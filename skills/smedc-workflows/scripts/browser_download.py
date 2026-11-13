"""Capture one observed BrowserSkill download into the current run."""
from hashlib import file_digest
import json
from pathlib import Path
import re
import stat
import subprocess
import sys
from zipfile import ZipFile, BadZipFile


def capture(request):
    root = Path(request["runRoot"])
    filename = request["filename"]
    if (
        not root.is_absolute() or root.resolve(strict=True) != root
        or not root.is_dir() or root.stat().st_mode & 0o077
        or not re.fullmatch(r"[\w().-]{1,180}\.(?:xlsx|zip)", filename)
        or not re.fullmatch(r"@e[0-9]+", request["ref"])
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", request["browserSession"])
        or not re.fullmatch(r"[a-f0-9-]{36}", request["contextId"])
        or type(request["tabId"]) is not int or request["tabId"] <= 0
    ):
        raise ValueError("Expected a private run directory and current observed browser target")
    target = root / filename
    if target.exists() or target.is_symlink():
        raise ValueError("Destination exists; reconcile the original file")
    command = [
        "bsk", "download", request["ref"], "--session", request["browserSession"],
        "--tab-id", str(request["tabId"]), "--context", request["contextId"],
        "--out", str(target), "--timeout", "40s", "--json",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=45)
        response = json.loads(result.stdout)
    except (subprocess.TimeoutExpired, ValueError):
        return {"state": "unknown", "reason": "download_result_unavailable"}
    if result.returncode != 0:
        reason = response.get("data", {}).get("reason")
        return {
            "state": "unknown",
            "reason": reason if isinstance(reason, str) and re.fullmatch(r"[a-z_]+", reason) else "download_failed",
        }
    if not target.is_file() or target.is_symlink():
        return {"state": "unknown", "reason": "missing_destination"}
    if not stat.S_ISREG(target.stat().st_mode):
        return {"state": "unknown", "reason": "invalid_destination"}
    try:
        with ZipFile(target) as archive:
            names = archive.namelist()
            if not names or (target.suffix == ".xlsx" and "xl/workbook.xml" not in names):
                return {"state": "unknown", "reason": "unexpected_file_format"}
    except BadZipFile:
        return {"state": "unknown", "reason": "incomplete_archive"}
    with target.open("rb") as handle:
        checksum = file_digest(handle, "sha256").hexdigest()
    return {"state": "saved", "path": str(target), "sha256": checksum, "bytes": target.stat().st_size}


if __name__ == "__main__":
    try:
        print(json.dumps(capture(json.loads(sys.argv[1]))))
    except (ValueError, TypeError, OSError, KeyError):
        print(json.dumps({"state": "unknown", "reason": "invalid_download_request_or_local_error"}))
