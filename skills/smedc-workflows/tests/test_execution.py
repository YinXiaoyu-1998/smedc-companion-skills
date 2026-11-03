import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from execution import plan


class ExecutionTests(unittest.TestCase):
    def run_fixture(self, kind):
        fixture = json.loads((ROOT / "tests/fixtures/three-workflows.json").read_text())
        config = next(c for c in fixture["configurations"] if c["type"] == kind)
        return {"runId": "synthetic-run", "snapshot": {
            "workflowType": kind, "configuration": config,
            "window": {"startDate": "2026-11-02", "endDate": "2026-11-03"},
            "integration": fixture["integration"],
        }}

    def evidence(self, item, path):
        return {"scopeHash": item["scopeHash"], "evidence": [{
            "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }]}

    def test_open_run_with_no_business_work_has_concrete_next_stage(self):
        value = plan({"run": self.run_fixture("meituan-daily-ingestion")})
        self.assertEqual(value["next"]["stage"], "collect")
        self.assertGreater(value["remaining"], 0)
        self.assertFalse(value["readyToSummarize"])

    def test_changed_or_cross_run_evidence_cannot_advance_work(self):
        run = self.run_fixture("meituan-daily-ingestion")
        value = plan({"run": run})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp).resolve() / "proof.json"
            path.write_text('{"synthetic":true}')
            progress = {"runId": run["runId"], "bindingHash": value["bindingHash"],
                        "completed": {value["next"]["id"]: self.evidence(value["next"], path)}}
            advanced = plan({"run": run, "progress": progress})
            self.assertEqual(advanced["next"]["stage"], "validate_original")
            progress["runId"] = "different-run"
            with self.assertRaisesRegex(ValueError, "another frozen run"):
                plan({"run": run, "progress": progress})
            progress["runId"] = run["runId"]
            path.write_text('{"synthetic":"changed"}')
            with self.assertRaisesRegex(ValueError, "evidence changed"):
                plan({"run": run, "progress": progress})

    def test_blocked_dataset_does_not_hide_independent_remaining_work(self):
        run = self.run_fixture("meituan-daily-ingestion")
        value = plan({"run": run})
        progress = {"runId": run["runId"], "bindingHash": value["bindingHash"],
                    "blocked": {value["next"]["id"]: "Source export unavailable"}}
        after = plan({"run": run, "progress": progress})
        self.assertNotEqual(after["next"]["scope"]["dataset"], value["next"]["scope"]["dataset"])
        self.assertFalse(after["readyToSummarize"])

    def test_review_collection_expands_every_explicit_identity(self):
        run = self.run_fixture("meituan-review-operations")
        value = plan({"run": run})
        collect = [t for t in value["tasks"] if t["stage"] == "collect"]
        config = run["snapshot"]["configuration"]
        mappings = [m for m in run["snapshot"]["integration"]["storeMappings"]
                    if m["source"]["product"] == "meituan_reviews"
                    and m["source"]["channel"] in config["channels"]
                    and m["storeName"] in config["storeNames"]]
        self.assertEqual(len(collect), len(mappings))
        publish = next(t for t in value["tasks"] if t["stage"] == "publish_authorized")
        self.assertEqual(publish["dependsOn"], ["workbook"])

    def test_enabled_report_mail_is_remaining_work_after_report_verification(self):
        run = self.run_fixture("weekly-business-report")
        run["snapshot"]["configuration"]["delivery"]["enabled"] = True
        value = plan({"run": run})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp).resolve() / "proof.json"
            path.write_text('{"synthetic":true}')
            completed = {}
            for item in value["tasks"]:
                if item["stage"] == "deliver_optional":
                    break
                completed[item["id"]] = self.evidence(item, path)
            progress = {"runId": run["runId"], "bindingHash": value["bindingHash"], "completed": completed}
            remaining = plan({"run": run, "progress": progress})
            self.assertEqual(remaining["next"]["stage"], "deliver_optional")
            self.assertFalse(remaining["readyToSummarize"])

    def test_disabled_publication_does_not_allow_sync_before_collection(self):
        run = self.run_fixture("meituan-review-operations")
        run["snapshot"]["configuration"]["publication"]["enabled"] = False
        value = plan({"run": run})
        progress = {"runId": run["runId"], "bindingHash": value["bindingHash"],
                    "blocked": {t["id"]: "Source unavailable" for t in value["tasks"] if t["stage"] == "collect"}}
        self.assertIsNone(plan({"run": run, "progress": progress})["next"])


if __name__ == "__main__":
    unittest.main()
