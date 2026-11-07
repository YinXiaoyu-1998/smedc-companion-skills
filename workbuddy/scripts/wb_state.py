#!/usr/bin/env python3
"""Local run-state machine for the WorkBuddy host adapter.

The Codex host keeps an unfinished run in a persistent Goal. WorkBuddy has no
Goal lifecycle tool, so the same continuation contract is expressed as an
atomically persisted state file inside a dedicated per-run workspace.

This module never calls SMEDC, never sends mail and never starts a schedule.
It only records facts that the invoking agent has already verified. Central
claim/check/record intents are still issued by the agent through the native
``mcp__smedc__*`` tools; this file is the local progress index, not proof of
success on the server.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
OPEN = "open"
CLOSED = "closed"
OUTCOMES = ("succeeded", "partial", "needs_attention", "failed", "unknown")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def state_hash(state: dict) -> str:
    payload = {k: v for k, v in state.items() if k != "stateHash"}
    return hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()


def resolve_root(raw: str) -> Path:
    """Reject shared roots, symlinked roots and non-absolute paths."""
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError("workspace root must be an absolute path")
    resolved = path.resolve()
    home = Path.home().resolve()
    if resolved in (home, Path("/"), Path("/tmp").resolve(), Path("/Users").resolve()):
        raise ValueError("workspace root must be a dedicated directory, not a shared root")
    if path.is_symlink():
        raise ValueError("workspace root must not be a symlink")
    return resolved


def state_path(root: Path) -> Path:
    return root / "state.json"


def atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".wb-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def save(state: dict, root: Path) -> dict:
    state["updatedAt"] = now()
    state["revision"] = int(state.get("revision", 0)) + 1
    state["stateHash"] = state_hash(state)
    atomic_write(state_path(root), json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    return state


def load(root: Path) -> dict:
    path = state_path(root)
    if not path.exists():
        raise FileNotFoundError(f"no run state at {path}")
    state = json.loads(path.read_text(encoding="utf-8"))
    expected = state.get("stateHash")
    if not expected or state_hash(state) != expected:
        raise ValueError("run state hash mismatch; refusing to resume a tampered run")
    if state.get("schemaVersion") != SCHEMA_VERSION:
        raise ValueError("unsupported run state schema version")
    return state


def evidence_for(paths: list[str]) -> list[dict]:
    result = []
    for raw in paths:
        p = Path(raw).expanduser().resolve()
        if not p.is_file():
            raise FileNotFoundError(f"evidence file not found: {p}")
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        result.append({"path": str(p), "sha256": digest})
    return result


def cmd_init(args: argparse.Namespace) -> int:
    root = resolve_root(args.root)
    if state_path(root).exists():
        raise ValueError("run state already exists; use resume, do not open a second run")
    window = json.loads(args.window) if args.window else {}
    state = {
        "schemaVersion": SCHEMA_VERSION,
        "host": "workbuddy",
        "workflowType": args.workflow,
        "runId": args.run_id,
        "bindingHash": args.binding_hash,
        "window": window,
        "createdAt": now(),
        "status": OPEN,
        "completed": {},
        "blocked": {},
        "outcome": None,
        "revision": 0,
    }
    save(state, root)
    print(json.dumps({"ok": True, "runId": args.run_id, "statePath": str(state_path(root))},
                     ensure_ascii=False))
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    print(json.dumps(load(resolve_root(args.root)), ensure_ascii=False, indent=2))
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    state = load(resolve_root(args.root))
    if state.get("status") != OPEN:
        raise ValueError("only an open run can be resumed")
    if args.run_id and args.run_id != state["runId"]:
        raise ValueError("resume runId does not match the saved runId")
    print(json.dumps({"ok": True, "runId": state["runId"],
                      "revision": state["revision"],
                      "completed": sorted(state["completed"]),
                      "blocked": sorted(state["blocked"])}, ensure_ascii=False))
    return 0


def cmd_save_progress(args: argparse.Namespace) -> int:
    root = resolve_root(args.root)
    state = load(root)
    if state["status"] != OPEN:
        raise ValueError("cannot update progress on a closed run")
    state["completed"][args.task_id] = {
        "scopeHash": args.scope_hash,
        "evidence": evidence_for(args.evidence),
        "recordedAt": now(),
    }
    state["blocked"].pop(args.task_id, None)
    save(state, root)
    print(json.dumps({"ok": True, "taskId": args.task_id,
                      "revision": state["revision"]}, ensure_ascii=False))
    return 0


def cmd_mark_blocked(args: argparse.Namespace) -> int:
    root = resolve_root(args.root)
    state = load(root)
    if state["status"] != OPEN:
        raise ValueError("cannot block a closed run")
    state["blocked"][args.task_id] = {"reason": args.reason, "recordedAt": now()}
    save(state, root)
    print(json.dumps({"ok": True, "taskId": args.task_id,
                      "blocked": state["blocked"][args.task_id]}, ensure_ascii=False))
    return 0


def cmd_close(args: argparse.Namespace) -> int:
    root = resolve_root(args.root)
    state = load(root)
    if args.outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {OUTCOMES}")
    state["status"] = CLOSED
    state["outcome"] = args.outcome
    state["closedAt"] = now()
    save(state, root)
    print(json.dumps({"ok": True, "runId": state["runId"],
                      "outcome": args.outcome}, ensure_ascii=False))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    state = load(resolve_root(args.root))
    missing = []
    for task_id, entry in state["completed"].items():
        for item in entry["evidence"]:
            p = Path(item["path"])
            if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != item["sha256"]:
                missing.append({"taskId": task_id, "path": item["path"]})
    print(json.dumps({"ok": not missing, "runId": state["runId"],
                      "revision": state["revision"], "status": state["status"],
                      "brokenEvidence": missing}, ensure_ascii=False))
    return 0 if not missing else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="open a new run state")
    p.add_argument("--root", required=True)
    p.add_argument("--workflow", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--binding-hash", required=True)
    p.add_argument("--window", help="JSON window object")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("show")
    p.add_argument("--root", required=True)
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("resume", help="verify and report the open run for continuation")
    p.add_argument("--root", required=True)
    p.add_argument("--run-id")
    p.set_defaults(func=cmd_resume)

    p = sub.add_parser("save-progress", help="record a verified stage with evidence hashes")
    p.add_argument("--root", required=True)
    p.add_argument("--task-id", required=True)
    p.add_argument("--scope-hash", required=True)
    p.add_argument("--evidence", nargs="*", default=[])
    p.set_defaults(func=cmd_save_progress)

    p = sub.add_parser("mark-blocked")
    p.add_argument("--root", required=True)
    p.add_argument("--task-id", required=True)
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_mark_blocked)

    p = sub.add_parser("close")
    p.add_argument("--root", required=True)
    p.add_argument("--outcome", required=True)
    p.set_defaults(func=cmd_close)

    p = sub.add_parser("verify", help="re-hash every recorded evidence file")
    p.add_argument("--root", required=True)
    p.set_defaults(func=cmd_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
