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
from attach_business_advisory import attach, prepare, section_sources, number


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
        for review in draft["store_reviews"]:
            for section, names in section_sources(mode).items():
                analysis = review[section]
                if analysis["status"] == "unavailable":
                    continue
                filename = names[0]
                field = "net_revenue" if mode == "diagnosis" else {"meal_periods": "current_net_revenue", "dishes": "quantity", "stalls": "current_income"}[section]
                with (directory / "facts" / filename).open(encoding="utf-8-sig") as source:
                    rows = list(csv.DictReader(source))
                index, row = next((i, row) for i, row in enumerate(rows, 1)
                                  if row["门店名称"] == review["store_name"] and number(row.get(field)) is not None)
                analysis.update(observation="本店本期存在可核验的经营记录。", judgment="先核对销售结构，再决定是否试点。",
                                next_step="核对本店在售与点单情况，稳定时保持，发现问题时只调整一项。",
                                evidence=[{"file": filename, "row": index, "field": field, "value": row[field], "label": "本店本期经营事实", "format": "number"}])
        report = directory / "advisory-test.html"
        report.write_text((directory / "base.html").read_text(encoding="utf-8"), encoding="utf-8")
        return directory / "facts", report, draft

    def test_missing_store_review_cannot_silently_become_a_complete_report(self):
        facts, report, draft = self.draft()
        original = report.read_bytes()
        draft["store_reviews"] = []
        with self.assertRaisesRegex(ValueError, "every current-period store"):
            attach(facts, "weekly", report, draft)
        self.assertEqual(report.read_bytes(), original)

    def test_prepare_identifies_all_current_stores_and_section_availability(self):
        for mode in ("diagnosis", "weekly", "monthly"):
            with self.subTest(mode=mode):
                draft = prepare(self.root / mode / "facts", mode)
                self.assertEqual(draft["schema_version"], 2)
                coverage = draft["context"]["store_coverage"]
                self.assertEqual(len(coverage), 2)
                self.assertEqual({x["store_name"] for x in draft["store_reviews"]}, {x["store_name"] for x in coverage})
                self.assertTrue(all(set(x["sections"]) == {"meal_periods", "dishes", "stalls"} for x in coverage))
                if mode == "diagnosis":
                    self.assertTrue(all(not x["sections"]["dishes"] for x in coverage))

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

    def test_each_store_has_a_collapsed_card_before_enterprise_priorities(self):
        for mode in ("diagnosis", "weekly", "monthly"):
            with self.subTest(mode=mode):
                facts, report, draft = self.draft(mode)
                draft["findings"] = []  # Baseline coverage is independent of enterprise priorities.
                result = attach(facts, mode, report, draft)
                html = report.read_text()
                self.assertEqual(result["store_reviews"], 2)
                self.assertEqual(result["status"], "attached")
                self.assertEqual(html.count('class="store-review-card"'), 2)
                for review in draft["store_reviews"]:
                    self.assertIn(review["store_name"] + '</summary>', html)
                self.assertNotRegex(html, r'<details class="store-review-card"[^>]*\bopen\b')
                self.assertEqual(html.count('data-review-section="meal_periods"'), 2)
                self.assertEqual(html.count('data-review-section="dishes"'), 2)
                self.assertEqual(html.count('data-review-section="stalls"'), 2)
                self.assertLess(html.index('逐店基础分析'), html.index('企业层面重点建议'))
                self.assertIn('grid-template-columns:repeat(3,minmax(0,1fr))', html)
                self.assertIn('@media(max-width:600px)', html)

    def test_store_reviews_reject_duplicates_missing_sections_and_cross_store_evidence(self):
        facts, report, draft = self.draft()
        for mutation, message in [
            (lambda x: x["store_reviews"].append(copy.deepcopy(x["store_reviews"][0])), "every current-period store"),
            (lambda x: x["store_reviews"][0].pop("dishes"), "every store needs"),
            (lambda x: x["store_reviews"][0]["meal_periods"].update(status="unavailable"), "availability"),
            (lambda x: x["store_reviews"][0]["meal_periods"].update(evidence=x["store_reviews"][1]["meal_periods"]["evidence"]), "belong to that store"),
            (lambda x: x["store_reviews"][0]["meal_periods"].update(evidence=x["store_reviews"][0]["stalls"]["evidence"]), "section fact tables"),
        ]:
            with self.subTest(message=message):
                invalid = copy.deepcopy(draft)
                mutation(invalid)
                before = report.read_bytes()
                with self.assertRaisesRegex(ValueError, message):
                    attach(facts, "weekly", report, invalid)
                self.assertEqual(report.read_bytes(), before)

    def test_unavailable_sections_never_acquire_invented_menu_advice(self):
        facts, report, draft = self.draft("diagnosis")
        draft["store_reviews"][0]["dishes"]["judgment"] = "扩大这道菜的供应。"
        with self.assertRaisesRegex(ValueError, "invented advice"):
            attach(facts, "diagnosis", report, draft)

    def test_store_coverage_keeps_recorded_zero_but_excludes_history_only_store(self):
        with tempfile.TemporaryDirectory() as temporary:
            facts = Path(temporary) / "facts"
            shutil.copytree(self.root / "weekly" / "facts", facts)
            source = facts / "weekly_store_comparison.csv"
            with source.open(encoding="utf-8-sig") as handle:
                reader = csv.DictReader(handle)
                fields, rows = reader.fieldnames, list(reader)
            for row in rows:
                for field in fields:
                    if field.startswith("current_"):
                        row[field] = ""
            rows[0]["current_net_revenue"] = "0"
            with source.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader(); writer.writerows(rows)
            draft = prepare(facts, "weekly")
            self.assertEqual([x["store_name"] for x in draft["store_reviews"]], [rows[0]["门店名称"]])

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
        draft["store_reviews"] = []
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
