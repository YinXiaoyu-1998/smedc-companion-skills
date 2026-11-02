"""Explicit-source legacy migration. Never scans customer directories or executes policy text."""

from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import tomllib

from workflow import digest, encoded, regular

KINDS = {"task", "settings", "policy", "groups", "receipts", "control", "evidence"}
SECRET_KEYS = re.compile(
    r"(^|[_-])(password|token|cookie|secret|credential|authorization_header|api_key)($|[_-])",
    re.I,
)
RECEIPT_KEYS = {
    "actionId",
    "state",
    "evidence",
    "receiptId",
    "jobId",
    "resultHash",
    "reason",
    "verifiedAt",
    "providerReadback",
    "launcherTransfer",
    "smedcReadback",
}
INTENT_KEYS = {"actionId", "identity", "artifactHash", "correlationMarker"}
UNRESOLVED_CODES = {
    "source_conflict",
    "missing_receipt",
    "unknown_action",
    "missing_local_evidence",
}


def pointer(value, path):
    if path == "":
        return value
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError("Expected JSON pointer")
    for part in path[1:].split("/"):
        key = part.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def no_secrets(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if SECRET_KEYS.search(key):
                raise ValueError("Credential-like field forbidden in migration payload")
            no_secrets(item)
    elif isinstance(value, list):
        for item in value:
            no_secrets(item)
    elif isinstance(value, str) and re.search(
        r"https?://\S+[?&](?:token|signature|sig|X-Amz-)", value, re.I
    ):
        raise ValueError("Signed link forbidden in migration payload")


def transformed(value, transform, source=None, target=None):
    if transform == "identity":
        return value
    if transform == "named_groups":
        groups = value.get("groups")
        if value.get("schemaVersion") != 1 or not isinstance(groups, dict):
            raise ValueError("Invalid legacy named groups")
        return [{"name": name, "storeNames": stores} for name, stores in groups.items()]
    if transform.startswith("review_policy:"):
        from review_policy import component, POLICY_FIELDS

        name = transform.split(":", 1)[1]
        if name not in POLICY_FIELDS:
            raise ValueError("Unknown policy component")
        return component(name, value)
    if transform == "ignored_review_identities":
        from review_policy import ignored_identities

        return ignored_identities(
            value, target["integration"], source.get("sourceAccountRef")
        )
    if transform == "recipient_list":
        return [value] if isinstance(value, str) else value
    raise ValueError("Unsupported migration transform")


def leaf_paths(value, prefix=""):
    if isinstance(value, dict) and value:
        return [
            path
            for key, item in value.items()
            for path in leaf_paths(
                item, prefix + "/" + str(key).replace("~", "~0").replace("/", "~1")
            )
        ]
    if isinstance(value, list) and value:
        return [
            path
            for index, item in enumerate(value)
            for path in leaf_paths(item, prefix + "/" + str(index))
        ]
    return [prefix]


def attest_fields(source, data, target, provenance):
    """Account for every machine field; text decisions require exact excerpts and review."""
    dispositions = source.get("fields", [])
    covered = set()
    for field in dispositions:
        path = field["source"]
        original = pointer(data, path)
        destination = field["destination"]
        if destination not in {"central", "local_evidence", "obsolete", "needs_review"}:
            raise ValueError("Invalid field disposition")
        if destination == "needs_review":
            raise ValueError("source_conflict: unresolved source field")
        if destination == "central":
            selected = transformed(
                original, field.get("transform", "identity"), source, target
            )
            if pointer(target, field["target"]) != selected:
                raise ValueError(
                    "source_conflict: settings differ from migration target"
                )
        covered.update(leaf_paths(original, path))
        provenance.append(
            {
                "sourceId": source["id"],
                "source": path,
                "destination": destination,
                **({"target": field["target"]} if destination == "central" else {}),
            }
        )
    if set(leaf_paths(data)) - covered:
        raise ValueError("source_conflict: account for every source setting explicitly")


def policy_decisions(source, text, target, provenance):
    decisions = source.get("decisions", [])
    covered = []
    for item in decisions:
        excerpt = item["excerpt"]
        if not excerpt.strip() or excerpt not in text:
            raise ValueError("Policy excerpt not found in exact source")
        destination = item["destination"]
        if destination == "needs_review":
            raise ValueError("source_conflict: unresolved policy rule")
        if destination not in {"central", "local_evidence", "obsolete"}:
            raise ValueError("Invalid policy decision")
        if (
            destination == "central"
            and pointer(target, item["target"]) != item["value"]
        ):
            raise ValueError("source_conflict: policy differs from migration target")
        covered.append(excerpt)
        provenance.append(
            {
                "sourceId": source["id"],
                "excerptHash": hashlib.sha256(excerpt.encode()).hexdigest(),
                "destination": destination,
                **({"target": item["target"]} if destination == "central" else {}),
            }
        )
    meaningful = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if any(not any(line in excerpt for excerpt in covered) for line in meaningful):
        raise ValueError(
            "source_conflict: policy rules require complete explicit review"
        )


def template(value, raw, target, depth=0):
    if depth > 30:
        raise ValueError("Migration template too deep")
    if isinstance(value, dict):
        if set(value) == {"$pointer"}:
            return deepcopy(pointer(raw, value["$pointer"]))
        if set(value) == {"$target"}:
            return deepcopy(pointer(target, value["$target"]))
        if set(value) == {"$hash"}:
            return digest(template(value["$hash"], raw, target, depth + 1))
        if set(value) == {"$actionId"}:
            return (
                "legacy_"
                + digest(template(value["$actionId"], raw, target, depth + 1))[:48]
            )
        if set(value) == {"$map"}:
            rule = value["$map"]
            selected = str(pointer(raw, rule["pointer"]))
            if selected not in rule["values"]:
                raise ValueError("source_conflict: unsupported legacy status")
            return deepcopy(rule["values"][selected])
        return {
            key: template(item, raw, target, depth + 1) for key, item in value.items()
        }
    if isinstance(value, list):
        return [template(item, raw, target, depth + 1) for item in value]
    return value


def bounded_identity(identity):
    common = {"kind", "storeNames", "window"}
    keys = {
        "upload": common | {"dataset", "orderScope", "sourceHash", "metadataHash"},
        "download": common | {"dataset", "manifestHash"},
        "review_sync": common | {"source", "observedFactsHash"},
        "review_publish": {"kind", "storeName", "source", "feedbackId", "purpose"},
        "email": common
        | {"purpose", "recipients", "sender", "deliveryVersion", "reviewIdentities"},
    }
    kind = identity.get("kind")
    if kind not in keys or set(identity) - keys[kind]:
        raise ValueError("Unexpected fields in central action identity")
    if "window" in identity and set(identity["window"]) != {"startDate", "endDate"}:
        raise ValueError("Invalid action window")
    if "source" in identity:
        bounded_source(identity["source"])
    for review in identity.get("reviewIdentities", []):
        if set(review) != {"source", "feedbackId", "recipient"}:
            raise ValueError("Unexpected review notification fields")
        bounded_source(review["source"])


def bounded_source(source):
    if set(source) - {
        "product",
        "channel",
        "accountRef",
        "sourceStoreId",
        "sourceStoreName",
    }:
        raise ValueError("Unexpected source identity fields")
    if source.get("product") not in {"meituan_erp", "meituan_reviews"} or source.get(
        "channel"
    ) not in {"erp", "meituan", "dianping"}:
        raise ValueError("Invalid source namespace")


def compact_record(record, source_id, index):
    """Only normalized known identity/receipt fields may cross into central history."""
    intent = record.get("intent")
    receipt = record.get("receipt")
    if not record.get("legacyKeyHash") and not record.get("legacyKey"):
        raise ValueError(
            "Persistent legacy key required; file/index is not a deduplication identity"
        )
    legacy_key = record.get("legacyKeyHash") or digest(record["legacyKey"])
    if not re.fullmatch("[0-9a-f]{64}", legacy_key):
        raise ValueError("Invalid legacy key hash")
    if not isinstance(intent, dict) or not isinstance(receipt, dict):
        return None, {
            "code": "missing_receipt",
            "sourceRef": source_id,
            "evidenceHash": digest(record),
        }
    intent = {k: deepcopy(v) for k, v in intent.items() if k in INTENT_KEYS}
    receipt = {k: deepcopy(v) for k, v in receipt.items() if k in RECEIPT_KEYS}
    if not intent.get("actionId") or receipt.get("actionId") != intent["actionId"]:
        raise ValueError("source_conflict: mismatched receipt identity")
    bounded_identity(intent["identity"])
    no_secrets(intent)
    no_secrets(receipt)
    if receipt.get("state") == "confirmed":
        if receipt.get("evidence") not in {
            "service_status",
            "provider_readback",
            "manual_resolution",
            "launcher_transfer",
            "smedc_readback",
        } or not (receipt.get("receiptId") or receipt.get("jobId")):
            return None, {
                "code": "missing_receipt",
                "sourceRef": source_id,
                "evidenceHash": digest(record),
            }
        return {"legacyKeyHash": legacy_key, "intent": intent, "receipt": receipt}, None
    if receipt.get("state") in {"unknown", "intent"}:
        receipt["state"] = "unknown"
        receipt["evidence"] = "transport_unknown"
        return None, {
            "code": "unknown_action",
            "sourceRef": source_id,
            "evidenceHash": digest(record),
            "intent": intent,
            "receipt": receipt,
        }
    if (
        receipt.get("state") == "failed"
        and receipt.get("evidence") == "request_rejected"
    ):
        # Keep a local provenance record; definite failures are not completed dedup claims.
        return None, None
    return None, {
        "code": "missing_receipt",
        "sourceRef": source_id,
        "evidenceHash": digest(record),
    }


def validate_recovery(item):
    allowed = {
        "itemId",
        "kind",
        "disposition",
        "stage",
        "scope",
        "evidenceRef",
        "evidenceHash",
        "resolutionReason",
    }
    if set(item) - allowed or not re.fullmatch("[A-Za-z0-9_-]{1,64}", item["itemId"]):
        raise ValueError("Invalid bounded recovery item")
    if item["kind"] not in {"business", "evidence"} or item["disposition"] not in {
        "open",
        "waived",
        "resolved",
    }:
        raise ValueError("Invalid recovery disposition")
    if item["stage"] not in {
        "preparing",
        "collecting",
        "validating",
        "processing",
        "delivering",
        "verifying",
        "cleaning",
        "finished",
    }:
        raise ValueError("Invalid recovery stage")
    if item["disposition"] != "open" and not item.get("resolutionReason", "").strip():
        raise ValueError("Recovery resolution reason required")
    scope = item["scope"]
    kind = scope["kind"]
    fields = {
        "dataset": {"kind", "dataset", "storeNames", "window"},
        "reviews": {"kind", "source", "storeName", "window", "feedbackId"},
        "report": {"kind", "storeNames", "window"},
        "unknown_scope": {"kind", "reason"},
    }
    if kind not in fields or set(scope) - fields[kind]:
        raise ValueError("Unsupported portable recovery scope")
    if kind == "unknown_scope" and scope.get("reason") not in {
        "scope_not_preserved",
        "missing_local_evidence",
        "ambiguous_source_identity",
    }:
        raise ValueError("Unknown recovery scope reason")
    if "window" in scope and set(scope["window"]) != {"startDate", "endDate"}:
        raise ValueError("Invalid recovery window")
    if "evidenceRef" in item and not re.fullmatch(
        "[A-Za-z0-9_-]{1,64}", item["evidenceRef"]
    ):
        raise ValueError("Recovery evidence reference must be an opaque ID")
    if "evidenceHash" in item and not re.fullmatch(
        "[a-f0-9]{64}", item["evidenceHash"]
    ):
        raise ValueError("Invalid recovery evidence hash")
    if len(item.get("resolutionReason", "")) > 2000:
        raise ValueError("Recovery reason too long")
    if kind == "reviews":
        bounded_source(scope["source"])
    no_secrets(item)


def build(value):
    target = {
        "integration": deepcopy(value["integration"]),
        "targetVersion": value["targetVersion"],
        "workflows": deepcopy(value["workflows"]),
    }
    sources = value["sources"]
    if not 1 <= len(target["workflows"]) <= 3 or not sources:
        raise ValueError("Migration needs selected workflows and explicit sources")
    if any(not re.fullmatch("[A-Za-z0-9_-]{1,64}", s["id"]) for s in sources):
        raise ValueError("Invalid source identity")
    if len({s["id"] for s in sources}) != len(sources):
        raise ValueError("Duplicate source identity")
    by_id = {w["workflowId"]: w for w in target["workflows"]}
    if len(by_id) != len(target["workflows"]):
        raise ValueError("Duplicate target workflow")
    initial_recovery = []
    for workflow in by_id.values():
        for item in workflow.pop("recoveryItems", []):
            initial_recovery.append((workflow["workflowId"], "recoveryItems", item))
        workflow["completedActions"] = []
        workflow["unresolved"] = []
    hashes = []
    local = []
    provenance = []
    all_records = initial_recovery
    tasks = {}
    for source in sources:
        kind = source["kind"]
        if kind not in KINDS:
            raise ValueError("Unrecognized migration source kind")
        path = regular(source["path"])
        content = path.read_bytes()
        if len(content) > 32 * 1024 * 1024:
            raise ValueError("Source too large; split explicitly without truncating")
        sha = hashlib.sha256(content).hexdigest()
        if source.get("expectedSha256", sha) != sha:
            raise ValueError("Source changed after selection")
        hashes.append({"id": source["id"], "kind": kind, "sha256": sha})
        local.append(
            {"sourceId": source["id"], "path": str(path), "sha256": sha, "kind": kind}
        )
        workflow = by_id.get(source.get("workflowId"))
        if kind == "task":
            if not workflow:
                raise ValueError("Task needs stable target workflow identity")
            task = tomllib.loads(content.decode())
            if (
                task.get("kind") != "cron"
                or not task.get("rrule")
                or not task.get("model")
                or not task.get("reasoning_effort")
            ):
                raise ValueError("Unsupported legacy host definition")
            if not source.get("observedAt"):
                raise ValueError(
                    "Fixed source observation time required for repeatable migration"
                )
            datetime.fromisoformat(source["observedAt"].replace("Z", "+00:00"))
            policy_decisions(
                {**source, "decisions": source.get("promptDecisions", [])},
                task.get("prompt", ""),
                target,
                provenance,
            )
            tasks[source["id"]] = task
            workflow["hostSnapshot"] = {
                "host": "codex",
                "platform": "macos",
                "taskId": task["id"],
                "projectRef": "legacy-reinstall-required",
                "cron": task["rrule"],
                "timezone": "Asia/Shanghai",
                "model": task["model"],
                "reasoningEffort": task["reasoning_effort"],
                "state": "enabled" if task.get("status") == "ACTIVE" else "paused",
                "verifiedAt": source["observedAt"],
            }
            if source.get("activeRun"):
                raise ValueError(
                    "Active legacy run must be reconciled and released before migration"
                )
            # Explicit referenced config paths must all be included, no directory discovery.
            for reference in source.get("references", []):
                if reference not in {s["id"] for s in sources}:
                    raise ValueError("Missing referenced policy/config/receipt source")
            provenance.append(
                {
                    "sourceId": source["id"],
                    "source": "/rrule",
                    "destination": "host_snapshot",
                }
            )
        elif kind in {"settings", "groups"}:
            data = json.loads(content)
            attest_fields(source, data, target, provenance)
        elif kind == "policy":
            policy_decisions(source, content.decode(), target, provenance)
        elif kind == "receipts":
            if not workflow:
                raise ValueError("Receipt needs stable workflow identity")
            data = json.loads(content)
            records = pointer(data, source.get("recordsPointer", ""))
            if not isinstance(records, list):
                raise ValueError("Receipt pointer must select a complete list")
            for index, raw in enumerate(records):
                if source.get("recordTemplate"):
                    raw = template(source["recordTemplate"], raw, target)
                if source.get("recordFields"):
                    # Map a documented legacy schema into normalized fields; never infer success from filename.
                    mapped = {
                        key: pointer(raw, path)
                        for key, path in source["recordFields"].items()
                    }
                    raw = mapped
                complete, unresolved = compact_record(raw, source["id"], index)
                if complete:
                    all_records.append(
                        (workflow["workflowId"], "completedActions", complete)
                    )
                if unresolved:
                    all_records.append(
                        (workflow["workflowId"], "unresolved", unresolved)
                    )
        elif kind == "control":
            if not workflow:
                raise ValueError("Control needs stable workflow identity")
            data = json.loads(content)
            if data.get("active") is True or data.get("lockHeld") is True:
                raise ValueError("Active source lock cannot be stolen")
            selected_lists = {
                entry["pointer"] for entry in source.get("recoveryLists", [])
            }
            for legacy_key in [
                "items",
                "evidenceItems",
                "resolvedItems",
                "resolvedReviewIssues",
                "waivedItems",
            ]:
                if data.get(legacy_key) and "/" + legacy_key not in selected_lists:
                    raise ValueError(
                        "source_conflict: legacy recovery list not accounted for"
                    )
            for selected in source.get("recoveryLists", []):
                records = pointer(data, selected["pointer"])
                if not isinstance(records, list):
                    raise ValueError("Recovery pointer must select complete list")
                for raw in records:
                    item = template(selected["template"], raw, target)
                    validate_recovery(item)
                    all_records.append((workflow["workflowId"], "recoveryItems", item))
            for item in data.get("recoveryItems", []):
                validate_recovery(item)
                all_records.append((workflow["workflowId"], "recoveryItems", item))
            for item in data.get("unresolved", []):
                if item.get("code") not in UNRESOLVED_CODES:
                    raise ValueError(
                        "Unsupported unresolved control item; review required"
                    )
                normalized = {
                    key: item[key]
                    for key in ["code", "intent", "receipt"]
                    if key in item
                }
                normalized.update(sourceRef=source["id"], evidenceHash=digest(item))
                if "intent" in normalized:
                    bounded_identity(normalized["intent"]["identity"])
                all_records.append((workflow["workflowId"], "unresolved", normalized))
            # Other business/evidence/waived items remain compact local evidence, never silently resolved.
            local[-1]["unfinished"] = data.get("status") not in {
                "succeeded",
                "confirmed",
                "finished",
            }
        else:
            provenance.append(
                {
                    "sourceId": source["id"],
                    "source": "",
                    "destination": "local_evidence",
                }
            )
    for workflow in by_id.values():
        if workflow.pop("taskSource", None) not in tasks:
            raise ValueError("Every workflow needs its actual task definition")
    no_secrets(target)
    # The static manifest is independently bounded; pages carry history without a total-history cap.
    for _, key, item in all_records:
        if key == "recoveryItems":
            validate_recovery(item)
    declarations = [
        {k: v for k, v in source.items() if k not in {"path", "expectedSha256"}}
        for source in sources
    ]
    target["sourceSnapshotHash"] = digest(
        {
            "sourceFiles": hashes,
            "interpretation": target,
            "sourceDeclarations": declarations,
            "recordInterpretationHash": digest(all_records),
            "schemaVersion": 1,
        }
    )
    pages = []
    current = {}
    size = 0

    def flush():
        nonlocal current, size
        chunk = [{"workflowId": wid, **parts} for wid, parts in current.items()]
        pages.append(chunk)
        current = {}
        size = 0

    seen = {}
    for wid, key, record in all_records:
        claim = (
            wid,
            key,
            record.get("legacyKeyHash") or record.get("itemId") or digest(record),
        )
        h = digest(record)
        if claim in seen:
            if seen[claim] != h:
                raise ValueError(
                    "source_conflict: duplicate legacy key with conflicting receipt"
                )
            continue
        seen[claim] = h
        candidate = deepcopy(current)
        candidate.setdefault(
            wid, {"completedActions": [], "unresolved": []}
        ).setdefault(key, []).append(record)
        if current and (
            size >= 100 or len(encoded(list(candidate.values()))) > 250 * 1024
        ):
            flush()
            candidate = {wid: {"completedActions": [], "unresolved": []}}
            candidate[wid].setdefault(key, []).append(record)
        if len(encoded(list(candidate.values()))) > 250 * 1024:
            raise ValueError("One receipt exceeds payload limit")
        current = candidate
        size += 1
    if current or not pages:
        flush()
    for part in pages[0]:
        by_id[part["workflowId"]]["completedActions"] = part["completedActions"]
        by_id[part["workflowId"]]["unresolved"] = part["unresolved"]
        if "recoveryItems" in part:
            by_id[part["workflowId"]]["recoveryItems"] = part["recoveryItems"]
    if len(encoded(target)) > 1024 * 1024:
        raise ValueError("Static migration configuration exceeds 1MiB")
    pages[0] = [
        {
            "workflowId": w["workflowId"],
            "completedActions": w["completedActions"],
            "unresolved": w["unresolved"],
            **({"recoveryItems": w["recoveryItems"]} if "recoveryItems" in w else {}),
        }
        for w in target["workflows"]
    ]
    chain = "0" * 64
    output_pages = []
    count = 0
    for sequence, chunk in enumerate(pages):
        records = sum(
            len(p["completedActions"])
            + len(p["unresolved"])
            + len(p.get("recoveryItems", []))
            for p in chunk
        )
        chunk_hash = digest(chunk)
        chain = digest([chain, sequence, chunk_hash, records])
        count += records
        if sequence:
            output_pages.append(
                {"sequence": sequence, "chunk": chunk, "chunkHash": chunk_hash}
            )
    return {
        "schemaVersion": 1,
        "manifest": target,
        "pages": output_pages,
        "chunkCount": len(pages),
        "recordCount": count,
        "chunksDigest": chain,
        "provenance": provenance,
        "localEvidence": local,
        "sourceSnapshots": hashes,
        "stage": "preview",
        "hostSwitchAllowed": False,
    }
