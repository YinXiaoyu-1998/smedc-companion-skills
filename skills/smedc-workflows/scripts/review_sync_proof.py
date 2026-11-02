"""Full local observed-field comparison of official SMEDC readback; emits metadata only."""

from datetime import datetime, timezone, timedelta
import json

from workflow import digest, load

IDENTITY = (
    "enterpriseName",
    "source",
    "storeName",
    "feedbackId",
    "reviewerName",
    "reviewedAt",
)
FIELDS = set(IDENTITY) | {"content", "merchantReply", "replyStatus", "scores"}
TZ = timezone(timedelta(hours=8))


def normalized(value):
    if isinstance(value, dict):
        return {key: normalized(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalized(item) for item in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def row_values(row, fields):
    result = {key: normalized(row[key]) for key in fields if key in row}
    if "reviewedAt" in result:
        observed = datetime.fromisoformat(result["reviewedAt"].replace("Z", "+00:00"))
        if observed.tzinfo is None:
            raise ValueError("Review readback time requires timezone")
        result["reviewedAt"] = observed.astimezone(TZ).isoformat(
            timespec="seconds" if not observed.microsecond else "microseconds"
        )
    return result


def unwrap(raw):
    if isinstance(raw, dict) and "result" in raw:
        raw = raw["result"]
    if (
        raw.get("isError")
        or raw.get("promiseRejected")
        or raw.get("ok") is False
        or raw.get("error")
    ):
        raise ValueError("Unsuccessful official review readback")
    if "structuredContent" in raw:
        raw = raw["structuredContent"]
    elif "content" in raw:
        candidates = []
        for item in raw["content"]:
            if item.get("type") == "text":
                try:
                    candidates.append(json.loads(item["text"]))
                except json.JSONDecodeError:
                    pass
        if len(candidates) != 1:
            raise ValueError("Ambiguous official review readback envelope")
        raw = candidates[0]
    return raw.get("data", raw)


def read_pages(paths):
    rows = []
    if not paths:
        raise ValueError("Complete review readback pages required")
    for index, path in enumerate(paths):
        page = unwrap(load(path))
        if not isinstance(page.get("rows"), list) or not isinstance(
            page.get("page"), dict
        ):
            raise ValueError("Invalid official review readback page")
        cursor = page["page"].get("nextCursor")
        if (index == len(paths) - 1) != (cursor is None):
            raise ValueError("Review readback pagination incomplete")
        rows.extend(page["rows"])
    ids = [row["id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate persisted ID in review readback")
    return rows


def source_key(source):
    return (
        source["product"],
        source["accountRef"],
        source["channel"],
        (
            ("id", source["sourceStoreId"])
            if source.get("sourceStoreId")
            else ("name", source["sourceStoreName"])
        ),
    )


def intent(value):
    entries = load(value["planPath"])["entries"]
    if not 1 <= len(entries) <= 1000:
        raise ValueError("Bounded review sync plan required")
    payloads = []
    for entry in entries:
        if source_key(entry["sourceIdentity"]) != source_key(value["source"]):
            raise ValueError("Review sync source namespace differs")
        payload = entry["payload"]
        if set(payload) - FIELDS or not set(IDENTITY) <= set(payload):
            raise ValueError("Observed full review identity required")
        row = row_values(payload, payload)
        if (
            payload["storeName"] not in value["storeNames"]
            or not value["window"]["startDate"]
            <= row["reviewedAt"][:10]
            <= value["window"]["endDate"]
        ):
            raise ValueError("Review sync outside frozen scope")
        payloads.append(row)
    return {
        "actionId": value["actionId"],
        "identity": {
            "kind": "review_sync",
            "source": value["source"],
            "storeNames": value["storeNames"],
            "window": value["window"],
            "observedFactsHash": digest(payloads),
        },
    }


def proof(value):
    intent = value["intent"]
    scope = intent["identity"]
    entries = load(value["planPath"])["entries"]
    if (
        scope["kind"] != "review_sync"
        or not 1 <= len(entries) <= 1000
        or len(value["readbackPaths"]) != len(entries)
    ):
        raise ValueError("Bounded review_sync plan/readbacks required")
    expected = []
    matched = []
    ids = []
    for entry, paths in zip(entries, value["readbackPaths"]):
        payload = entry["payload"]
        if source_key(entry["sourceIdentity"]) != source_key(scope["source"]):
            raise ValueError("Review readback source namespace differs")
        if set(payload) - FIELDS or not set(IDENTITY) <= set(payload):
            raise ValueError("Observed full review identity required")
        expected_row = row_values(payload, payload)
        source_channel = {"meituan": "美团评价", "dianping": "点评评价"}.get(
            scope["source"]["channel"]
        )
        if (
            payload["source"] != source_channel
            or payload["storeName"] not in scope["storeNames"]
            or not scope["window"]["startDate"]
            <= expected_row["reviewedAt"][:10]
            <= scope["window"]["endDate"]
        ):
            raise ValueError("Review readback outside frozen source/store/date scope")
        rows = read_pages([paths] if isinstance(paths, str) else paths)
        candidates = [
            row
            for row in rows
            if row_values(row, IDENTITY) == {key: expected_row[key] for key in IDENTITY}
        ]
        if len(candidates) != 1:
            raise ValueError("Full review readback identity is not unique")
        actual = candidates[0]
        if entry.get("existingId") and actual["id"] != entry["existingId"]:
            raise ValueError("Existing review readback ID changed")
        actual_row = row_values(actual, payload)
        if actual_row != expected_row:
            raise ValueError("Observed review readback fields differ")
        for independent in entry.get("independentRows", []):
            preserved = [row for row in rows if row["id"] == independent["id"]]
            if len(preserved) != 1 or row_values(
                preserved[0], independent
            ) != row_values(independent, independent):
                raise ValueError(
                    "Independent review readback row changed or disappeared"
                )
        expected.append(expected_row)
        matched.append(actual_row)
        ids.append(actual["id"])
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate matched review IDs")
    if digest(expected) != scope["observedFactsHash"]:
        raise ValueError("Observed facts hash differs from sync intent")
    result_hash = digest(matched)
    observed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "actionId": intent["actionId"],
        "state": "confirmed",
        "evidence": "smedc_readback",
        "receiptId": intent["actionId"],
        "resultHash": result_hash,
        "verifiedAt": observed_at,
        "smedcReadback": {
            "identityHash": value["identityHash"],
            "observedFactsHash": scope["observedFactsHash"],
            "resultHash": result_hash,
            "recordIds": ids,
            "observedAt": observed_at,
            "outcome": "matched",
            "reviewCount": len(entries),
            "matchedCount": len(ids),
        },
    }
