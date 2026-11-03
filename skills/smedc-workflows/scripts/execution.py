"""Derive remaining work from a frozen run and durable, scoped evidence.

This is a local work queue, not a scheduler, authorization decision or provider receipt.
"""
from __future__ import annotations

import hashlib
from workflow import digest, manifest, regular


def plan(value):
    run = value["run"]
    snapshot = run["snapshot"]
    kind = snapshot["workflowType"]
    config = snapshot["configuration"]
    if config["type"] != kind or not config["storeNames"]:
        raise ValueError("Frozen configuration/type required")
    run_id = run.get("runId", run.get("id"))
    if not run_id:
        raise ValueError("Central run ID required")
    binding = digest({"runId": run_id, "snapshot": snapshot})
    progress = value.get("progress", {})
    if progress and (progress.get("runId") != run_id or progress.get("bindingHash") != binding):
        raise ValueError("Progress belongs to another frozen run")
    tasks = []

    def add(task_id, stage, scope, dependencies=(), applicable=True):
        tasks.append({"id": task_id, "stage": stage, "scope": scope,
                      "scopeHash": digest(scope), "dependsOn": list(dependencies),
                      "applicable": applicable})

    base = {"storeNames": config["storeNames"], "window": snapshot["window"]}
    stages = manifest()["workflows"][kind]["stages"]
    if kind == "meituan-daily-ingestion":
        for dataset in config["datasets"]:
            previous = []
            for stage in stages:
                task_id = dataset + "/" + stage
                add(task_id, stage, {**base, "dataset": dataset}, previous)
                previous = [task_id]
    elif kind == "meituan-review-operations":
        from review_policy import task

        source_task = task({"snapshot": snapshot, "enterpriseName": "workflow"})
        collections = []
        for mapping in source_task["sourceIdentityMappings"]:
            scope = {"window": snapshot["window"], **mapping}
            task_id = "collect/" + digest(scope)[:24]
            add(task_id, "collect", scope)
            collections.append(task_id)
        previous = collections
        for stage in stages[1:]:
            dependencies = previous
            applicable = True
            if stage == "notify_new_drafts":
                applicable = config.get("draftNotification", {}).get("enabled", False)
            elif stage == "publish_authorized":
                # An unavailable mail provider does not block authorized publication.
                dependencies = ["workbook"]
                applicable = config.get("publication", {}).get("enabled", False)
            elif stage == "archive_complete_run":
                dependencies = ["sync_and_readback", "notify_new_drafts"]
            add(stage, stage, base, dependencies, applicable)
            previous = [stage]
    else:
        previous = []
        for stage in stages:
            applicable = stage != "deliver_optional" or config.get("delivery", {}).get("enabled", False)
            add(stage, stage, base, previous, applicable)
            previous = [stage]

    completed = progress.get("completed", {})
    blocked = progress.get("blocked", {})
    known = {t["id"] for t in tasks}
    if (set(completed) | set(blocked)) - known or set(completed) & set(blocked):
        raise ValueError("Unknown or contradictory work item")
    states = {}
    for item in tasks:
        key = item["id"]
        if not item["applicable"]:
            states[key] = "not_applicable"
        elif key in completed:
            record = completed[key]
            if record.get("scopeHash") != item["scopeHash"] or not record.get("evidence"):
                raise ValueError("Completed work requires matching scope and durable evidence")
            for evidence in record["evidence"]:
                path = regular(evidence["path"])
                if hashlib.sha256(path.read_bytes()).hexdigest() != evidence["sha256"]:
                    raise ValueError("Work evidence changed; reconcile the original outcome")
            states[key] = "complete"
        elif key in blocked:
            if not isinstance(blocked[key], str) or not blocked[key].strip():
                raise ValueError("Blocked work requires an actionable reason")
            states[key] = "blocked"
        else:
            states[key] = "pending"
    terminal = {"complete", "not_applicable"}
    by_id = {t["id"]: t for t in tasks}

    def satisfied(key):
        return states[key] in terminal and all(satisfied(d) for d in by_id[key]["dependsOn"])

    for item in tasks:
        if states[item["id"]] == "complete" and any(not satisfied(d) for d in item["dependsOn"]):
            raise ValueError("Completed work has unfinished dependencies")
        item["state"] = states[item["id"]]
    runnable = [t for t in tasks if t["state"] == "pending" and all(satisfied(d) for d in t["dependsOn"])]
    return {
        "schemaVersion": 1, "runId": run_id, "bindingHash": binding,
        "tasks": tasks, "next": runnable[0] if runnable else None,
        "remaining": sum(s not in terminal for s in states.values()),
        "blocked": blocked, "readyToSummarize": all(s in terminal for s in states.values()),
    }
