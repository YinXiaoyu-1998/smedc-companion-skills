"""Closed, versioned review semantics and explicit legacy exception conversion."""

from __future__ import annotations
from copy import deepcopy
from pathlib import Path
from workflow import load

PACKAGE = Path(__file__).resolve().parents[1]
PRESET = {"id": "verified-review-operations", "version": 1}
POLICY_FIELDS = {
    "unrecognizedReviewGraphicsPolicy",
    "sourceAuthorityPolicy",
    "issueTrackingPolicy",
    "errorRecordingPolicy",
}
PATH_FIELDS = {
    "reference": {"error-recording.md", "review-execution-policy.md"},
    "logger": {"audit_log.py"},
    "toolWrapper": {"audited_tool.js", "audited-tool.js"},
}


def component(name, value):
    expected = deepcopy(
        load(PACKAGE / "review-execution-policy.json")["legacyPolicies"][name]
    )
    actual = deepcopy(value)
    for key, allowed in PATH_FIELDS.items():
        if key in expected:
            if (
                not isinstance(actual.get(key), str)
                or Path(actual[key]).name not in allowed
            ):
                raise ValueError(
                    "source_conflict: unknown review policy runtime reference"
                )
            actual.pop(key)
            expected.pop(key)
    if actual != expected:
        raise ValueError("source_conflict: unsupported review execution policy")
    return dict(PRESET)


def ignored_identities(records, integration, account_ref):
    if not isinstance(records, list) or len(records) > 2000 or not account_ref:
        raise ValueError(
            "Explicit source account and bounded ignored identities required"
        )
    output = []
    for record in records:
        if set(record) - {"poiId", "source", "feedbackId", "reason"}:
            raise ValueError("Unknown ignored identity field")
        channel = {"美团评价": "meituan", "点评评价": "dianping"}.get(
            record.get("source")
        )
        matches = [
            m["source"]
            for m in integration["storeMappings"]
            if m["source"]["product"] == "meituan_reviews"
            and m["source"]["accountRef"] == account_ref
            and m["source"]["channel"] == channel
            and m["source"].get("sourceStoreId") == record.get("poiId")
        ]
        if (
            len(matches) != 1
            or not isinstance(record.get("feedbackId"), str)
            or not record["feedbackId"]
        ):
            raise ValueError(
                "source_conflict: ignored review source not uniquely mapped"
            )
        output.append(
            {
                "source": matches[0],
                "feedbackId": record["feedbackId"],
                "reason": record.get(
                    "reason",
                    "Retained explicit legacy source exclusion; see migration evidence",
                ),
                "purpose": "exclude_source_record",
            }
        )
    return output


def task(value):
    snapshot = value["snapshot"]
    config = snapshot["configuration"]
    if (
        config["type"] != "meituan-review-operations"
        or config.get("executionPolicy", PRESET) != PRESET
    ):
        raise ValueError("Unsupported frozen review execution policy")
    mappings = [
        m
        for m in snapshot["integration"]["storeMappings"]
        if m["source"]["product"] == "meituan_reviews"
        and m["source"]["channel"] in config["channels"]
        and m["storeName"] in config["storeNames"]
    ]
    for store in config["storeNames"]:
        for channel in config["channels"]:
            if not any(
                m["storeName"] == store and m["source"]["channel"] == channel
                for m in mappings
            ):
                raise ValueError("Selected review store/channel has no source mapping")
    grouped = {}
    for mapping in mappings:
        # The legacy display view has no channel; the scoped list below keeps every identity.
        grouped.setdefault(mapping["storeName"], {})[
            mapping["source"]["sourceStoreName"]
        ] = None
    policies = deepcopy(
        load(PACKAGE / "review-execution-policy.json")["legacyPolicies"]
    )
    policies["issueTrackingPolicy"]["reference"] = str(
        PACKAGE / "references" / "review-execution-policy.md"
    )
    policies["errorRecordingPolicy"].update(
        reference=str(PACKAGE / "references" / "review-execution-policy.md"),
        logger=str(PACKAGE / "scripts" / "audit_log.py"),
        toolWrapper=str(PACKAGE / "scripts" / "audited-tool.js"),
    )
    return {
        "enterpriseName": value["enterpriseName"],
        "mappings": [
            {
                "targetStoreName": name,
                "sourceStores": [{"storeName": source} for source in names],
            }
            for name, names in grouped.items()
        ],
        "sourceIdentityMappings": mappings,
        "replyWhitelist": config["publication"]["storeNames"] or config["storeNames"],
        "ignoredRecords": [],
        "ignoredReviewIdentities": config.get("ignoredReviewIdentities", []),
        "executionPolicy": PRESET,
        **policies,
    }
