#!/usr/bin/env python3
"""Mail-stage degradation for the WorkBuddy host adapter.

The distributed workflows require the host's native Gmail namespace and an
``allowedSender`` identity that matches the frozen central configuration.
WorkBuddy only exposes an Agent Mail alias, which is a different sender and
cannot satisfy the central ``email`` intent identity check. Per the upstream
execution definition, an unavailable mail stage blocks only that stage: the
weekly report is delivered locally and review drafts stay in the workbook.

This module therefore NEVER sends mail. It produces an auditable, hash-bound
local delivery record and marks the stage ``blocked``. Do not add SMTP, a
second mail server, or a sender override here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

BLOCK_REASON = "native_gmail_namespace_and_allowed_sender_unavailable"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def deliver_locally(artifact: Path, workspace: Path) -> dict:
    """Copy the artifact without ever silently overwriting earlier evidence."""
    workspace = workspace.expanduser().resolve()
    target_dir = workspace / "delivery"
    target_dir.mkdir(parents=True, exist_ok=True)
    source = artifact.resolve()
    source_hash = sha256(source)
    target = target_dir / artifact.name
    reused = False
    if target.exists():
        if sha256(target) == source_hash:
            reused = True
        else:
            target = target_dir / f"{artifact.stem}-{source_hash[:8]}{artifact.suffix}"
            if target.exists() and sha256(target) != source_hash:
                raise ValueError("delivery name collision; use a distinct run workspace")
            reused = False
    if not target.exists():
        shutil.copy2(source, target)
    return {
        "path": str(target),
        "sha256": sha256(target),
        "bytes": target.stat().st_size,
        "reused": reused,
    }


def build_plan(args: argparse.Namespace) -> dict:
    artifact = Path(args.artifact).expanduser().resolve()
    if not artifact.is_file():
        raise FileNotFoundError(f"artifact not found: {artifact}")
    workspace = Path(args.workspace).expanduser()
    if not workspace.is_absolute():
        raise ValueError("workspace must be an absolute dedicated directory")
    recipients = json.loads(args.recipients) if args.recipients else []
    record = {
        "ok": True,
        "stage": "email",
        "status": "blocked",
        "reason": BLOCK_REASON,
        "workflowType": args.workflow,
        "allowedSender": args.allowed_sender,
        "hostMailSender": args.host_sender,
        "recipients": recipients,
        "providerReadback": "unavailable",
        "sent": False,
        "localDelivery": deliver_locally(artifact, workspace),
        "observedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "nextStep": (
            "Record the blocked mail stage in the central run, keep the final "
            "report/review workbook locally, and continue independent stages. "
            "Do not retry with a different sender; a central configuration "
            "change belongs to the service owner, not this adapter."
        ),
    }
    return record


def cmd_plan(args: argparse.Namespace) -> int:
    print(json.dumps(build_plan(args), ensure_ascii=False, indent=2))
    return 0


def cmd_note(_: argparse.Namespace) -> int:
    print(json.dumps({
        "policy": "official-degradation",
        "reference": "skills/smedc-workflows/references/execution.md",
        "weeklyReport": "no native mail -> local HTML delivery, retain final report",
        "reviewDrafts": "no native mail -> keep frozen nine-column workbook; publication unaffected",
        "forbidden": ["SMTP", "sender override", "second mail server", "fabricated readback"],
    }, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan", help="produce a blocked mail-stage record and local delivery")
    p.add_argument("--workflow", required=True)
    p.add_argument("--artifact", required=True)
    p.add_argument("--workspace", required=True)
    p.add_argument("--allowed-sender", required=True)
    p.add_argument("--host-sender", required=True)
    p.add_argument("--recipients", required=True, help="JSON array from the frozen snapshot")
    p.set_defaults(func=cmd_plan)
    p = sub.add_parser("note", help="print the degradation policy")
    p.set_defaults(func=cmd_note)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
