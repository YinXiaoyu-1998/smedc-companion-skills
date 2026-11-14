#!/usr/bin/env python3
"""Portable local workflow plans and evidence. All service/provider calls stay in the host."""
from __future__ import annotations
import argparse
from datetime import date, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import tomllib
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("Asia/Shanghai")


def encoded(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def regular(path):
    p = Path(os.path.abspath(path))
    if any(x.is_symlink() for x in [p, *p.parents]) or not p.is_file():
        raise ValueError("Expected ordinary non-symlink file")
    return p


def load(path):
    return json.loads(regular(path).read_text())


def atomic(path, value):
    p = Path(os.path.abspath(path))
    if any(x.is_symlink() for x in [p, *p.parents]):
        raise ValueError("Symlink destination forbidden")
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + p.name, dir=p.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, p)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def manifest():
    return load(ROOT / "manifest.json")


def window(value):
    kind = value["workflowType"]
    if kind not in manifest()["workflows"]:
        raise ValueError("Unknown workflow")
    if value.get("resume"):
        selected = value["resume"]
    else:
        current = datetime.fromisoformat(value["now"])
        if current.tzinfo is None:
            raise ValueError("Timezone-aware clock required")
        today = current.astimezone(TZ).date()
        if kind == "weekly-business-report":
            end = today - timedelta(days=today.weekday() + 1)
            start = end - timedelta(days=6)
        else:
            start = today - timedelta(days=1)
            end = today if kind == "meituan-review-operations" else start
        selected = {"startDate": start.isoformat(), "endDate": end.isoformat()}
    start, end = date.fromisoformat(selected["startDate"]), date.fromisoformat(
        selected["endDate"]
    )
    if start > end:
        raise ValueError("Invalid frozen date window")
    return {
        "window": selected,
        "timezone": "Asia/Shanghai",
        "resumed": bool(value.get("resume")),
    }


def readiness(value):
    definition = manifest()["workflows"][value["workflowType"]]
    checks = []
    for capability in [
        *definition["capabilities"],
        *definition.get("optionalCapabilities", []),
    ]:
        observed = value["checks"].get(
            capability,
            {"status": "unavailable", "nextStep": "Run the actual capability check"},
        )
        if observed["status"] not in {
            "ready",
            "needs_configuration",
            "needs_login",
            "permission_denied",
            "unsupported",
            "unavailable",
        }:
            raise ValueError("Unsupported readiness status")
        if "sampleStatus" in observed and observed["sampleStatus"] not in {
            "verified", "no_sample", "not_checked"
        }:
            raise ValueError(
                "Unsupported sampleStatus: use verified, no_sample or not_checked; "
                "put the observation method in nextStep"
            )
        checks.append(
            {
                "capability": capability,
                "status": observed["status"],
                "nextStep": observed.get("nextStep", ""),
                "checkedAt": value["checkedAt"],
                **(
                    {"sampleStatus": observed["sampleStatus"]}
                    if "sampleStatus" in observed
                    else {}
                ),
            }
        )
    local_ready = all(
        c["status"] == "ready"
        for c in checks
        if c["capability"] in definition["capabilities"]
    )
    mail_ready = not value.get("mailEnabled") or all(
        c["status"] == "ready"
        for c in checks
        if c["capability"] in {"email_identity", "sent_mail_lookup"}
    )
    return {
        "checks": checks,
        "localReady": local_ready,
        "deliveryReady": mail_ready,
        "firstRunVerification": "not_run",
        "installationState": "paused",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation",
        choices=[
            "window",
            "migration",
            "readiness",
            "install",
            "cleanup",
            "cleanup-temporary",
            "lock",
            "save",
            "host-read",
            "review-task",
            "download-proof",
            "save-chunk",
            "review-sync-proof",
            "review-sync-intent",
            "prepare-workspace",
            "execution-plan",
        ],
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path)
    source.add_argument("--json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        value = json.loads(args.json) if args.json is not None else load(args.input)
        if args.operation == "execution-plan":
            from execution import plan

            result = plan(value)
        elif args.operation == "prepare-workspace":
            from lifecycle import prepare_workspace

            result = prepare_workspace(value)
        elif args.operation == "review-sync-intent":
            from review_sync_proof import intent

            result = intent(value)
        elif args.operation == "review-sync-proof":
            from review_sync_proof import proof

            result = proof(value)
        elif args.operation == "save-chunk":
            from lifecycle import save_chunk

            result = save_chunk(value)
        elif args.operation == "download-proof":
            from transfer_proof import proof

            result = proof(value)
        elif args.operation == "review-task":
            from review_policy import task

            result = task(value)
        elif args.operation == "host-read":
            import re

            if not re.fullmatch("[A-Za-z0-9_-]{1,64}", value["taskId"]):
                raise ValueError("Invalid task id")
            home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).resolve()
            target = regular(home / "automations" / value["taskId"] / "automation.toml")
            result = tomllib.loads(target.read_text())
            if result.get("id") != value["taskId"]:
                raise ValueError("Native task id differs")
        elif args.operation == "save":
            if args.output is None:
                raise ValueError("State output path required")
            atomic(args.output, value)
            result = {"saved": True}
        elif args.operation == "cleanup-temporary":
            from lifecycle import cleanup_temporary

            result = cleanup_temporary(value)
        elif args.operation in {"cleanup", "lock"}:
            from lifecycle import cleanup, lock

            result = cleanup(value) if args.operation == "cleanup" else lock(value)
        elif args.operation == "migration":
            from migration import build

            result = build(value)
        elif args.operation == "install":
            from installation import install

            result = install(value)
        elif args.operation == "readiness":
            result = readiness(value)
        else:
            result = window(value)
        if args.output is not None and args.operation != "save":
            atomic(args.output, result)
            print(
                json.dumps(
                    {
                        "saved": True,
                        **{
                            k: result[k]
                            for k in ["recordCount", "chunkCount", "stage"]
                            if k in result
                        },
                    }
                )
            )
        else:
            print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    except (ValueError, KeyError, OSError, TypeError) as error:
        print("workflow: " + str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
