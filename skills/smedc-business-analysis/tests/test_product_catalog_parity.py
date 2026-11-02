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


class ProductCatalogParityTests(unittest.TestCase):
    maxDiff = None

    def run_profile(self, bundle_data: dict) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        output_dir = Path(tmp.name)
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
        return output_dir

    def test_product_sales_prefers_linked_name_and_keeps_aliases_and_scope_denominators(self) -> None:
        bundle = json.loads(FIXTURE.read_text(encoding="utf-8"))
        bundle["resultsByJobId"]["dishes_current_product_totals"]["rows"] = [
            {
                "store_name": "示例一店",
                "product_name": "牛肉面小份",
                "matched_product_name": "招牌牛肉面",
                "order_category": "店内销售",
                "dish_quantity": "50",
                "dish_revenue": "1000",
            },
            {
                "store_name": "示例一店",
                "product_name": "牛肉面大份",
                "matched_product_name": "招牌牛肉面",
                "order_category": "店内销售",
                "dish_quantity": "70",
                "dish_revenue": "1400",
            },
            {
                "store_name": "示例二店",
                "product_name": "牛肉面",
                "matched_product_name": "招牌牛肉面",
                "order_category": "店内销售",
                "dish_quantity": "40",
                "dish_revenue": "800",
            },
        ]

        output_dir = self.run_profile(bundle)

        product_rows = read_csv(output_dir / "weekly_store_product_sales_per_10k.csv")
        store_rows = [
            row
            for row in product_rows
            if row["门店名称"] == "示例一店" and row["产品名称"] == "招牌牛肉面" and row["销售分类"] == "堂食"
        ]
        self.assertEqual(len(store_rows), 2)
        self.assertEqual(sum(float(r["quantity"]) for r in store_rows), 120.0)
        self.assertEqual(store_rows[0]["order_revenue"], "10000.0")
        self.assertEqual(store_rows[0]["gross_sales"], "12500.0")
        self.assertEqual(sum(float(r["units_per_10k"]) for r in store_rows), 120.0)
        self.assertEqual(sum(float(r["units_per_10k_gross_sales"]) for r in store_rows), 96.0)
        self.assertEqual({r["原始品项"] for r in store_rows}, {"牛肉面小份", "牛肉面大份"})
        self.assertEqual({r["quantity_unit"] for r in store_rows}, {"原品项单位"})

        all_stores = [
            row
            for row in product_rows
            if row["门店名称"] == "全体门店" and row["产品名称"] == "招牌牛肉面" and row["销售分类"] == "堂食"
        ]
        self.assertEqual(sum(float(r["quantity"]) for r in all_stores), 160.0)
        self.assertEqual(all_stores[0]["order_revenue"], "15000.0")
        self.assertEqual(all_stores[0]["gross_sales"], "18750.0")

    def test_stall_resolution_prefers_linked_name_before_primary_fallback(self) -> None:
        bundle = json.loads(FIXTURE.read_text(encoding="utf-8"))
        bundle["resultsByJobId"]["dishes_current_product_totals"]["rows"] = [
            {
                "store_name": "示例一店",
                "product_name": "牛肉面",
                "matched_product_name": "招牌牛肉面",
                "order_category": "店内销售",
                "dish_quantity": "120",
                "dish_revenue": "2400",
            }
        ]
        bundle["resultsByJobId"]["dish_catalog_current_snapshot"]["rows"] = [
            {
                "snapshot_date": "2026-07-26",
                "dish_name": "牛肉面",
                "base_category_name": "面档",
                "dish_alias": "",
                "sale_price": "20",
            },
            {
                "snapshot_date": "2026-07-26",
                "dish_name": "招牌牛肉面",
                "base_category_name": "外卖品项",
                "dish_alias": "",
                "sale_price": "20",
            },
        ]

        output_dir = self.run_profile(bundle)

        product_rows = read_csv(output_dir / "weekly_store_product_sales_per_10k.csv")
        canonical = next(
            row
            for row in product_rows
            if row["门店名称"] == "示例一店" and row["产品名称"] == "招牌牛肉面" and row["销售分类"] == "堂食"
        )
        self.assertEqual(canonical["档口"], "外卖品项")

        stall_rows = read_csv(output_dir / "weekly_store_stall_sales_mix.csv")
        store_stall = next(row for row in stall_rows if row["门店名称"] == "示例一店")
        self.assertEqual(store_stall["档口"], "外卖品项")

    def test_catalog_duplicate_names_across_categories_are_ambiguous_not_last_write_wins(self) -> None:
        bundle = json.loads(FIXTURE.read_text(encoding="utf-8"))
        bundle["resultsByJobId"]["dishes_current_product_totals"]["rows"] = [
            {
                "store_name": "示例一店",
                "product_name": "同名套餐",
                "matched_product_name": "",
                "order_category": "店内销售",
                "dish_quantity": "12",
                "dish_revenue": "240",
            }
        ]
        bundle["resultsByJobId"]["dish_catalog_current_snapshot"]["rows"] = [
            {
                "snapshot_date": "2026-07-26",
                "dish_name": "同名套餐",
                "base_category_name": "面档",
                "dish_alias": "",
                "sale_price": "20",
            },
            {
                "snapshot_date": "2026-07-26",
                "dish_name": "同名套餐",
                "base_category_name": "饭档",
                "dish_alias": "",
                "sale_price": "20",
            },
        ]

        output_dir = self.run_profile(bundle)

        product_rows = read_csv(output_dir / "weekly_store_product_sales_per_10k.csv")
        product = next(
            row
            for row in product_rows
            if row["门店名称"] == "示例一店" and row["产品名称"] == "同名套餐" and row["销售分类"] == "堂食"
        )
        self.assertEqual(product["档口"], "未匹配")

        stall_rows = read_csv(output_dir / "weekly_store_stall_sales_mix.csv")
        store_stall = next(row for row in stall_rows if row["门店名称"] == "示例一店")
        self.assertEqual(store_stall["档口"], "未匹配")

    def test_product_sales_keeps_original_items_with_the_same_linked_name_separate(self) -> None:
        bundle = json.loads(FIXTURE.read_text(encoding="utf-8"))
        bundle["resultsByJobId"]["dishes_current_product_totals"]["rows"] = [
            {
                "store_name": "示例一店",
                "product_name": "儿童牛肉面",
                "matched_product_name": "招牌牛肉面",
                "order_category": "店内销售",
                "dish_quantity": "30",
                "dish_revenue": "600",
            },
            {
                "store_name": "示例一店",
                "product_name": "家庭牛肉面",
                "matched_product_name": "招牌牛肉面",
                "order_category": "店内销售",
                "dish_quantity": "90",
                "dish_revenue": "1800",
            },
        ]
        bundle["resultsByJobId"]["dish_catalog_current_snapshot"]["rows"] = [
            {
                "snapshot_date": "2026-07-26",
                "dish_name": "儿童牛肉面",
                "base_category_name": "儿童餐",
                "dish_alias": "",
                "sale_price": "20",
            },
            {
                "snapshot_date": "2026-07-26",
                "dish_name": "家庭牛肉面",
                "base_category_name": "面档",
                "dish_alias": "",
                "sale_price": "20",
            },
        ]

        output_dir = self.run_profile(bundle)

        product_rows = read_csv(output_dir / "weekly_store_product_sales_per_10k.csv")
        store_rows = [
            row
            for row in product_rows
            if row["门店名称"] == "示例一店" and row["产品名称"] == "招牌牛肉面" and row["销售分类"] == "堂食"
        ]
        self.assertEqual(len(store_rows), 2)
        self.assertEqual(sum(float(r["quantity"]) for r in store_rows), 120.0)
        self.assertEqual({r["档口"] for r in store_rows}, {"儿童餐", "面档"})
        self.assertEqual({r["原始品项"] for r in store_rows}, {"儿童牛肉面", "家庭牛肉面"})

    def test_ambiguous_linked_name_does_not_fall_back_but_unmatched_name_does(self):
        bundle = json.loads(FIXTURE.read_text())
        bundle["resultsByJobId"]["dishes_current_product_totals"]["rows"] = [
            {"store_name": "示例一店", "product_name": "原品项", "matched_product_name": linked,
             "order_category": "店内销售", "dish_quantity": "3", "dish_revenue": "60"}
            for linked in ["歧义名称", "不存在", ""]
        ]
        bundle["resultsByJobId"]["dish_catalog_current_snapshot"]["rows"] = [
            {"dish_name": name, "base_category_name": stall}
            for name, stall in [("歧义名称", "面档"), ("歧义名称", "饭档"), ("原品项", "面档")]
        ]
        output = self.run_profile(bundle)
        matches = read_csv(output / "dish_catalog_matches.csv")
        self.assertEqual([(r["match_field"], r["match_status"], r["档口"]) for r in matches], [
            ("matched_product_name", "ambiguous", "未匹配"),
            ("product_name", "matched", "面档"), ("product_name", "matched", "面档")])
        summary = {r["metric"]: r["value"] for r in read_csv(output / "dish_catalog_match_summary.csv")}
        self.assertEqual(summary["ambiguous_rows"], "1")
        self.assertEqual(summary["primary_name_fallback_rows"], "2")

    def test_fees_preserve_income_and_quantities_without_demand_rates(self):
        bundle = json.loads(FIXTURE.read_text())
        bundle["resultsByJobId"]["dishes_current_product_totals"]["rows"] = [
            {"store_name": "示例一店", "product_name": name, "matched_product_name": linked,
             "order_category": "店内销售", "dish_quantity": "12", "dish_revenue": "240"}
            for name, linked in [("牛肉面", "招牌牛肉面"), ("餐具费", "服务项"), ("加工费", ""), ("打包费", ""), ("包装费", "")]
        ]
        output = self.run_profile(bundle)
        products = [r for r in read_csv(output / "weekly_store_product_sales_per_10k.csv") if r["门店名称"] == "示例一店"]
        self.assertEqual(len(products), 5)
        fees = [r for r in products if r["record_kind"] == "fee"]
        self.assertEqual(len(fees), 4)
        self.assertTrue(all(r["quantity"] == "12.0" and r["units_per_10k"] == "" and r["units_per_10k_gross_sales"] == "" for r in fees))
        self.assertTrue(all(r["order_revenue"] == "10000.0" for r in products))
        stalls = [r for r in read_csv(output / "weekly_store_stall_sales_mix.csv") if r["门店名称"] == "示例一店"]
        self.assertEqual(sum(float(r["stall_income"]) for r in stalls), 1200.0)
