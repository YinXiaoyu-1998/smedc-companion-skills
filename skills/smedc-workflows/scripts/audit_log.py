"""Durable per-call journal. No credentials, business decisions, retries or writes to services."""

import argparse
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid


def stamp():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat()


def redact(value):
    if isinstance(value, dict):
        return {
            k: (
                "<REDACTED>"
                if re.search(
                    r"authorization|cookie|password|secret|access.?token|refresh.?token|api.?key",
                    k,
                    re.I,
                )
                else redact(v)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r"(?i)\bBearer\s+[^\s\"']+", "Bearer <REDACTED>", value)
        value = re.sub(
            r"(?im)(authorization|cookie|password|access_token|refresh_token|api_key)\s*[:=]\s*[^\r\n]+",
            r"\1: <REDACTED>",
            value,
        )
    return value


def journal(run_dir):
    root = Path(run_dir)
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise ValueError("run-dir must be an existing absolute ordinary directory")
    path = root / "call-audit"
    path.mkdir(exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError("symlink journal refused")
    return path


def write_atomic(path, value):
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with tmp.open("x", encoding="utf-8") as f:
        os.chmod(tmp, 0o600)
        json.dump(redact(value), f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def call_path(run_dir, call_id):
    if not re.fullmatch(r"[a-f0-9]{32}", call_id):
        raise ValueError("invalid call id")
    return journal(run_dir) / (call_id + ".json")


def start(run_dir, meta):
    for k in ("stage", "tool", "effect"):
        if not isinstance(meta.get(k), str) or not meta[k]:
            raise ValueError("missing metadata: " + k)
    if meta["effect"] not in ("read", "local", "external_write"):
        raise ValueError("effect must be read, local or external_write")
    cid = uuid.uuid4().hex
    value = {
        "schemaVersion": 1,
        "callId": cid,
        "startedAt": stamp(),
        "startMonotonicNs": time.monotonic_ns(),
        "status": "started",
        "timeMeaning": "client pre-dispatch checkpoint; not server receipt time",
        "meta": meta,
    }
    write_atomic(call_path(run_dir, cid), value)
    return {"callId": cid, "startedAt": value["startedAt"]}


def finish(run_dir, call_id, status, payload):
    if status not in ("succeeded", "failed", "unknown"):
        raise ValueError("invalid final status")
    path = call_path(run_dir, call_id)
    with (journal(run_dir) / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        value = json.loads(path.read_text())
        if value["status"] not in ("started", "unknown"):
            raise ValueError("already finished; retain original outcome")
        if (
            status == "succeeded"
            and isinstance(payload, dict)
            and (payload.get("isError") or payload.get("exit_code") not in (None, 0))
        ):
            raise ValueError("error result cannot be marked succeeded")
        if status == "failed" and value["meta"]["effect"] == "external_write":
            if not (
                isinstance(payload, dict)
                and payload.get("confirmedNoCommit") is True
                and payload.get("verificationEvidence")
            ):
                status = "unknown"
        if value["status"] == "unknown":
            value.setdefault("priorOutcomes", []).append(
                {k: value[k] for k in ("status", "endedAt", "result")}
            )
        value.update(
            status=status,
            endedAt=stamp(),
            elapsedMs=round((time.monotonic_ns() - value["startMonotonicNs"]) / 1e6, 3),
            result=payload,
        )
        write_atomic(path, value)
    return {"callId": call_id, "status": status, "path": str(path)}


def check(run_dir):
    rows = [json.loads(p.read_text()) for p in journal(run_dir).glob("*.json")]
    pending = [r for r in rows if r["status"] in ("started", "unknown")]
    return {
        "calls": len(rows),
        "succeeded": sum(r["status"] == "succeeded" for r in rows),
        "failed": sum(r["status"] == "failed" for r in rows),
        "pendingCalls": [
            {"callId": r["callId"], "meta": r["meta"], "startedAt": r["startedAt"]}
            for r in pending
        ],
        "externalWriteUnknown": [
            r["callId"] for r in pending if r["meta"]["effect"] == "external_write"
        ],
        "journalComplete": not pending,
        "note": "Tool errors are execution events; business and evidence dispositions require separate verification.",
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["start", "finish", "run", "check"])
    p.add_argument("--run-dir", required=True)
    p.add_argument("--meta-json")
    p.add_argument("--call-id")
    p.add_argument("--status")
    p.add_argument("--payload-json")
    p.add_argument("--payload-file")
    argv = sys.argv[1:]
    split = argv.index("--") if "--" in argv else len(argv)
    command = argv[split + 1 :]
    a = p.parse_args(argv[:split])
    if a.action == "start":
        result = start(a.run_dir, json.loads(a.meta_json))
    elif a.action == "finish":
        payload = json.loads(
            Path(a.payload_file).read_text() if a.payload_file else a.payload_json
        )
        result = finish(a.run_dir, a.call_id, a.status, payload)
    elif a.action == "check":
        result = check(a.run_dir)
    else:
        if not command:
            p.error("run requires -- COMMAND ARGS")
        meta = json.loads(a.meta_json)
        cid = start(a.run_dir, meta)["callId"]
        try:
            proc = subprocess.run(
                command, capture_output=True, text=True, errors="replace"
            )
        except BaseException as exc:
            finish(
                a.run_dir,
                cid,
                "unknown",
                {"exceptionType": type(exc).__name__, "message": str(exc)},
            )
            raise
        status = (
            "succeeded"
            if proc.returncode == 0
            else "unknown" if meta["effect"] == "external_write" else "failed"
        )
        result = finish(
            a.run_dir,
            cid,
            status,
            {
                "exit_code": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
            },
        )
        print(json.dumps(result, ensure_ascii=False))
        print(redact(proc.stdout), end="")
        print(redact(proc.stderr), file=sys.stderr, end="")
        return proc.returncode
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
