import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from generate_weekly_report_html import render
from profile_weekly_data import profile
from weekly_dashboard import bind_dashboard
from weekly_dining import DiningAccumulator, TRAFFIC, TURNOVER, reviewed_exclusions


class WeeklyDiningReportTests(unittest.TestCase):
    def test_weekly_report_uses_eligible_parties_and_weighted_table_days(self):
        bundle = json.loads((ROOT / "tests/fixtures/weekly_bundle.json").read_text())
        window = bundle["report"]["windows"]["current"]
        stores = [row["store_name"] for row in bundle["resultsByJobId"]["business_current_store_totals"]["rows"]]
        store_a, store_b = sorted(set(stores))[:2]
        day = window["start"]
        exclusions = reviewed_exclusions([
            {"store_name": store_a, "business_date": day, "order_id": "reviewed",
             "reason": "Source receipt documents an erroneous recorded party size"},
        ])
        query = {"filter": {"value": [day, window["end"]]}}
        traffic = DiningAccumulator({"localMetric": TRAFFIC, "input": query}, exclusions)
        for order, size, mode, status in (
            ("normal", 4, "堂食", "已结账"),
            ("normal", 4, "堂食", "已结账"),
            ("outlier", 1111, "堂食", "已结账"),
            ("reviewed", 24, "堂食", "已结账"),
            ("pickup", 3, "外带", "已结账"),
            ("refund", 8, "堂食", "已退单"),
        ):
            traffic.add({"business_date": day, "store_name": store_a, "order_id": order,
                         "diner_count": size, "dining_mode": mode, "order_status": status})
        self.assertEqual(traffic.matched, exclusions)
        turnover = DiningAccumulator({"localMetric": TURNOVER, "input": query}, set())
        for store, count, uses, method in (
            (store_a, 5, 10, "堂食"), (store_a, 5, 5, "堂食"), (store_a, 5, 1, "整单外带"),
            (store_b, 15, 15, "堂食"),
        ):
            turnover.add({"business_date": day, "store_name": store, "table_count": count,
                          "table_use_count": uses, "dining_method": method})
        bundle["resultsByJobId"].update({
            TRAFFIC: {"rows": traffic.rows()}, TURNOVER: {"rows": turnover.rows()},
        })

        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            source, facts, report = work / "bundle.json", work / "facts", work / "report.html"
            source.write_text(json.dumps(bundle))
            profile(source, facts)
            render(facts, report)
            html = report.read_text()
            content = json.loads(re.search(
                r'<script id="weekly-dashboard-content" type="application/json">(.*?)</script>', html, re.S
            )[1])
            self.assertNotIn('"order_id"', html)
            dining = content["details"]["dining"]
            total = dining["weekly"][0]
            self.assertEqual(total["dine_in_headcount"], 4)
            self.assertEqual(total["excluded_orders"], 2)
            self.assertEqual(total["excluded_registered_headcount"], 1135)
            self.assertEqual(total["configured_tables"], 20)
            self.assertEqual(total["estimated_table_turnover"], 1.5)
            self.assertEqual(total["traffic_days"], 1)
            self.assertEqual(total["turnover_days"], 2)
            self.assertEqual(
                {row["门店名称"]: row["estimated_table_turnover"] for row in dining["weekly"] if row["scope"] == "store"},
                {store_a: 3, store_b: 1},
            )
            missing = next(row for row in dining["daily"] if row["scope"] == "all" and row["business_date"] != day)
            self.assertIsNone(missing["dine_in_headcount"])
            self.assertIsNone(missing["estimated_table_turnover"])
            dining["weekly"][0]["dine_in_headcount"] = 1234
            with self.assertRaisesRegex(ValueError, "do not match saved weekly facts"):
                bind_dashboard(html, {}, None, True, dining)


if __name__ == "__main__":
    unittest.main()
