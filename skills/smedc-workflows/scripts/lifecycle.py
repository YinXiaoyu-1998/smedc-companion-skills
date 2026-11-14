"""Run-scoped atomic lock/checkpoints and cleanup after live central readback."""

from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

from workflow import atomic, load, regular


def lock(value):
    path = Path(value["path"])
    if any(p.is_symlink() for p in [path, *path.parents]):
        raise ValueError("Symlink lock forbidden")
    if value["mode"] == "acquire":
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            existing = load(path)
            if existing.get("runId") == value["runId"]:
                return {"acquired": True, "resumed": True}
            raise ValueError(
                "Existing lock cannot be stolen; verify old owner and reconcile centrally"
            )
        with os.fdopen(fd, "w") as stream:
            json.dump(
                {"runId": value["runId"], "workflowId": value["workflowId"]}, stream
            )
            stream.flush()
            os.fsync(stream.fileno())
        return {"acquired": True, "resumed": False}
    if value["mode"] != "release" or load(path).get("runId") != value["runId"]:
        raise ValueError("Lock owner differs")
    regular(path).unlink()
    return {"released": True}


def cleanup(value):
    proof = value["centralProof"]
    files = value["files"]
    actions = {a["actionId"]: a for a in proof.get("actions", [])}
    if (
        not files
        or proof.get("runId") != value["runId"]
        or proof.get("workflowId") != value["workflowId"]
    ):
        raise ValueError("Central confirmed receipt binding missing")
    for item in files:
        action = actions.get(item["actionId"], {})
        if (
            action.get("identity", {}).get("kind") == "upload"
            and action["identity"].get("sourceHash") != item["sha256"]
        ):
            raise ValueError("Original hash differs from confirmed upload identity")
        if (
            action.get("state") != "confirmed"
            or action.get("runId") != value["runId"]
            or action.get("receipt", {}).get("state") != "confirmed"
        ):
            raise ValueError("Central confirmed receipt required for each original")
    expires = datetime.fromisoformat(proof["expiresAt"].replace("Z", "+00:00"))
    if expires <= datetime.now(timezone.utc):
        raise ValueError("Central readback expired; refresh before cleanup")
    root = Path(value["runRoot"])
    if (
        root == Path.home()
        or root == Path("/")
        or any(p.is_symlink() for p in [root, *root.parents])
    ):
        raise ValueError("Unsafe run root")
    owner = regular(value["lockOwnerPath"])
    if load(owner).get("runId") != value["runId"]:
        raise ValueError("Run does not own lock")
    checked = []
    for item in files:
        path = regular(item["path"])
        if (
            root not in path.parents
            or path == owner
            or item.get("finalReport")
            or path.suffix.lower() == ".html"
            or path.name in {"state.json", "run.json", "installation.json"}
        ):
            raise ValueError("File outside run or protected final/state file")
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if sha != item["sha256"]:
            raise ValueError("Original changed since verified receipt")
        checked.append((path, path.stat(), sha))
    if not value.get("resultPath"):
        raise ValueError("Durable cleanup result path required")
    result_path = Path(value["resultPath"])
    if result_path in [path for path, _, _ in checked] or result_path == owner:
        raise ValueError("Cleanup result must be outside deletion list and lock")
    result = {
        "runId": value["runId"],
        "deleted": [],
        "retained": [str(path) for path, _, _ in checked],
        "centralConfirmed": True,
        "status": "running",
    }
    atomic(result_path, result)
    try:
        for path, before, sha in checked:
            if datetime.now(timezone.utc) >= expires:
                raise ValueError("Central readback expired during cleanup")
            if load(owner).get("runId") != value["runId"]:
                raise ValueError("Lock changed during cleanup")
            after = regular(path).stat()
            if (after.st_ino, after.st_dev, after.st_size, after.st_mtime_ns) != (
                before.st_ino,
                before.st_dev,
                before.st_size,
                before.st_mtime_ns,
            ):
                raise ValueError("Original changed before deletion")
            if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                raise ValueError("Original hash changed")
            path.unlink()
            result["deleted"].append(str(path))
            result["retained"].remove(str(path))
            atomic(result_path, result)
    except (ValueError, OSError) as error:
        result.update(status="blocked", error=str(error))
        atomic(result_path, result)
        raise
    result["status"] = "succeeded"
    atomic(result_path, result)
    return result


def cleanup_temporary(value):
    """Delete only registered scratch files after a successful central finish."""
    run_id = value["runId"]
    workflow_id = value["workflowId"]
    proof = value["centralProof"]
    expires = datetime.fromisoformat(proof["expiresAt"].replace("Z", "+00:00"))
    if (
        proof["runId"] != run_id
        or proof["workflowId"] != workflow_id
        or proof["status"] != "succeeded"
        or not proof["finishedAt"]
        or expires <= datetime.now(timezone.utc)
    ):
        raise ValueError("Fresh successful central finish required")

    root = Path(value["runRoot"])
    if (
        not root.is_absolute()
        or root.name != run_id
        or root != root.resolve()
        or not root.is_dir()
    ):
        raise ValueError("Canonical run directory required")
    scratch = root / "temporary"
    if scratch.is_symlink():
        raise ValueError("Symlink temporary directory forbidden")
    result_path = root / "temporary-cleanup-result.json"
    owner = regular(value["lockOwnerPath"])
    if owner.is_relative_to(scratch):
        raise ValueError("Run lock must be outside the temporary directory")

    def check_lock_and_proof():
        lock_state = load(owner)
        if (
            lock_state.get("runId") != run_id
            or lock_state.get("workflowId") != workflow_id
        ):
            raise ValueError("Run does not own the lock")
        if expires <= datetime.now(timezone.utc):
            raise ValueError("Central readback expired during cleanup")

    check_lock_and_proof()
    progress_path = regular(root / "progress.json")
    progress = load(progress_path)
    if progress.get("runId") != run_id:
        raise ValueError("Progress must belong to this run")
    for stage in progress["completed"].values():
        if any(
            Path(item["path"]).resolve().is_relative_to(scratch)
            for item in stage["evidence"]
        ):
            raise ValueError("Retained progress references temporary files")

    files = value["files"]
    paths = [Path(item["path"]) for item in files]
    if len(set(paths)) != len(paths) or any(
        not path.is_absolute()
        or not path.is_relative_to(scratch)
        or ".." in path.parts
        or path == scratch
        or path.suffix.lower() == ".html"
        for path in paths
    ):
        raise ValueError("Only distinct run temporary files may be deleted")

    result = {
        "runId": run_id,
        "workflowId": workflow_id,
        "files": files,
        "deleted": [],
        "retained": [str(path) for path in paths],
        "status": "running",
    }
    if result_path.exists():
        previous = load(result_path)
        if any(previous[k] != result[k] for k in ("runId", "workflowId", "files")):
            raise ValueError("Temporary cleanup manifest differs from the saved result")
        result["deleted"] = previous["deleted"]
        result["retained"] = previous["retained"]
        if "inFlight" in previous:
            result["inFlight"] = previous["inFlight"]

    def matches(path, item):
        with regular(path).open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != item["sha256"]:
                raise ValueError("Temporary file hash changed")

    remaining = []
    try:
        for path, item in zip(paths, files):
            if str(path) in result["deleted"]:
                if path.exists() or path.is_symlink():
                    raise ValueError("A previously removed temporary file reappeared")
                continue
            if (
                not path.exists()
                and not path.is_symlink()
                and result.get("inFlight") == str(path)
            ):
                result["deleted"].append(str(path))
                result["retained"].remove(str(path))
                result.pop("inFlight")
                continue
            matches(path, item)
            remaining.append((path, item))

        for path, item in remaining:
            check_lock_and_proof()
            matches(path, item)
            result["inFlight"] = str(path)
            atomic(result_path, result)
            path.unlink()
            result["deleted"].append(str(path))
            result["retained"].remove(str(path))
            del result["inFlight"]
            atomic(result_path, result)
        result.pop("inFlight", None)
        result["status"] = "succeeded"
    except (OSError, ValueError) as error:
        result.update(status="blocked", error=str(error))
        atomic(result_path, result)
        raise
    atomic(result_path, result)
    return {"status": result["status"], "deletedFiles": len(result["deleted"])}


def save_chunk(value):
    import fcntl
    import re

    target = Path(value["path"])
    if not target.is_absolute() or any(
        p.is_symlink() for p in [target, *target.parents]
    ):
        raise ValueError("Canonical state path required")
    if not re.fullmatch("[A-Za-z0-9_-]{1,64}", value["uploadId"]):
        raise ValueError("Invalid local upload id")
    content = value["text"].encode("utf-8")
    offset = value["offset"]
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("Invalid local chunk offset")
    target.parent.mkdir(parents=True, exist_ok=True)
    expected = value["checksumSha256"]
    if (
        target.exists()
        and hashlib.sha256(regular(target).read_bytes()).hexdigest() == expected
    ):
        return {"saved": True, "alreadyPresent": True}
    partial = target.with_name("." + target.name + ".incoming-" + value["uploadId"])
    if partial.is_symlink():
        raise ValueError("Symlink partial state forbidden")
    fd = os.open(partial, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "r+b") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        if size == offset:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        elif size >= offset + len(content):
            stream.seek(offset)
            if stream.read(len(content)) != content:
                raise ValueError("Local chunk conflicts with prior write")
        else:
            raise ValueError("Local chunk sequence gap")
        if value.get("final"):
            stream.seek(0)
            payload = stream.read()
            if hashlib.sha256(payload).hexdigest() != expected:
                raise ValueError("Local final state checksum differs")
            json.loads(payload)
            os.replace(partial, target)
            directory_fd = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    return {"saved": bool(value.get("final")), "nextOffset": offset + len(content)}


def prepare_workspace(value):
    import re
    import tempfile

    raw = Path(value["path"]).expanduser()
    if not raw.is_absolute():
        raise ValueError("Absolute proposed workspace required")
    root = raw.resolve()
    if root in {
        Path("/"),
        Path.home().resolve(),
        Path(tempfile.gettempdir()).resolve(),
        (Path.home() / "Downloads").resolve(),
    }:
        raise ValueError("Choose a dedicated workflow workspace, not a shared root")
    if not all(
        re.fullmatch("[A-Za-z0-9_-]{1,64}", value[key])
        for key in ["workflowId", "installationId"]
    ):
        raise ValueError("Stable workflow and installation IDs required")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.stat().st_uid != os.getuid():
        raise ValueError("Workspace must belong to current user")
    marker = root / ".smedc-workspace.json"
    identity = {
        "schemaVersion": 1,
        "workflowId": value["workflowId"],
        "installationId": value["installationId"],
    }
    if marker.exists():
        if load(marker) != identity:
            raise ValueError("Workspace belongs to another workflow/installation")
    elif any(item.name != ".DS_Store" for item in root.iterdir()):
        raise ValueError(
            "Choose an empty dedicated folder; existing files are preserved"
        )
    else:
        atomic(marker, identity)
    fd, probe = tempfile.mkstemp(prefix=".write-check-", dir=root)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(b"workspace-check")
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        Path(probe).unlink(missing_ok=True)
    return {
        "workspaceRoot": str(root),
        "statePath": str(root / "state.json"),
        "runsDirectory": str(root / "runs"),
        "builderDirectory": str(root / "builder"),
        "check": {
            "capability": "workspace",
            "status": "ready",
            "nextStep": "",
            "checkedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        },
    }
