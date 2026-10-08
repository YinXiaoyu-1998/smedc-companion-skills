import json
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_query_plan import monthly_trend_window, weekly_trend_window
from profile_weekly_data import trend_rows as weekly_rows
from profile_monthly_data import trend_rows as monthly_rows
from meeting_report_weekly import build_trend_comparison_entities as weekly_chart
from meeting_report_monthly import build_trend_comparison_entities as monthly_chart


class TrendParityTests(unittest.TestCase):
    def test_month_positions_cross_december_without_losing_january(self):
        bundle = json.loads((ROOT / "tests/fixtures/monthly_bundle.json").read_text())
        bundle["report"]["windows"]["current"] = {"start": "2026-01-01", "end": "2026-01-31"}
        bundle["resultsByJobId"] = {"business_6_month_store_trend": {"rows": [
            {"store_name": "示例一店", "business_month": "2025-12", "order_revenue": "90"},
            {"store_name": "示例一店", "business_month": "2026-01", "order_revenue": "100"}]}}
        try:
            chart = monthly_chart(monthly_rows(bundle))[0]["rows"]
        except ValueError as exc:
            self.fail(f"valid cross-year report failed: {exc}")
        self.assertEqual(chart[-1]["week_label"], "2026-01")
        self.assertEqual(chart[-2]["current_net_revenue"], 90)
        self.assertEqual(chart[-1]["current_net_revenue"], 100)

    def test_monthly_year_includes_oldest_month_and_leap_day(self):
        bundle = json.loads((ROOT / "tests/fixtures/monthly_bundle.json").read_text())
        bundle["report"]["windows"]["current"] = {"start": "2024-02-01", "end": "2024-02-29"}
        bundle["resultsByJobId"] = {
            "business_12_month_store_trend": {"rows": [
                {"store_name": "示例一店", "business_month": "2023-02", "order_revenue": "999"},
                {"store_name": "示例一店", "business_month": "2023-03", "order_revenue": "10"},
                {"store_name": "示例一店", "business_month": "2023-12", "order_revenue": "20"},
                {"store_name": "示例一店", "business_month": "2024-02", "order_revenue": "30"}]},
            "business_12_month_prior_year_store_trend": {"rows": [
                {"store_name": "示例一店", "business_month": "2022-03", "order_revenue": "7"},
                {"store_name": "示例一店", "business_month": "2023-02", "order_revenue": "25"}]},
        }
        entities = monthly_chart(monthly_rows(bundle))
        self.assertTrue(entities, "monthly facts must produce a chart")
        chart = entities[0]["rows"]
        self.assertEqual(len(chart), 12)
        self.assertEqual((chart[0]["current_net_revenue"], chart[0]["prior_net_revenue"]), (10, 7))
        self.assertEqual(chart[0]["current_week_range"], "2023-03-01-2023-03-31")
        self.assertEqual(chart[9]["current_net_revenue"], 20)
        self.assertIsNone(chart[1]["current_net_revenue"])
        self.assertEqual(chart[-1]["current_week_range"], "2024-02-01-2024-02-29")
        self.assertEqual(chart[-1]["prior_week_range"], "2023-02-01-2023-02-28")
        self.assertEqual((chart[-1]["current_net_revenue"], chart[-1]["prior_net_revenue"]), (30, 25))

    def test_partial_month_ends_year_window_at_last_complete_month(self):
        self.assertEqual(monthly_trend_window(date(2026, 7, 15)).as_json(),
                         {"start": "2025-07-01", "end": "2026-06-30"})

    def test_saturday_report_does_not_drop_its_last_six_days(self):
        self.assertEqual(weekly_trend_window(date(2026, 6, 20)).as_json(),
                         {"start": "2025-06-22", "end": "2026-06-20"})

    def test_year_window_includes_oldest_week_and_preserves_cross_year_order(self):
        bundle = json.loads((ROOT / "tests/fixtures/weekly_bundle.json").read_text())
        bundle["resultsByJobId"] = {"business_52_week_store_trend": {"rows": [
            {"store_name": "示例一店", "business_date": "2025-07-28", "order_revenue": "10"},
            {"store_name": "示例一店", "business_date": "2025-12-29", "order_revenue": "20"},
            {"store_name": "示例一店", "business_date": "2026-07-26", "order_revenue": "30"},
            {"store_name": "示例一店", "business_date": "2025-07-27", "order_revenue": "999"}]}}
        entities = weekly_chart(weekly_rows(bundle))
        self.assertTrue(entities, "daily trend facts must produce a chart")
        chart = entities[0]["rows"]
        self.assertEqual(len(chart), 52)
        self.assertEqual(chart[0]["current_week_range"], "2025-07-28-2025-08-03")
        self.assertEqual(chart[0]["current_net_revenue"], 10)
        self.assertEqual(chart[22]["current_net_revenue"], 20)
        self.assertEqual(chart[-1]["current_net_revenue"], 30)
        self.assertIsNone(chart[1]["current_net_revenue"])

    def test_month_gap_keeps_matching_calendar_month_and_unknown_value(self):
        bundle = json.loads((ROOT / "tests/fixtures/monthly_bundle.json").read_text())
        bundle["resultsByJobId"] = {
            "business_6_month_store_trend": {"rows": [
                {"store_name": "示例一店", "business_month": "2026/02", "order_revenue": "100"},
                {"store_name": "示例一店", "business_month": "2026/04", "order_revenue": "300"}]},
            "business_6_month_prior_year_store_trend": {"rows": [
                {"store_name": "示例一店", "business_month": "2025/02", "order_revenue": "90"},
                {"store_name": "示例一店", "business_month": "2025/03", "order_revenue": "200"},
                {"store_name": "示例一店", "business_month": "2025/04", "order_revenue": "250"}]},
        }
        chart = monthly_chart(monthly_rows(bundle))[0]["rows"]
        self.assertEqual(len(chart), 12)
        self.assertEqual(chart[7]["week_label"], "2026-03")
        self.assertIsNone(chart[7]["current_net_revenue"])
        self.assertEqual(chart[7]["prior_net_revenue"], 200)
        self.assertEqual((chart[8]["current_net_revenue"], chart[8]["prior_net_revenue"]), (300, 250))
        self.assertEqual(chart[8]["prior_week_range"], "2025-04-01-2025-04-30")

    def test_weekly_daily_facts_use_requested_buckets_and_keep_missing_weeks(self):
        bundle = json.loads((ROOT / "tests/fixtures/weekly_bundle.json").read_text())
        bundle["report"]["windows"]["current"] = {"start": "2026-06-14", "end": "2026-06-20"}
        bundle["report"]["windows"]["yoy"] = {"start": "2025-06-15", "end": "2025-06-21"}
        bundle["resultsByJobId"] = {
            "business_16_week_store_trend": {"rows": [
                {"store_name": "示例一店", "business_date": "2026-06-14", "order_revenue": "100"},
                {"store_name": "示例一店", "business_date": "2026-06-20", "order_revenue": "300"}]},
            "business_16_week_prior_year_store_trend": {"rows": [
                {"store_name": "示例一店", "business_date": "2025-06-14", "order_revenue": "80"},
                {"store_name": "示例一店", "business_date": "2025-06-21", "order_revenue": "250"}]},
        }
        entities = weekly_chart(weekly_rows(bundle))
        self.assertTrue(entities, "daily trend facts must produce a chart")
        chart = entities[0]["rows"]
        self.assertEqual(len(chart), 52)
        self.assertEqual(chart[-1]["current_week_range"], "2026-06-14-2026-06-20")
        self.assertEqual(chart[-1]["prior_week_range"], "2025-06-15-2025-06-21")
        self.assertEqual((chart[-1]["current_net_revenue"], chart[-1]["prior_net_revenue"]), (400, 250))
        self.assertIsNone(chart[-2]["current_net_revenue"])
        self.assertEqual(chart[-2]["prior_net_revenue"], 80)


if __name__ == "__main__":
    unittest.main()
