import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "profile_monthly_data.py"
FIXTURE = ROOT / "tests" / "fixtures" / "monthly_bundle.json"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class ProfileMonthlyDataTests(unittest.TestCase):
    maxDiff = None

    def run_profile(self, bundle_data: dict | None = None) -> tuple[Path, dict]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        output_dir = Path(tmp.name)
        bundle_path = FIXTURE
        if bundle_data is not None:
            bundle_path = output_dir / "bundle.json"
            bundle_path.write_text(json.dumps(bundle_data, ensure_ascii=False, indent=2), encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--bundle", str(bundle_path), "--output-dir", str(output_dir)],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        if completed.returncode != 0:
            self.fail(
                f"profile_monthly_data failed with {completed.returncode}\n"
                f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
            )
        return output_dir, json.loads((output_dir / "monthly_meeting_summary.json").read_text(encoding="utf-8"))

    def test_derives_monthly_meeting_facts_from_grouped_bundle(self) -> None:
        output_dir, summary = self.run_profile()

        self.assertEqual(summary["meta"]["report_grain"], "month")
        self.assertEqual(summary["meta"]["coverage"], json.loads(FIXTURE.read_text(encoding="utf-8"))["coverage"])
        self.assertIn("OPTIONAL_MODULE_MISSING", [notice["code"] for notice in summary["notices"]])

        comparisons = read_csv(output_dir / "monthly_store_comparison.csv")
        by_store = {row["门店名称"]: row for row in comparisons}
        self.assertEqual(by_store["示例一店"]["wow_net_revenue_delta"], "4000.0")
        self.assertEqual(by_store["示例一店"]["yoy_net_revenue_pct"], "0.25")
        self.assertEqual(by_store["示例二店"]["store_size_bucket"], "未分组")

        trend = read_csv(output_dir / "monthly_trend_comparison_metrics.csv")
        series_and_months = {(row["series_key"], row["month_label"]) for row in trend if row["net_revenue"]}
        self.assertEqual(
            series_and_months,
            {
                ("prior_year", "2025-06"),
                ("prior_year", "2025-07"),
                ("current_year", "2026-06"),
                ("current_year", "2026-07"),
            },
        )

        daypart_drivers = read_csv(output_dir / "monthly_store_daypart_driver_summary.csv")
        self.assertEqual(daypart_drivers[0]["top_positive_time_slot"], "12:00")

        product_rows = read_csv(output_dir / "monthly_store_product_sales_per_10k.csv")
        beef = next(row for row in product_rows if row["门店名称"] == "示例一店" and row["产品名称"] == "招牌牛肉面")
        self.assertEqual(beef["units_per_10k"], "120.0")
        self.assertEqual(beef["units_per_10k_gross_sales"], "96.0")

        outputs = set(summary["meta"]["outputs"])
        self.assertEqual(
            outputs,
            {
                "monthly_store_metrics.csv",
                "monthly_store_channel_metrics.csv",
                "monthly_store_daypart_metrics.csv",
                "monthly_store_daypart_comparison.csv",
                "monthly_store_meal_period_comparison.csv",
                "monthly_store_daypart_driver_summary.csv",
                "monthly_store_stall_metrics.csv",
                "monthly_store_stall_comparison.csv",
                "monthly_store_stall_driver_summary.csv",
                "monthly_store_stall_dish_drivers.csv",
                "dish_catalog_match_summary.csv",
                "monthly_store_stall_sales_mix.csv",
                "monthly_store_product_sales_per_10k.csv",
                "monthly_trend_comparison_metrics.csv",
                "monthly_store_comparison.csv",
                "store_driver_summary.csv",
                "star_problem_stores.csv",
                "monthly_meeting_summary.json",
            },
        )

    def test_normalizes_slash_separated_business_months(self) -> None:
        bundle = json.loads(FIXTURE.read_text(encoding="utf-8"))
        for job_id in (
            "business_6_month_prior_year_store_trend",
            "business_6_month_store_trend",
        ):
            for row in bundle["resultsByJobId"][job_id]["rows"]:
                row["business_month"] = row["business_month"].replace("-", "/")

        output_dir, _ = self.run_profile(bundle)

        trend = read_csv(output_dir / "monthly_trend_comparison_metrics.csv")
        self.assertEqual(
            {(row["series_key"], row["month_label"], row["month_start"], row["month_end"]) for row in trend if row["net_revenue"]},
            {
                ("prior_year", "2025-06", "2025-06-01", "2025-06-30"),
                ("prior_year", "2025-07", "2025-07-01", "2025-07-31"),
                ("current_year", "2026-06", "2026-06-01", "2026-06-30"),
                ("current_year", "2026-07", "2026-07-01", "2026-07-31"),
            },
        )

    def test_monthly_all_store_channel_rates_are_blank_when_denominator_is_partial(self) -> None:
        bundle = json.loads(FIXTURE.read_text(encoding="utf-8"))
        bundle["resultsByJobId"]["business_current_channel_platform_mix"]["rows"] = [
            {
                "store_name": "示例一店",
                "order_category": "店内销售",
                "order_source": "收银",
                "dining_method": "堂食",
                "order_revenue": "9000",
                "table_days": "1",
                "weighted_open_rate": "0.90",
                "weighted_turnover_rate": "4.00",
            },
            {
                "store_name": "示例二店",
                "order_category": "店内销售",
                "order_source": "收银",
                "dining_method": "堂食",
                "order_revenue": "1000",
                "weighted_open_rate": "0.10",
                "weighted_turnover_rate": "1.00",
            },
        ]

        output_dir, _ = self.run_profile(bundle)

        channel_rows = read_csv(output_dir / "monthly_store_channel_metrics.csv")
        all_store = next(row for row in channel_rows if row["门店名称"] == "全体门店" and row["channel"] == "店内销售 / 收银")
        self.assertEqual(all_store["open_rate"], "")
        self.assertEqual(all_store["turnover_rate"], "")
