"""Meal-period evidence and calendar-aligned revenue views from saved MCP facts."""

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from profile_weekly_data import profile
from meeting_report_weekly import build_payload
from profile_monthly_data import profile as profile_monthly
from meeting_report_monthly import build_payload as build_monthly_payload


class MealPeriodAndTrendGrainsTests(unittest.TestCase):
    def profile_bundle(self, mutate, report_type="weekly"):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        directory = Path(workspace.name)
        bundle = json.loads((ROOT / f"tests/fixtures/{report_type}_bundle.json").read_text())
        mutate(bundle)
        path = directory / "bundle.json"
        path.write_text(json.dumps(bundle, ensure_ascii=False))
        (profile if report_type == "weekly" else profile_monthly)(path, directory / "facts")
        return directory / "facts"

    def test_meal_period_combines_hours_and_recalculates_ratios(self):
        def mutate(bundle):
            bundle["resultsByJobId"]["business_current_daypart_mix"] = {"rows": [
                {"store_name": "示例一店", "meal_period": "晚餐", "time_slot": "18:00-19:00",
                 "order_revenue": "100", "positive_orders": "1", "dine_in_revenue": "90",
                 "dine_in_positive_orders": "1", "table_days": "1", "weighted_open_rate": "0.5"},
                {"store_name": "示例一店", "meal_period": "晚餐", "time_slot": "19:00-20:00",
                 "order_revenue": "300", "positive_orders": "2", "dine_in_revenue": "270",
                 "dine_in_positive_orders": "2", "table_days": "3", "weighted_open_rate": "1"},
            ]}
            for suffix in ("supplemental_channel", "supplemental_platform", "supplemental_pickup"):
                bundle["resultsByJobId"].pop("business_current_daypart_mix_" + suffix, None)
        facts = self.profile_bundle(mutate)
        path = facts / "weekly_store_meal_period_comparison.csv"
        self.assertTrue(path.exists(), "advisory evidence must include whole meal periods")
        with path.open(encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
        dinner = next(row for row in rows if row["门店名称"] == "示例一店" and row["餐段"] == "晚餐")
        self.assertEqual(float(dinner["current_net_revenue"]), 400)
        self.assertEqual(float(dinner["current_post_discount_aov"]), 133.33)
        self.assertEqual(float(dinner["current_dine_in_aov"]), 120)
        self.assertEqual(float(dinner["current_open_rate"]), .875)
        self.assertNotIn("时段", dinner)

    def test_monthly_report_has_daily_weekly_and_monthly_views(self):
        def mutate(bundle):
            bundle["resultsByJobId"]["business_daily_store_trend"] = {"rows": [
                {"store_name": "示例一店", "business_date": "2026-07-26", "order_revenue": "12.34"},
            ]}
        facts = self.profile_bundle(mutate, "monthly")
        payload = build_monthly_payload(facts)
        self.assertEqual(set(payload["trend_by_grain"]), {"day", "week", "month"})
        self.assertTrue((facts / "monthly_store_meal_period_comparison.csv").exists())
        self.assertEqual(len(payload["trend_by_grain"]["week"]["entities"][0]["rows"]), 52)

    def test_daily_calendar_alignment_keeps_leap_day_without_reusing_february_28(self):
        def mutate(bundle):
            bundle["report"]["windows"]["current"] = {"start": "2024-02-27", "end": "2024-03-04"}
            bundle["report"]["windows"]["yoy"] = {"start": "2023-02-28", "end": "2023-03-06"}
            bundle["resultsByJobId"]["business_daily_store_trend"] = {"rows": [
                {"store_name": "示例一店", "business_date": "2024-02-28", "order_revenue": "20"},
                {"store_name": "示例一店", "business_date": "2024-02-29", "order_revenue": "40"},
                {"store_name": "示例一店", "business_date": "2023-02-28", "order_revenue": "10"},
            ]}
        payload = build_payload(self.profile_bundle(mutate))
        self.assertTrue("trend_by_grain" in payload, "daily MCP facts must enable day/week/month views")
        day = payload["trend_by_grain"]["day"]["entities"][0]["rows"]
        feb28 = next(row for row in day if row["current_week_range"].startswith("2024-02-28"))
        leap = next(row for row in day if row["current_week_range"].startswith("2024-02-29"))
        self.assertEqual((feb28["current_net_revenue"], feb28["prior_net_revenue"]), (20, 10))
        self.assertEqual(leap["current_net_revenue"], 40)
        self.assertIsNone(leap["prior_net_revenue"])
        self.assertEqual(leap["prior_week_range"], "")

    def test_month_view_uses_complete_calendar_months_and_keeps_empty_buckets(self):
        def mutate(bundle):
            bundle["resultsByJobId"]["business_daily_store_trend"] = {"rows": [
                {"store_name": "示例一店", "business_date": "2026-06-01", "order_revenue": "20"},
                {"store_name": "示例一店", "business_date": "2026-06-30", "order_revenue": "40"},
                {"store_name": "示例一店", "business_date": "2026-07-26", "order_revenue": "999"},
                {"store_name": "示例一店", "business_date": "2025-06-30", "order_revenue": "10"},
            ]}
        payload = build_payload(self.profile_bundle(mutate))
        self.assertTrue("trend_by_grain" in payload)
        month = payload["trend_by_grain"]["month"]["entities"][0]["rows"]
        self.assertEqual(len(month), 12)
        self.assertEqual(month[-1]["current_week_range"], "2026-06-01-2026-06-30")
        self.assertEqual((month[-1]["current_net_revenue"], month[-1]["prior_net_revenue"]), (60, 10))
        self.assertIsNone(month[-2]["current_net_revenue"])

    def test_day_view_preserves_observed_zero_and_unknown_dates(self):
        def mutate(bundle):
            bundle["resultsByJobId"]["business_daily_store_trend"] = {"rows": [
                {"store_name": "示例一店", "business_date": "2026-07-26", "order_revenue": "0"},
                {"store_name": "示例一店", "business_date": "2025-07-26", "order_revenue": "10"},
            ]}
        payload = build_payload(self.profile_bundle(mutate))
        self.assertTrue("trend_by_grain" in payload)
        day = payload["trend_by_grain"]["day"]["entities"][0]["rows"]
        self.assertEqual(len(day), 365)
        self.assertEqual((day[-1]["current_net_revenue"], day[-1]["prior_net_revenue"]), (0, 10))
        self.assertIsNone(day[-2]["current_net_revenue"])


if __name__ == "__main__":
    unittest.main()
