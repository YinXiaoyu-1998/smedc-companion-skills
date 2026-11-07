#!/usr/bin/env python3
"""bsk (BrowserSkill) host bridge for the WorkBuddy adapter.

Codex workflows default to IAB and fall back to the local Chrome profile. On
WorkBuddy the equivalent is the ``bsk`` CLI plus the Chrome BrowserSkill
extension: a dedicated Agent Window reuses the employee's existing Chrome
login. No cookies are copied, no UA is spoofed and no private API is called.

Every mutating action requires the control context returned by
``cooperate sync --policy target``; the default ``strict`` policy rejects
click/evaluate. This bridge keeps those tokens explicit instead of caching
them in a file.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any

BSK = "bsk"


def run_bsk(args: list[str], *, timeout: int = 90) -> dict[str, Any]:
    completed = subprocess.run([BSK, *args, "--json"], capture_output=True,
                               text=True, timeout=timeout)
    text = completed.stdout.strip()
    if not text:
        return {"ok": False, "returncode": completed.returncode,
                "stderr": completed.stderr.strip()}
    start = text.find("{")
    if start < 0:
        return {"ok": False, "raw": text[:500], "stderr": completed.stderr.strip()}
    try:
        payload = json.loads(text[start:])
    except json.JSONDecodeError:
        return {"ok": False, "raw": text[:500]}
    if isinstance(payload, dict) and payload.get("code"):
        return {"ok": False, "code": payload["code"],
                "message": payload.get("message"), "hint": payload.get("hint")}
    return {"ok": completed.returncode == 0, "data": payload}


def emit(result: dict[str, Any]) -> int:
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


def cmd_doctor(_: argparse.Namespace) -> int:
    status = run_bsk(["status"], timeout=30)
    browsers = run_bsk(["browsers"], timeout=30)
    return emit({"ok": bool(status.get("ok") and browsers.get("ok")),
                 "status": status.get("data"), "browsers": browsers.get("data")})


def cmd_session_start(args: argparse.Namespace) -> int:
    cmd = ["session", "start", "--name", args.name, "--no-focus"]
    result = run_bsk(cmd)
    if result.get("ok") and isinstance(result.get("data"), dict):
        result["sessionId"] = result["data"].get("session_id")
    return emit(result)


def cmd_sync(args: argparse.Namespace) -> int:
    result = run_bsk(["cooperate", "sync", "--session", args.session,
                      "--policy", "target"])
    if result.get("ok") and isinstance(result.get("data"), dict):
        data = result["data"]
        result["contextId"] = data.get("context_id")
        result["observationId"] = data.get("observation_id")
        result["controlPolicy"] = data.get("control_policy")
        result["ready"] = data.get("state", {}).get("mode") == "ready"
    return emit(result)


def cmd_navigate(args: argparse.Namespace) -> int:
    cmd = ["navigate", "--session", args.session, args.url,
           "--wait-until", args.wait_until, "--timeout", args.timeout]
    if args.context:
        cmd += ["--context", args.context]
    return emit(run_bsk(cmd))


def cmd_snapshot(args: argparse.Namespace) -> int:
    return emit(run_bsk(["snapshot", "--session", args.session,
                         "--max-tokens", str(args.max_tokens)]))


def cmd_click(args: argparse.Namespace) -> int:
    if not args.context or not args.observation:
        return emit({"ok": False, "error": "click requires --context and --observation from sync"})
    return emit(run_bsk(["click", "--session", args.session, args.ref,
                        "--context", args.context,
                        "--observation", args.observation]))


def cmd_evaluate(args: argparse.Namespace) -> int:
    if not args.context or not args.observation:
        return emit({"ok": False, "error": "evaluate requires --context and --observation from sync"})
    return emit(run_bsk(["evaluate", "--session", args.session, args.expression,
                        "--context", args.context,
                        "--observation", args.observation]))


def cmd_download(args: argparse.Namespace) -> int:
    """Capture one browser download. The caller must have triggered the export."""
    return emit(run_bsk(["download", "--session", args.session,
                         "--output", args.dest], timeout=args.timeout_s))


def cmd_stop(args: argparse.Namespace) -> int:
    return emit(run_bsk(["session", "stop", args.session]))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("doctor")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("session-start")
    p.add_argument("--name", required=True)
    p.set_defaults(func=cmd_session_start)

    p = sub.add_parser("sync", help="establish target control context before interactions")
    p.add_argument("--session", required=True)
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("navigate")
    p.add_argument("--session", required=True)
    p.add_argument("--url", required=True)
    p.add_argument("--context")
    p.add_argument("--wait-until", default="domcontentloaded")
    p.add_argument("--timeout", default="45s")
    p.set_defaults(func=cmd_navigate)

    p = sub.add_parser("snapshot")
    p.add_argument("--session", required=True)
    p.add_argument("--max-tokens", type=int, default=2500)
    p.set_defaults(func=cmd_snapshot)

    p = sub.add_parser("click")
    p.add_argument("--session", required=True)
    p.add_argument("--ref", required=True)
    p.add_argument("--context")
    p.add_argument("--observation")
    p.set_defaults(func=cmd_click)

    p = sub.add_parser("evaluate")
    p.add_argument("--session", required=True)
    p.add_argument("--expression", required=True)
    p.add_argument("--context")
    p.add_argument("--observation")
    p.set_defaults(func=cmd_evaluate)

    p = sub.add_parser("download")
    p.add_argument("--session", required=True)
    p.add_argument("--dest", required=True)
    p.add_argument("--timeout-s", type=int, default=180)
    p.set_defaults(func=cmd_download)

    p = sub.add_parser("stop")
    p.add_argument("--session", required=True)
    p.set_defaults(func=cmd_stop)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (subprocess.TimeoutExpired, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
