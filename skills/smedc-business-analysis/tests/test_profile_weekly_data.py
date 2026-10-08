import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "profile_weekly_data.py"
FIXTURE = ROOT / "tests" / "fixtures" / "weekly_bundle.json"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class ProfileWeeklyDataTests(unittest.TestCase):
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
                f"profile_weekly_data failed with {completed.returncode}\n"
                f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
            )
        return output_dir, json.loads((output_dir / "weekly_meeting_summary.json").read_text(encoding="utf-8"))

    def test_derives_weekly_meeting_facts_from_grouped_bundle(self) -> None:
        output_dir, summary = self.run_profile()

        self.assertEqual(summary["meta"]["report_grain"], "week")
        self.assertEqual(summary["meta"]["coverage"], json.loads(FIXTURE.read_text(encoding="utf-8"))["coverage"])
        self.assertIn("OPTIONAL_MODULE_MISSING", [notice["code"] for notice in summary["notices"]])
        self.assertIn("weekly_meeting_summary.json", summary["meta"]["outputs"])

        comparisons = read_csv(output_dir / "weekly_store_comparison.csv")
        by_store = {row["门店名称"]: row for row in comparisons}
        self.assertEqual(by_store["示例一店"]["store_size_bucket"], "未分组")
        self.assertEqual(by_store["示例一店"]["wow_net_revenue_delta"], "2000.0")
        self.assertEqual(by_store["示例一店"]["wow_net_revenue_pct"], "0.25")
        self.assertEqual(by_store["示例一店"]["open_rate_delta"], "0.125")
        self.assertEqual(by_store["示例二店"]["store_segment"], "问题门店")

        trend = read_csv(output_dir / "weekly_trend_comparison_metrics.csv")
        observed = [row for row in trend if row["net_revenue"]]
        self.assertEqual({row["window_index"] for row in observed}, {"51", "52"})
        self.assertEqual(observed[0]["week_label"], "07/14-07/20")
        self.assertEqual(observed[0]["series_key"], "prior_year")

        channel = read_csv(output_dir / "weekly_store_channel_metrics.csv")
        self.assertEqual(channel[0]["channel"], "店内销售 / 收银")
        self.assertEqual(channel[0]["net_revenue"], "9000.0")

        daypart_drivers = read_csv(output_dir / "weekly_store_daypart_driver_summary.csv")
        self.assertEqual(daypart_drivers[0]["门店名称"], "示例一店")
        self.assertEqual(daypart_drivers[0]["top_positive_daypart"], "午餐")
        self.assertEqual(daypart_drivers[2]["top_negative_daypart"], "午餐")

        stall_mix = read_csv(output_dir / "weekly_store_stall_sales_mix.csv")
        self.assertEqual(stall_mix[0]["档口"], "面档")
        self.assertEqual(stall_mix[0]["stall_income"], "3200.0")
        self.assertNotIn("未匹配", {row["档口"] for row in stall_mix})

        stall_drivers = read_csv(output_dir / "weekly_store_stall_driver_summary.csv")
        self.assertEqual(
            {(row["门店名称"], row["basis"]) for row in stall_drivers},
            {("示例一店", "环比"), ("示例一店", "同比"), ("示例二店", "环比"), ("示例二店", "同比")},
        )

        product_rows = read_csv(output_dir / "weekly_store_product_sales_per_10k.csv")
        beef = next(row for row in product_rows if row["门店名称"] == "示例一店" and row["产品名称"] == "招牌牛肉面")
        self.assertEqual(beef["档口"], "面档")
        self.assertEqual(beef["units_per_10k"], "120.0")
        self.assertEqual(beef["units_per_10k_gross_sales"], "96.0")

        product_details = read_csv(output_dir / "weekly_store_stall_dish_drivers.csv")
        self.assertIn("示例一店", {row["门店名称"] for row in product_details})
        self.assertIn("示例二店", {row["门店名称"] for row in product_details})

    def test_missing_baselines_keep_store_classification_unknown_and_notices_visible(self) -> None:
        bundle = json.loads(FIXTURE.read_text(encoding="utf-8"))
        bundle["coverage"] = {
            "business": {
                "dataset": "business",
                "windows": {
                    "previous": {
                        "isFullyCovered": False,
                        "gaps": [{"startDate": "2026-07-13", "endDate": "2026-07-19"}],
                    }
                },
            }
        }
        bundle["notices"].append(
            {
                "code": "COVERAGE_WINDOW_MISSING",
                "dataset": "business",
                "window": "previous",
                "module": "coreBusiness",
            }
        )
        bundle["resultsByJobId"]["business_previous_store_totals"]["rows"] = [
            row for row in bundle["resultsByJobId"]["business_previous_store_totals"]["rows"] if row["store_name"] != "示例二店"
        ]

        output_dir, summary = self.run_profile(bundle)

        by_store = {row["门店名称"]: row for row in read_csv(output_dir / "weekly_store_comparison.csv")}
        self.assertEqual(by_store["示例二店"]["store_segment"], "对比不足")
        self.assertEqual(by_store["示例二店"]["wow_net_revenue_pct"], "")
        self.assertIn("COVERAGE_WINDOW_MISSING", [notice["code"] for notice in summary["notices"]])
        self.assertEqual(summary["meta"]["coverage"], bundle["coverage"])

    def test_catalog_matching_uses_latest_snapshot_when_rows_conflict(self) -> None:
        bundle = json.loads(FIXTURE.read_text(encoding="utf-8"))
        bundle["resultsByJobId"]["dish_catalog_current_snapshot"]["rows"] = [
            {
                "snapshot_date": "2026-07-26",
                "dish_name": "招牌牛肉面",
                "base_category_name": "面档",
                "dish_alias": "牛肉面",
                "sale_price": "20",
            },
            {
                "snapshot_date": "2026-06-30",
                "dish_name": "招牌牛肉面",
                "base_category_name": "旧档口",
                "dish_alias": "牛肉面",
                "sale_price": "20",
            },
        ]

        output_dir, _ = self.run_profile(bundle)

        product_rows = read_csv(output_dir / "weekly_store_product_sales_per_10k.csv")
        beef = next(row for row in product_rows if row["门店名称"] == "示例一店" and row["产品名称"] == "招牌牛肉面")
        self.assertEqual(beef["档口"], "面档")

    def test_weekly_all_store_channel_rates_are_blank_when_denominator_is_partial(self) -> None:
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

        channel_rows = read_csv(output_dir / "weekly_store_channel_metrics.csv")
        all_store = next(row for row in channel_rows if row["门店名称"] == "全体门店" and row["channel"] == "店内销售 / 收银")
        self.assertEqual(all_store["open_rate"], "")
        self.assertEqual(all_store["turnover_rate"], "")
