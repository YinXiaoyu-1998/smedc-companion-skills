"""Observable advisory handoff checks using the existing synthetic report fixtures."""

import copy
import csv
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from attach_business_advisory import attach, prepare


class BusinessAdvisoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = tempfile.TemporaryDirectory()
        cls.root = Path(cls.workspace.name)
        for mode, runner in [("diagnosis", "business"), ("weekly", "weekly"), ("monthly", "monthly")]:
            directory = cls.root / mode
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / f"run_{runner}_report.py"),
                 "--bundle", str(ROOT / "tests/fixtures" / f"{mode}_bundle.json"),
                 "--current-user", str(ROOT / "tests/fixtures/current_user_response.json"),
                 "--output-dir", str(directory / "facts"), "--report", str(directory / "base.html")],
                check=True, capture_output=True, text=True,
            )

    @classmethod
    def tearDownClass(cls):
        cls.workspace.cleanup()

    def draft(self, mode="weekly"):
        directory = self.root / mode
        draft = prepare(directory / "facts", mode)
        filename = "store_summary.csv" if mode == "diagnosis" else f"{mode}_store_comparison.csv"
        with (directory / "facts" / filename).open(encoding="utf-8-sig") as source:
            row = next(csv.DictReader(source))
        field = "net_revenue" if mode == "diagnosis" else "current_net_revenue"
        draft["findings"] = [{
            "id": "F1", "module": "stores", "priority": "P1", "confidence": "medium",
            "title": "先核实门店差异再选择试点", "observation": "本期有可核验的门店收入。",
            "interpretation": "先核对可比条件，再决定是否复制其他店的做法。",
            "hypothesis": "渠道组合可能不同，仍待核实。", "alternative": "也可能是营业天数差异。",
            "caveat": "比较时选择商圈与面积相近的门店。",
            "evidence": [{"file": filename, "row": 1, "field": field,
                          "value": row[field], "label": "该门店本期订单营业收入（元）", "format": "number"}],
            "action": {"owner_role": "运营督导", "scope": row["门店名称"],
                       "steps": ["核对营业天数和渠道结构，选择一家条件接近的试点店。"],
                       "review_after": "下次经营会", "primary_metric": "同口径订单营业收入",
                       "guardrail": "折扣率与订单量", "stop_rule": "可比条件不成立时停止复制。"},
        }]
        report = directory / "advisory-test.html"
        report.write_text((directory / "base.html").read_text(encoding="utf-8"), encoding="utf-8")
        return directory / "facts", report, draft

    def test_three_report_types_show_agent_content_without_changing_fact_payload(self):
        for mode in ("diagnosis", "weekly", "monthly"):
            with self.subTest(mode=mode):
                facts, report, draft = self.draft(mode)
                original = report.read_text(encoding="utf-8")
                result = attach(facts, mode, report, draft)
                html = report.read_text(encoding="utf-8")
                self.assertEqual(result["findings"], 1)
                self.assertIn("先核实门店差异再选择试点", html)
                self.assertIn("可比条件不成立时停止复制。", html)
                self.assertIn(draft["findings"][0]["hypothesis"], html)
                feedback = html.split('<!-- SMEDC_ADVISORY_START -->')[1].split('<!-- SMEDC_ADVISORY_END -->')[0]
                self.assertNotIn(draft["findings"][0]["evidence"][0]["file"], feedback)
                self.assertNotIn(str(facts), feedback)
                before = original.split('<script type="application/json" id="report-data">')[1].split("</script>")[0]
                after = html.split('<script type="application/json" id="report-data">')[1].split("</script>")[0]
                self.assertEqual(before, after)

    def test_invalid_evidence_leaves_report_unchanged(self):
        facts, report, draft = self.draft()
        original = report.read_bytes()
        draft["findings"][0]["evidence"][0]["value"] = "999999999999"
        with self.assertRaisesRegex(ValueError, "evidence value"):
            attach(facts, "weekly", report, draft)
        self.assertEqual(report.read_bytes(), original)

    def test_optional_notes_only_appear_when_supplied(self):
        for mode in ("diagnosis", "weekly", "monthly"):
            with self.subTest(mode=mode):
                facts, report, draft = self.draft(mode)
                for key in ("alternative", "caveat"):
                    draft["findings"][0].pop(key)
                action = draft["findings"][0]["action"]
                action["steps"] = ["核对营业天数；一致时选一店试行推荐，存在差异时先按营业日重比。"]
                attach(facts, mode, report, draft)
                html = report.read_text(encoding="utf-8")
                self.assertNotIn("其他可能", html)
                self.assertNotIn("补充说明", html)
                # Omitting optional commentary must preserve the useful check,
                # next decision, metrics, and adjustment condition in each report type.
                for value in [*action["steps"], action["primary_metric"], action["stop_rule"]]:
                    self.assertIn(value, html)
                draft["findings"][0]["caveat"] = "只比较营业天数相同的门店。"
                attach(facts, mode, report, draft)
                self.assertIn(draft["findings"][0]["caveat"], report.read_text(encoding="utf-8"))

    def test_changed_scope_or_stale_facts_are_rejected(self):
        facts, report, draft = self.draft()
        draft["context"]["store_name_contains"] = ["其他品牌"]
        with self.assertRaisesRegex(ValueError, "context"):
            attach(facts, "weekly", report, draft)
        draft = prepare(facts, "weekly")
        with tempfile.TemporaryDirectory() as temporary:
            changed = Path(temporary) / "facts"
            shutil.copytree(facts, changed)
            source = changed / "weekly_store_comparison.csv"
            source.write_bytes(source.read_bytes().replace(b"10000.0", b"10001.0", 1))
            with self.assertRaisesRegex(ValueError, "context"):
                attach(changed, "weekly", report, draft)

    def test_rerun_replaces_feedback_and_escapes_agent_text(self):
        facts, report, draft = self.draft()
        draft["findings"][0]["title"] = '<img src=x onerror="alert(1)">'
        attach(facts, "weekly", report, draft)
        first = report.read_text(encoding="utf-8")
        attach(facts, "weekly", report, draft)
        self.assertEqual(report.read_text(encoding="utf-8"), first)
        self.assertIn("&lt;img src=x", first)
        self.assertNotIn("<img src=x", first)
        self.assertNotIn('href="http', first)

    def test_no_current_data_cannot_acquire_advice_from_history(self):
        facts, report, draft = self.draft()
        html = report.read_text(encoding="utf-8").replace('"current": true', '"current": false')
        report.write_text(html, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "current-period"):
            attach(facts, "weekly", report, draft)
        draft["findings"] = []
        draft["management_questions"] = []
        result = attach(facts, "weekly", report, draft)
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertNotIn('id="business-advisory"', report.read_text(encoding="utf-8"))

    def test_unlisted_sources_and_missing_action_metrics_are_rejected(self):
        facts, report, draft = self.draft()
        invalid = copy.deepcopy(draft)
        invalid["findings"][0]["evidence"][0]["file"] = "../current_user.json"
        with self.assertRaisesRegex(ValueError, "source"):
            attach(facts, "weekly", report, invalid)
        draft["findings"][0]["action"]["primary_metric"] = ""
        with self.assertRaisesRegex(ValueError, "primary_metric"):
            attach(facts, "weekly", report, draft)


if __name__ == "__main__":
    unittest.main()
