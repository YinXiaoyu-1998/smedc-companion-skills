"""Verify the official launcher's local range/ZIP metadata and bytes; no downloads or credentials."""

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re

from workflow import digest, load, regular


def unsigned(value):
    if isinstance(value, bool) or not re.fullmatch(r"0|[1-9][0-9]*", str(value)):
        raise ValueError("Invalid transfer count")
    return int(value)


def proof(value):
    response = value["response"]
    intent = value["intent"]
    identity = intent["identity"]
    if identity["kind"] != "download":
        raise ValueError("Download intent required")
    version = value["launcherVersion"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version) or tuple(
        map(int, version.split("."))
    ) < (0, 17, 0):
        raise ValueError("Incompatible verified launcher")
    root = Path(response["localDirectory"])
    if root.is_symlink() or root.parent.is_symlink():
        raise ValueError("Symlink extract refused")
    root = root.resolve()
    if root.parent.name != "smedc-partition-extracts" or not root.name.startswith(
        "extract-"
    ):
        raise ValueError("Expected official launcher extract")
    manifest = regular(root / "manifest.json")
    metadata = load(manifest)
    for key in [
        "dataset",
        "enterpriseName",
        "startDate",
        "endDate",
        "partitionCount",
        "totalRowCount",
    ]:
        if str(metadata[key]) != str(response[key]):
            raise ValueError("Launcher response/manifest differs")
    if (
        metadata["dataset"] != identity["dataset"]
        or metadata["startDate"] != identity["window"]["startDate"]
        or metadata["endDate"] != identity["window"]["endDate"]
    ):
        raise ValueError("Downloaded scope differs from frozen intent")
    files = metadata["files"]
    if (
        not isinstance(files, list)
        or len(files) > 100000
        or len(files) != unsigned(metadata["partitionCount"])
    ):
        raise ValueError("Invalid partition count")
    names = [item["fileName"] for item in files]
    if len(set(names)) != len(names) or set(names) != set(response["files"]):
        raise ValueError("Launcher file inventory differs")
    byte_count = 0
    row_count = 0
    verified = []
    for item in files:
        name = item["fileName"]
        if (
            not isinstance(name, str)
            or Path(name).name != name
            or name in {".", "..", "manifest.json"}
        ):
            raise ValueError("Unsafe extract filename")
        if (
            item["storeName"] not in identity["storeNames"]
            or not identity["window"]["startDate"]
            <= item["businessDate"]
            <= identity["window"]["endDate"]
        ):
            raise ValueError("Partition outside exact frozen store/day scope")
        file = regular(root / name)
        before = file.stat()
        with file.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        after = file.stat()
        if (
            before.st_size != unsigned(item["byteSize"])
            or checksum != item["checksumSha256"]
            or (before.st_ino, before.st_mtime_ns, before.st_size)
            != (after.st_ino, after.st_mtime_ns, after.st_size)
        ):
            raise ValueError("Downloaded byte size/checksum mismatch")
        if metadata["dataset"] == "in_store_orders" and item.get("orderScope") not in {
            "settled_only",
            "all_statuses",
            "legacy_unknown",
        }:
            raise ValueError("Missing orderScope metadata")
        byte_count += before.st_size
        row_count += unsigned(item["rowCount"])
        verified.append(
            {
                "fileName": name,
                "checksumSha256": checksum,
                "byteSize": str(before.st_size),
                "rowCount": str(unsigned(item["rowCount"])),
                "storeName": item["storeName"],
                "businessDate": item["businessDate"],
                "orderScope": item.get("orderScope"),
            }
        )
    if row_count != unsigned(metadata["totalRowCount"]):
        raise ValueError("Downloaded row total differs")
    manifest_hash = hashlib.sha256(manifest.read_bytes()).hexdigest()
    if identity.get("manifestHash", manifest_hash) != manifest_hash:
        raise ValueError("Prepared manifest differs from intent")
    result_hash = digest(verified)
    verified_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    transfer = {
        "identityHash": value["identityHash"],
        "manifestHash": manifest_hash,
        "resultHash": result_hash,
        "launcherVersion": version,
        "verifiedAt": verified_at,
        "partitionCount": len(files),
        "fileCount": len(files),
        "totalByteSize": str(byte_count),
        "totalRowCount": str(row_count),
    }
    if value.get("requestId"):
        transfer["requestId"] = value["requestId"]
    return {
        "actionId": intent["actionId"],
        "state": "confirmed",
        "evidence": "launcher_transfer",
        "receiptId": value.get("requestId", intent["actionId"]),
        "resultHash": result_hash,
        "verifiedAt": verified_at,
        "launcherTransfer": transfer,
    }
