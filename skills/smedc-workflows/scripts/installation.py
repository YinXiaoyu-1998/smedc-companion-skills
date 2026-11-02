"""Bounded selected-subtree installer; no launcher/host/account configuration edits."""

from __future__ import annotations
import hashlib
import os
from pathlib import Path
import re
import shutil
import tempfile

from workflow import atomic, digest, manifest, regular

IGNORED = {"__pycache__", ".DS_Store", ".pytest_cache"}


def tree_hash(path):
    root = Path(path)
    if any(p.is_symlink() for p in [root, *root.parents]):
        raise ValueError("Symlink skill root forbidden")
    entries = []
    for item in sorted(root.rglob("*")):
        if any(part in IGNORED for part in item.relative_to(root).parts):
            continue
        if item.is_symlink():
            raise ValueError("Symlink skill member forbidden")
        if item.is_file():
            entries.append(
                [
                    item.relative_to(root).as_posix(),
                    hashlib.sha256(item.read_bytes()).hexdigest(),
                ]
            )
    return digest(entries)


def install(value):
    package = manifest()
    selected = value["selected"]
    if not selected or len(set(selected)) != len(selected):
        raise ValueError("Choose unique workflows explicitly")
    wanted = {Path(__file__).resolve().parents[1].name}
    for name in selected:
        if name not in package["workflows"]:
            raise ValueError("Unknown requested workflow")
        wanted.update(package["workflows"][name]["dependencies"])
    source = Path(value["sourceSkillsRoot"])
    destination = Path(value["destinationRoot"])
    if not re.fullmatch("[0-9a-f]{40}", value["sourceRevision"]):
        raise ValueError("Verified source Git commit required")
    if any(
        p.is_symlink()
        for p in [source, destination, *source.parents, *destination.parents]
    ):
        raise ValueError("Canonical non-symlink skill directories required")
    if (
        source == destination
        or source in destination.parents
        or destination in source.parents
    ):
        raise ValueError("Source and installation must be separate")
    recovery = Path(
        value.get("recoveryRoot", destination.parent / ".smedc-workflow-recovery")
    )
    if (
        recovery == destination
        or destination in recovery.parents
        or any(p.is_symlink() for p in [recovery, *recovery.parents])
    ):
        raise ValueError("Recovery must be outside skill discovery")
    hashes = {}
    changed = []
    reused = []
    existing_hashes = {}
    for name in sorted(wanted):
        regular(source / name / "SKILL.md")
        regular(source / name / "agents" / "openai.yaml")
        hashes[name] = tree_hash(source / name)
        if (destination / name).exists():
            current = tree_hash(destination / name)
            existing_hashes[name] = current
            if current == hashes[name]:
                reused.append(name)
                continue
            if value.get("expectedInstalledHashes", {}).get(name) != current:
                raise ValueError(
                    "needs_review: installed subtree differs; compare and preserve changes before approved replacement: "
                    + name
                )
        changed.append(name)
    # All conflicts are checked before any mutation. Retain recovery through host reload verification.
    recovery.mkdir(parents=True, exist_ok=True)
    destination.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="stage-", dir=recovery))
    installed = []
    backups = {}
    try:
        for name in changed:
            shutil.copytree(
                source / name, stage / name, ignore=shutil.ignore_patterns(*IGNORED)
            )
            if tree_hash(stage / name) != hashes[name]:
                raise ValueError("Staged subtree content mismatch")
        for name in changed:
            target = destination / name
            if target.exists():
                if tree_hash(target) != existing_hashes[name]:
                    raise ValueError("Installed subtree changed during staging")
                backup = recovery / (name + "-" + existing_hashes[name][:16])
                if backup.exists():
                    raise ValueError(
                        "Recovery already exists; inspect it before replacing"
                    )
                os.rename(target, backup)
                backups[name] = str(backup)
            try:
                os.rename(stage / name, target)
            except BaseException:
                if name in backups:
                    os.rename(backups[name], target)
                raise
            if tree_hash(target) != hashes[name]:
                raise ValueError("Installed content readback differs")
            installed.append(name)
    finally:
        shutil.rmtree(stage)
    lock = {
        "packageVersion": package["packageVersion"],
        "sourceRevision": value["sourceRevision"],
        "selected": selected,
        "skillHashes": hashes,
        "recoveryCopies": backups,
        "hostReload": "pending",
    }
    atomic(recovery / "installation.json", lock)
    return {**lock, "installed": installed, "reused": reused, "tasksCreated": False}
