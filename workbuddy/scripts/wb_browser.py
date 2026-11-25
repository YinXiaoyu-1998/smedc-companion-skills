#!/usr/bin/env python3
"""bsk (BrowserSkill) host bridge for the WorkBuddy adapter.

Codex workflows default to an in-app browser and fall back to the local Chrome
profile. On WorkBuddy the equivalent is the ``bsk`` CLI plus the Chrome
BrowserSkill extension: a dedicated Agent Window reuses the employee's existing
Chrome login. No cookies are copied, no UA is spoofed and no private API is
called.

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

SESSION_LOST_MARKERS = ("session not registered", "already stopped", "no active sessions")


def run_bsk(args: list[str], *, timeout: int = 90) -> dict[str, Any]:
    completed = subprocess.run([BSK, *args, "--json"], capture_output=True,
                               text=True, timeout=timeout)
    text = completed.stdout.strip()
    if not text:
        return {"ok": False, "returncode": completed.returncode,
                "stderr": completed.stderr.strip()}
    start = text.find("{")
    bracket = text.find("[")
    if bracket >= 0 and (start < 0 or bracket < start):
        start = bracket
    if start < 0:
        return {"ok": False, "raw": text[:500], "stderr": completed.stderr.strip()}
    try:
        payload = json.loads(text[start:])
    except json.JSONDecodeError:
        return {"ok": False, "raw": text[:500]}
    if isinstance(payload, dict) and (
        payload.get("code") or payload.get("exit_code") not in (None, 0)
    ):
        result: dict[str, Any] = {
            "ok": False, "code": payload.get("code"),
            "message": payload.get("message"), "hint": payload.get("hint"),
        }
        message = str(payload.get("message", ""))
        if any(marker in message for marker in SESSION_LOST_MARKERS):
            result["recovery"] = (
                "The bsk daemon may have auto-upgraded and dropped the session. "
                "Run `doctor`, then `session-start` and `sync` again; never reuse "
                "a stale session id."
            )
        return result
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
    """Capture one download by passing bsk's required download trigger.

    ``bsk download --out <PATH> --session <SID> [TARGET]`` clicks TARGET and
    captures the resulting file; TARGET is mandatory in practice. Since it is
    a click, the caller must also pass the control context and observation
    from ``sync``. ``--dest`` maps to bsk's ``--out`` flag.
    """
    trigger = args.ref or args.selector or args.target
    if not trigger:
        return emit({"ok": False,
                     "error": "bsk download requires --target/--ref/--selector for the download trigger"})
    if not (args.context and args.observation):
        return emit({"ok": False,
                     "error": "download trigger is a click; --context and --observation from sync are required"})
    cmd = ["download", "--session", args.session, "--out", args.dest,
           "--context", args.context, "--observation", args.observation]
    if args.ref:
        cmd += ["--ref", args.ref]
    elif args.selector:
        cmd += ["--selector", args.selector]
    else:
        cmd += [args.target]
    if args.overwrite:
        cmd += ["--overwrite"]
    cmd += ["--timeout", args.bsk_timeout]
    return emit(run_bsk(cmd, timeout=args.timeout_s))


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

    p = sub.add_parser("download", help="capture one download; --dest maps to bsk --out")
    p.add_argument("--session", required=True)
    p.add_argument("--dest", required=True)
    p.add_argument("--target", help="snapshot ref or CSS selector for the download trigger")
    p.add_argument("--ref", help="explicit snapshot ref for the trigger")
    p.add_argument("--selector", help="explicit CSS selector for the trigger")
    p.add_argument("--context", help="control context from sync")
    p.add_argument("--observation", help="observation id from sync")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--bsk-timeout", default="2m", help="bsk native wait timeout")
    p.add_argument("--timeout-s", type=int, default=240, help="subprocess hard timeout")
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
