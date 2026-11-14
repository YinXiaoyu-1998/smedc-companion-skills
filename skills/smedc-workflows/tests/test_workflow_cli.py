import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "workflow.py"


class WorkflowCliTests(unittest.TestCase):
    def review_checks(self):
        package = json.loads((ROOT / "manifest.json").read_text())
        return {
            name: {"status": "ready"}
            for name in package["workflows"]["meituan-review-operations"]["capabilities"]
        }

    def test_readiness_rejects_the_sample_status_that_failed_in_record_checks(self):
        checks = self.review_checks()
        checks["file_format"]["sampleStatus"] = "synthetic_workbook_readback"
        result, _ = self.run_cli("readiness", {
            "workflowType": "meituan-review-operations",
            "checks": checks, "checkedAt": "2026-11-03T03:15:00Z",
        })
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("sampleStatus", result.stderr)

    def test_review_page_collection_does_not_require_a_source_export(self):
        checks = self.review_checks()
        checks["download"] = {"status": "unsupported", "sampleStatus": "no_sample"}
        checks["file_format"] = {"status": "ready", "sampleStatus": "verified",
                                 "nextStep": "Synthetic output workbook independently reopened"}
        result, value = self.run_cli("readiness", {
            "workflowType": "meituan-review-operations",
            "checks": checks, "checkedAt": "2026-11-03T03:15:00Z",
        })
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(value["localReady"])
        export = next(c for c in value["checks"] if c["capability"] == "download")
        self.assertEqual(export["status"], "unsupported")
        checks["meituan_reviews"]["status"] = "needs_login"
        _, value = self.run_cli("readiness", {
            "workflowType": "meituan-review-operations",
            "checks": checks, "checkedAt": "2026-11-03T03:15:00Z",
        })
        self.assertFalse(value["localReady"])

    def test_iab_unavailable_has_a_workflow_level_chrome_fallback(self):
        package = json.loads((ROOT / "manifest.json").read_text())
        self.assertEqual(package["hosts"]["codex"]["browser"], "iab")
        self.assertEqual(package["hosts"]["codex"].get("browserFallback"), ["chrome"])
        for name in ["SKILL.md", "references/installation.md"]:
            self.assertIn("browser.md", (ROOT / name).read_text())
        browser = (ROOT / "references/browser.md").read_text()
        self.assertIn("Browser is not available: iab", browser)
        self.assertIn("Chrome", browser)

    def test_source_reads_are_not_required_to_invent_a_central_action(self):
        runtime = (ROOT / "references/runtime.md").read_text()
        self.assertFalse(
            "在每个外部动作前 `native.claim(session,intent)`" in runtime,
            "Read-only source collection must not require an unsupported intent",
        )
        self.assertIn("浏览器来源读取", runtime)
        self.assertIn("review_collect", runtime)
        self.assertIn("review_export", runtime)
        self.assertIn("withLease", runtime)
        self.assertIn("check_actions", runtime)

    def run_cli(self, operation, value):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary).resolve() / "input.json"
            source.write_text(json.dumps(value))
            result = subprocess.run(
                [sys.executable, str(SCRIPT), operation, "--input", str(source)],
                capture_output=True,
                text=True,
            )
            return result, json.loads(result.stdout) if result.returncode == 0 else {}

    def test_finished_cleanup_preserves_progress_and_is_safe_to_retry(self):
        from datetime import datetime, timedelta, timezone
        import hashlib

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "synthetic-run"
            scratch = root / "temporary"
            scratch.mkdir(parents=True)
            original = scratch / "batch.zip"
            original.write_bytes(b"export")
            report = root / "report.html"
            report.write_text("retained output")
            progress = root / "progress.json"
            owner = root.parent / "run-lock.json"
            binding = {"runId": root.name, "workflowId": "synthetic-flow"}
            owner.write_text(json.dumps(binding))
            evidence = [{"path": str(original)}]
            index = {**binding, "completed": {"stage": {"evidence": evidence}}}
            progress.write_text(json.dumps(index))
            proof = {
                **binding, "status": "succeeded", "finishedAt": "2026-11-14T00:00:00Z",
                "expiresAt": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(),
            }
            files = [{"path": str(original), "sha256": hashlib.sha256(b"export").hexdigest()}]
            value = {
                **binding, "runRoot": str(root), "lockOwnerPath": str(owner),
                "centralProof": proof, "files": files,
            }
            rejected, _ = self.run_cli("cleanup-temporary", value)
            self.assertIn("progress references temporary", rejected.stderr)
            evidence[0]["path"] = str(report)
            progress.write_text(json.dumps(index))
            original.write_bytes(b"changed")
            rejected, _ = self.run_cli("cleanup-temporary", value)
            self.assertIn("hash changed", rejected.stderr)
            self.assertTrue(original.exists())
            original.write_bytes(b"export")
            for _ in range(2):
                completed, result = self.run_cli("cleanup-temporary", value)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(result["deletedFiles"], 1)
            self.assertFalse(original.exists())
            self.assertTrue(report.exists())

    def test_window_is_frozen_and_resumption_does_not_cross_midnight(self):
        result, value = self.run_cli(
            "window",
            {
                "workflowType": "meituan-review-operations",
                "now": "2026-11-02T00:05:00+08:00",
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            value["window"], {"startDate": "2026-11-01", "endDate": "2026-11-02"}
        )
        _, value = self.run_cli(
            "window",
            {
                "workflowType": "meituan-review-operations",
                "now": "2026-11-03T00:05:00+08:00",
                "resume": value["window"],
            },
        )
        self.assertEqual(
            value["window"], {"startDate": "2026-11-01", "endDate": "2026-11-02"}
        )

    def test_migration_rejects_array_control_with_private_projection_guidance(self):
        with tempfile.TemporaryDirectory() as temporary:
            control = Path(temporary).resolve() / "control.json"
            control.write_text(json.dumps([{"status": "SYNTHETIC_SOURCE_VALUE"}]))
            result, _ = self.run_cli(
                "migration",
                {
                    "integration": {},
                    "targetVersion": 1,
                    "workflows": [{"workflowId": "synthetic-workflow"}],
                    "sources": [
                        {
                            "id": "synthetic-control",
                            "kind": "control",
                            "workflowId": "synthetic-workflow",
                            "path": str(control),
                        }
                    ],
                },
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("Control source must be a JSON object", result.stderr)
            self.assertIn(
                "provenance-verified private canonical projection", result.stderr
            )
            self.assertNotIn("Traceback", result.stderr)
            self.assertNotIn("SYNTHETIC_SOURCE_VALUE", result.stderr)

    def test_migration_preserves_three_schedules_and_all_151_receipts_in_bounded_pages(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture = json.loads(
                (ROOT / "tests" / "fixtures" / "three-workflows.json").read_text()
            )
            workflows = []
            sources = []
            for n, kind in enumerate(
                [
                    "meituan-daily-ingestion",
                    "meituan-review-operations",
                    "weekly-business-report",
                ]
            ):
                task = root / f"task-{n}.toml"
                schedule = fixture["legacyHostSchedules"][kind]
                task.write_text(
                    'id = "legacy-'
                    + str(n)
                    + '"\nkind = "cron"\nstatus = "PAUSED"\nrrule = '
                    + json.dumps(schedule)
                    + '\nmodel = "gpt-6.1-sol"\nreasoning_effort = "high"\nprompt = "Read the workflow"\n'
                )
                sources.append(
                    {
                        "id": f"task-{n}",
                        "kind": "task",
                        "path": str(task),
                        "workflowId": f"workflow-{n}",
                        "observedAt": "2026-11-02T00:00:00Z",
                        "promptDecisions": [
                            {"excerpt": "Read the workflow", "destination": "obsolete"}
                        ],
                    }
                )
                workflows.append(
                    {
                        "workflowId": f"workflow-{n}",
                        "configuration": fixture["configurations"][n],
                        "authorizations": fixture["authorizations"][n],
                        "taskSource": f"task-{n}",
                    }
                )
            from datetime import date, timedelta

            receipts = []
            for n in range(151):
                start_date = date(2023, 1, 2) + timedelta(weeks=n)
                receipts.append(
                    {
                        "dedup": f"legacy-key-{n}",
                        "period": {
                            "startDate": start_date.isoformat(),
                            "endDate": (start_date + timedelta(days=6)).isoformat(),
                        },
                        "recipient": "owner@example.test",
                        "sender": "sender@example.test",
                        "provider_id": f"provider-{n}",
                        "status": "sent_verified",
                        "sent_at": (start_date + timedelta(days=7)).isoformat()
                        + "T00:00:00Z",
                        "artifact": "a" * 64,
                        "marker": f"legacy-marker-{n}",
                        "messageBody": "SYNTHETIC_PRIVATE_BODY",
                    }
                )
            ledger = root / "ledger.json"
            ledger.write_text(json.dumps({"actions": receipts}))
            action_id = {"$actionId": {"$pointer": "/dedup"}}
            receipt_template = {
                "legacyKey": {"$pointer": "/dedup"},
                "intent": {
                    "actionId": action_id,
                    "identity": {
                        "kind": "email",
                        "purpose": "weekly_report",
                        "recipients": [{"$pointer": "/recipient"}],
                        "sender": {"$pointer": "/sender"},
                        "deliveryVersion": 1,
                        "storeNames": ["Demo"],
                        "window": {"$pointer": "/period"},
                    },
                    "artifactHash": {"$pointer": "/artifact"},
                    "correlationMarker": {"$pointer": "/marker"},
                },
                "receipt": {
                    "actionId": action_id,
                    "state": {
                        "$map": {
                            "pointer": "/status",
                            "values": {
                                "sent_verified": "confirmed",
                                "unknown": "unknown",
                            },
                        }
                    },
                    "evidence": {
                        "$map": {
                            "pointer": "/status",
                            "values": {
                                "sent_verified": "provider_readback",
                                "unknown": "transport_unknown",
                            },
                        }
                    },
                    "receiptId": {"$pointer": "/provider_id"},
                    "verifiedAt": {"$pointer": "/sent_at"},
                },
            }
            sources.append(
                {
                    "id": "receipts",
                    "kind": "receipts",
                    "path": str(ledger),
                    "workflowId": "workflow-2",
                    "recordsPointer": "/actions",
                    "recordTemplate": receipt_template,
                }
            )
            groups = root / "groups.json"
            groups.write_text(
                json.dumps({"schemaVersion": 1, "groups": {"City Center": ["Demo"]}})
            )
            sources.append(
                {
                    "id": "groups",
                    "kind": "groups",
                    "path": str(groups),
                    "fields": [
                        {
                            "source": "",
                            "destination": "central",
                            "target": "/workflows/2/configuration/groups",
                            "transform": "named_groups",
                        }
                    ],
                }
            )
            policies = json.loads((ROOT / "review-execution-policy.json").read_text())[
                "legacyPolicies"
            ]
            settings = {
                "replyWhitelist": ["Demo"],
                "ignoredRecords": [
                    {
                        "poiId": "poi-demo-2",
                        "source": "美团评价",
                        "feedbackId": "ignored-demo",
                    }
                ],
                **policies,
            }
            settings_file = root / "task-settings.json"
            settings_file.write_text(json.dumps(settings))
            fields = [
                {
                    "source": "/replyWhitelist",
                    "destination": "central",
                    "target": "/workflows/1/configuration/publication/storeNames",
                },
                {
                    "source": "/ignoredRecords",
                    "destination": "central",
                    "target": "/workflows/1/configuration/ignoredReviewIdentities",
                    "transform": "ignored_review_identities",
                },
                *[
                    {
                        "source": "/" + name,
                        "destination": "central",
                        "target": "/workflows/1/configuration/executionPolicy",
                        "transform": "review_policy:" + name,
                    }
                    for name in policies
                ],
            ]
            sources.append(
                {
                    "id": "review-settings",
                    "kind": "settings",
                    "path": str(settings_file),
                    "sourceAccountRef": "review-demo",
                    "fields": fields,
                }
            )
            control = root / "control.json"
            control.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "id": "open-demo",
                                "storeNames": ["Demo"],
                                "window": {
                                    "startDate": "2026-10-01",
                                    "endDate": "2026-10-01",
                                },
                                "body": "SYNTHETIC_PRIVATE_BODY",
                            }
                        ],
                        "waivedItems": [{"id": "waived-demo"}],
                        "resolvedItems": [{"id": "resolved-demo"}],
                    }
                )
            )
            recovery_lists = [
                {
                    "pointer": "/items",
                    "template": {
                        "itemId": {"$pointer": "/id"},
                        "kind": "business",
                        "disposition": "open",
                        "stage": "collecting",
                        "scope": {
                            "kind": "dataset",
                            "dataset": "business",
                            "storeNames": {"$pointer": "/storeNames"},
                            "window": {"$pointer": "/window"},
                        },
                        "evidenceRef": "control",
                        "evidenceHash": {"$hash": {"$pointer": ""}},
                    },
                },
                *[
                    {
                        "pointer": "/" + name,
                        "template": {
                            "itemId": {"$pointer": "/id"},
                            "kind": "evidence",
                            "disposition": disposition,
                            "stage": "finished",
                            "scope": {
                                "kind": "unknown_scope",
                                "reason": "missing_local_evidence",
                            },
                            "evidenceRef": "control",
                            "evidenceHash": {"$hash": {"$pointer": ""}},
                            "resolutionReason": "Retained explicit legacy disposition",
                        },
                    }
                    for name, disposition in [
                        ("waivedItems", "waived"),
                        ("resolvedItems", "resolved"),
                    ]
                ],
            ]
            sources.append(
                {
                    "id": "control",
                    "kind": "control",
                    "path": str(control),
                    "workflowId": "workflow-1",
                    "recoveryLists": recovery_lists,
                }
            )
            request = {
                "sources": sources,
                "integration": fixture["integration"],
                "targetVersion": 0,
                "workflows": workflows,
            }
            result, value = self.run_cli("migration", request)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(value["recordCount"], 154)
            self.assertEqual(value["chunkCount"], 2)
            self.assertEqual(
                len(value["manifest"]["workflows"][2]["completedActions"]), 100
            )
            self.assertEqual(len(value["pages"][0]["chunk"][0]["completedActions"]), 51)
            self.assertNotIn("messageBody", json.dumps(value["manifest"]))
            self.assertNotIn(
                "SYNTHETIC_PRIVATE_BODY",
                json.dumps([value["manifest"], value["pages"]]),
            )
            recovered = value["pages"][0]["chunk"][1]["recoveryItems"]
            self.assertEqual(
                [item["disposition"] for item in recovered],
                ["open", "waived", "resolved"],
            )
            self.assertEqual(recovered[0]["scope"]["window"]["startDate"], "2026-10-01")
            self.assertEqual(
                value["manifest"]["workflows"][1]["hostSnapshot"]["model"],
                "gpt-6.1-sol",
            )
            self.assertEqual(
                value["manifest"]["workflows"][1]["configuration"],
                fixture["configurations"][1],
            )
            self.assertEqual(
                [w["authorizations"] for w in value["manifest"]["workflows"]],
                fixture["authorizations"],
            )
            self.assertEqual(
                value["manifest"]["workflows"][2]["configuration"]["groups"],
                [{"name": "City Center", "storeNames": ["Demo"]}],
            )
            repeated, again = self.run_cli("migration", request)
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            self.assertEqual(again["manifest"], value["manifest"])
            self.assertEqual(again["chunksDigest"], value["chunksDigest"])
            settings["sourceAuthorityPolicy"]["observedFields"] = "unverified_values"
            settings_file.write_text(json.dumps(settings))
            rejected, _ = self.run_cli("migration", request)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("source_conflict", rejected.stderr)

    def test_readiness_keeps_local_report_available_without_gmail_and_distinguishes_no_sample(
        self,
    ):
        capabilities = [
            "configuration",
            "permissions",
            "download",
            "workspace",
            "dependencies",
            "host_schedule",
            "host_timezone",
            "host_model",
            "assignment",
        ]
        checks = {name: {"status": "ready", "nextStep": ""} for name in capabilities}
        checks["email_identity"] = {
            "status": "needs_login",
            "nextStep": "Connect Gmail",
        }
        result, value = self.run_cli(
            "readiness",
            {
                "workflowType": "weekly-business-report",
                "checks": checks,
                "mailEnabled": True,
                "checkedAt": "2026-11-02T00:00:00Z",
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(value["localReady"])
        self.assertFalse(value["deliveryReady"])
        self.assertEqual(value["firstRunVerification"], "not_run")

    def test_installer_copies_only_selected_dependency_closure_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary).resolve() / "skills"
            request = {
                "selected": ["weekly-business-report"],
                "sourceSkillsRoot": str(ROOT.parent),
                "destinationRoot": str(destination),
                "sourceRevision": "a" * 40,
            }
            result, value = self.run_cli("install", request)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                set(value["installed"]), {"smedc-workflows", "smedc-business-analysis"}
            )
            self.assertFalse((destination / "reply-meituan-reviews").exists())
            result, value = self.run_cli("install", request)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(value["installed"], [])

    def test_cleanup_refuses_unknown_receipt_and_preserves_the_original(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            run = root / "run"
            run.mkdir()
            original = run / "original.xlsx"
            original.write_bytes(b"original")
            lock = root / "lock.json"
            lock.write_text(json.dumps({"runId": "r"}))
            request = {
                "runRoot": str(run),
                "runId": "r",
                "workflowId": "w",
                "lockOwnerPath": str(lock),
                "files": [{"path": str(original), "sha256": "x", "actionId": "a"}],
                "centralProof": {
                    "workflowId": "w",
                    "runId": "r",
                    "actions": [{"actionId": "a", "state": "unknown"}],
                },
            }
            result, _ = self.run_cli("cleanup", request)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("confirmed", result.stderr)
            self.assertTrue(original.exists())

    def test_no_enterprise_schedule_default_and_legacy_review_times_preserved(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from dateutil.rrule import rrulestr

        package = json.loads((ROOT / "manifest.json").read_text())
        for definition in package["workflows"].values():
            self.assertNotIn("defaultSchedule", definition)
        fixture = json.loads((ROOT / "tests/fixtures/three-workflows.json").read_text())
        schedule = rrulestr(
            fixture["legacyHostSchedules"]["meituan-review-operations"],
            dtstart=datetime(2026, 11, 2, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        actual = [value.strftime("%H:%M") for value in schedule[:5]]
        self.assertEqual(actual, ["00:00", "08:30", "11:00", "17:00", "21:00"])
        self.assertEqual(schedule[5].strftime("%Y-%m-%d %H:%M"), "2026-11-03 00:00")

    def test_frozen_review_task_restores_namespaced_exclusions_and_the_closed_preset(
        self,
    ):
        source = {
            "product": "meituan_reviews",
            "channel": "meituan",
            "accountRef": "demo-account",
            "sourceStoreId": "demo-poi",
            "sourceStoreName": "Demo source",
        }
        ignored = {
            "source": source,
            "feedbackId": "demo-feedback",
            "reason": "Explicit known exclusion",
            "purpose": "exclude_source_record",
        }
        value = {
            "enterpriseName": "Demo enterprise",
            "snapshot": {
                "integration": {
                    "storeMappings": [{"source": source, "storeName": "Demo"}]
                },
                "configuration": {
                    "type": "meituan-review-operations",
                    "channels": ["meituan"],
                    "storeNames": ["Demo"],
                    "publication": {"enabled": False, "storeNames": ["Demo"]},
                    "executionPolicy": {
                        "id": "verified-review-operations",
                        "version": 1,
                    },
                    "ignoredReviewIdentities": [ignored],
                },
            },
        }
        result, task = self.run_cli("review-task", value)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(task["ignoredReviewIdentities"], [ignored])
        self.assertEqual(
            task["sourceIdentityMappings"][0]["source"]["accountRef"], "demo-account"
        )
        self.assertEqual(
            task["unrecognizedReviewGraphicsPolicy"]["action"], "omit_unrecognized_only"
        )
        self.assertTrue(task["errorRecordingPolicy"]["preDispatchCheckpointRequired"])
        value["snapshot"]["configuration"]["channels"] = ["meituan", "dianping"]
        result, _ = self.run_cli("review-task", value)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("channel", result.stderr)
        value["snapshot"]["integration"]["storeMappings"].append(
            {"source": {**source, "channel": "dianping"}, "storeName": "Demo"}
        )
        result, task = self.run_cli("review-task", value)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(task["sourceIdentityMappings"]), 2)
        self.assertEqual(task["mappings"][0]["sourceStores"], [{"storeName": "Demo source"}])
        value["snapshot"]["configuration"]["channels"] = ["meituan"]
        value["snapshot"]["configuration"]["executionPolicy"]["version"] = 2
        result, _ = self.run_cli("review-task", value)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unsupported", result.stderr)

    def test_range_download_proof_verifies_exact_local_bytes_before_confirming(self):
        import hashlib

        with tempfile.TemporaryDirectory() as temporary:
            directory = (
                Path(temporary).resolve() / "smedc-partition-extracts" / "extract-demo"
            )
            directory.mkdir(parents=True)
            csv = directory / "business_20261101_demo.csv"
            csv.write_text("date,store,amount\n2026-11-01,Demo,10\n")
            item = {
                "fileName": csv.name,
                "storeId": "demo",
                "storeName": "Demo",
                "businessDate": "2026-11-01",
                "byteSize": csv.stat().st_size,
                "rowCount": 1,
                "checksumSha256": hashlib.sha256(csv.read_bytes()).hexdigest(),
            }
            metadata = {
                "dataset": "business",
                "enterpriseName": "Demo enterprise",
                "startDate": "2026-11-01",
                "endDate": "2026-11-01",
                "partitionCount": 1,
                "totalRowCount": 1,
                "files": [item],
            }
            (directory / "manifest.json").write_text(json.dumps(metadata))
            response = {
                **metadata,
                "localDirectory": str(directory),
                "files": [csv.name],
            }
            intent = {
                "actionId": "read-demo",
                "identity": {
                    "kind": "download",
                    "dataset": "business",
                    "storeNames": ["Demo"],
                    "window": {"startDate": "2026-11-01", "endDate": "2026-11-01"},
                },
            }
            request = {
                "response": response,
                "intent": intent,
                "identityHash": "a" * 64,
                "launcherVersion": "0.16.0",
            }
            result, receipt = self.run_cli("download-proof", request)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(receipt["evidence"], "launcher_transfer")
            self.assertEqual(receipt["launcherTransfer"]["totalRowCount"], "1")
            self.assertEqual(
                receipt["launcherTransfer"]["totalByteSize"], str(csv.stat().st_size)
            )
            csv.write_text("corrupt")
            result, _ = self.run_cli("download-proof", request)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("checksum", result.stderr)

    def test_chunked_local_state_write_is_repeatable_and_preserves_unicode(self):
        import hashlib

        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary).resolve() / "state.json"
            text = json.dumps(
                {"note": "synthetic 😀", "receipts": [1, 2, 3]}, ensure_ascii=False
            )
            request = {
                "path": str(target),
                "uploadId": "demo-upload",
                "offset": 0,
                "text": text,
                "final": True,
                "checksumSha256": hashlib.sha256(text.encode()).hexdigest(),
            }
            for _ in range(2):
                result, _ = self.run_cli("save-chunk", request)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                json.loads(target.read_text()),
                {"note": "synthetic 😀", "receipts": [1, 2, 3]},
            )

    def test_review_sync_proof_compares_every_observed_field_and_preserves_independent_rows(
        self,
    ):
        import hashlib

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            expected = {
                "enterpriseName": "Demo enterprise",
                "source": "美团评价",
                "storeName": "Demo",
                "feedbackId": "demo-feedback",
                "reviewerName": "Anonymous",
                "reviewedAt": "2026-11-01T12:00:00+08:00",
                "content": "Synthetic review",
                "merchantReply": None,
                "replyStatus": "unreplied_with_content",
                "scores": {"总评": 5},
            }
            independent = {
                **expected,
                "id": "independent-id",
                "reviewerName": "Independent identity",
            }
            source = {
                "product": "meituan_reviews",
                "accountRef": "demo-account",
                "channel": "meituan",
                "sourceStoreId": "demo-poi",
                "sourceStoreName": "Demo source",
            }
            plan = {
                "entries": [
                    {
                        "payload": expected,
                        "sourceIdentity": source,
                        "existingId": "persisted-id",
                        "independentRows": [independent],
                    }
                ]
            }
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(plan))
            response_path = root / "readback.json"
            response = {
                "rows": [{**expected, "id": "persisted-id"}, independent],
                "page": {"nextCursor": None},
            }
            response_path.write_text(json.dumps(response))
            canonical = json.dumps(
                [expected], ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            observed_hash = hashlib.sha256(canonical.encode()).hexdigest()
            intent = {
                "actionId": "sync-demo",
                "identity": {
                    "kind": "review_sync",
                    "source": {
                        "product": "meituan_reviews",
                        "accountRef": "demo-account",
                        "channel": "meituan",
                        "sourceStoreId": "demo-poi",
                        "sourceStoreName": "Demo source",
                    },
                    "storeNames": ["Demo"],
                    "window": {"startDate": "2026-11-01", "endDate": "2026-11-01"},
                    "observedFactsHash": observed_hash,
                },
            }
            request = {
                "intent": intent,
                "identityHash": "a" * 64,
                "planPath": str(plan_path),
                "readbackPaths": [[str(response_path)]],
            }
            result, receipt = self.run_cli("review-sync-proof", request)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(receipt["evidence"], "smedc_readback")
            self.assertEqual(receipt["smedcReadback"]["recordIds"], ["persisted-id"])
            response["rows"][0]["content"] = "Different persisted content"
            response_path.write_text(json.dumps(response))
            result, _ = self.run_cli("review-sync-proof", request)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("readback", result.stderr)

    def test_cleanup_removes_only_the_confirmed_unchanged_original_and_persists_its_result(
        self,
    ):
        import hashlib
        from datetime import datetime, timezone, timedelta

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            run = root / "run"
            run.mkdir()
            original = run / "source.xlsx"
            original.write_bytes(b"synthetic original")
            other = run / "keep.xlsx"
            other.write_bytes(b"not selected")
            lock = root / "lock.json"
            lock.write_text(json.dumps({"runId": "r"}))
            checksum = hashlib.sha256(original.read_bytes()).hexdigest()
            result_path = root / "cleanup-result.json"
            request = {
                "runRoot": str(run),
                "runId": "r",
                "workflowId": "w",
                "lockOwnerPath": str(lock),
                "resultPath": str(result_path),
                "files": [{"path": str(original), "sha256": checksum, "actionId": "a"}],
                "centralProof": {
                    "workflowId": "w",
                    "runId": "r",
                    "expiresAt": (
                        datetime.now(timezone.utc) + timedelta(seconds=30)
                    ).isoformat(),
                    "actions": [
                        {
                            "actionId": "a",
                            "runId": "r",
                            "state": "confirmed",
                            "identity": {"kind": "upload", "sourceHash": checksum},
                            "receipt": {
                                "state": "confirmed",
                                "evidence": "service_status",
                                "jobId": "published-job",
                            },
                        }
                    ],
                },
            }
            result, summary = self.run_cli("cleanup", request)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(original.exists())
            self.assertTrue(other.exists())
            self.assertTrue(lock.exists())
            self.assertEqual(summary["deleted"], [str(original)])
            self.assertEqual(json.loads(result_path.read_text())["status"], "succeeded")

    def test_workspace_preflight_returns_canonical_owned_paths_before_strict_state_writes(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            actual = root / "owned"
            actual.mkdir()
            alias = root / "alias"
            alias.symlink_to(actual, target_is_directory=True)
            result, value = self.run_cli(
                "prepare-workspace",
                {
                    "path": str(alias),
                    "workflowId": "demo-workflow",
                    "installationId": "demo-installation",
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(value["workspaceRoot"], str(actual))
            self.assertEqual(value["statePath"], str(actual / "state.json"))
            self.assertEqual(value["check"]["status"], "ready")
            saved, _ = self.run_cli(
                "save-chunk",
                {
                    "path": value["statePath"],
                    "uploadId": "canonical-check",
                    "offset": 0,
                    "text": "{}",
                    "final": True,
                    "checksumSha256": "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
                },
            )
            self.assertEqual(saved.returncode, 0, saved.stderr)
            rejected, _ = self.run_cli(
                "prepare-workspace",
                {
                    "path": str(actual),
                    "workflowId": "other-workflow",
                    "installationId": "other-installation",
                },
            )
            self.assertNotEqual(rejected.returncode, 0)
