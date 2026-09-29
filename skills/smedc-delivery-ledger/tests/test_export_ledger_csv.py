import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "export_ledger_csv.py"
FIXTURE = ROOT / "tests" / "fixtures" / "ledger-pages.json"

PROFILE = {
    "id": "food-purchase-ledger-cn-v2",
    "title": "食品经营单位进货台帐",
    "columns": [
        {"canonicalName": "receipt_id", "displayName": "收货单号"},
        {"canonicalName": "item_name", "displayName": "食品名称"},
        {"canonicalName": "specification", "displayName": "规格"},
        {"canonicalName": "purchase_quantity", "displayName": "进货数量"},
        {"canonicalName": "purchase_amount", "displayName": "进货金额"},
        {"canonicalName": "production_date_or_batch", "displayName": "生产日期或生产批号"},
        {"canonicalName": "shelf_life", "displayName": "保质期"},
        {"canonicalName": "supplier_name", "displayName": "供货单位名称"},
        {"canonicalName": "supplier_unit_address", "displayName": "供货单位地址"},
        {"canonicalName": "supplier_contact_phone", "displayName": "供货单位联系方式"},
        {"canonicalName": "purchase_date", "displayName": "进货日期"},
    ],
}
HEADERS = [column["displayName"] for column in PROFILE["columns"]]


def page(rows):
    return {
        "dataset": "delivery_ledger",
        "mode": "detail",
        "presentation": PROFILE,
        "rows": rows,
        "nextCursor": None,
    }


def complete_row(**overrides):
    row = {
        "receipt_id": "SH-20260915-001",
        "item_name": "牛奶",
        "specification": "250ml",
        "purchase_quantity": "12.50",
        "purchase_amount": "99.90",
        "production_date_or_batch": "2026-09-01",
        "shelf_life": "180天",
        "supplier_name": "上海供应商A",
        "supplier_unit_address": "上海市黄浦区",
        "supplier_contact_phone": "+8613800138000",
        "purchase_date": "2026-09-15",
    }
    row.update(overrides)
    return row


class ExportLedgerCsvTests(unittest.TestCase):
    def run_export(self, payload, output_path, *extra_args):
        input_path = output_path.with_suffix(".json")
        input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(input_path), str(output_path), *extra_args],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

    def read_csv(self, output_path):
        with output_path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.reader(handle))

    def assert_export_ok(self, payload):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "ledger.csv"
            result = self.run_export(payload, output_path)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(output_path.read_bytes().startswith(b"\xef\xbb\xbf"))
            return self.read_csv(output_path)

    def assert_export_fails(self, payload, message_fragment=""):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "ledger.csv"
            result = self.run_export(payload, output_path)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output_path.exists(), result.stderr)
            if message_fragment:
                self.assertIn(message_fragment, result.stderr)

    def test_exports_valid_object_with_presentation_bom_exact_headers_and_order(self):
        rows = self.assert_export_ok(page([complete_row()]))
        self.assertEqual(rows[0], HEADERS)
        self.assertEqual(rows[1], ["SH-20260915-001", "牛奶", "250ml", "12.50", "99.90", "2026-09-01", "180天", "上海供应商A", "上海市黄浦区", "'+8613800138000", "2026-09-15"])

    def test_exports_valid_presentation_array_preserving_page_and_row_order(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        rows = self.assert_export_ok(payload)
        self.assertEqual(rows[0], HEADERS)
        self.assertEqual([row[0] for row in rows[1:]], ["SH-20260915-001", "SH-20260916-001", "SH-20260917-001"])
        self.assertEqual([row[1] for row in rows[1:]], ["牛奶", "苹果,红富士", "'=配方"])

    def test_null_and_absent_nullable_fields_become_empty_cells(self):
        rows = self.assert_export_ok(page([complete_row(production_date_or_batch=None, shelf_life=None, supplier_unit_address=None, supplier_contact_phone=None)]))
        self.assertEqual(rows[1][5:7], ["", ""])
        self.assertEqual(rows[1][8:10], ["", ""])
        rows = self.assert_export_ok(page([{
            "receipt_id": "SH-20260915-002",
            "item_name": "茶叶",
            "specification": "500g",
            "purchase_quantity": "1",
            "purchase_amount": "88.00",
            "supplier_name": "茶叶供应商",
            "purchase_date": "2026-09-15",
        }]))
        self.assertEqual(rows[1][5:7], ["", ""])
        self.assertEqual(rows[1][8:10], ["", ""])

    def test_string_null_sentinels_in_nullable_fields_become_empty_cells(self):
        rows = self.assert_export_ok(page([complete_row(
            production_date_or_batch="null",
            shelf_life="null",
            supplier_unit_address="null",
            supplier_contact_phone="null",
        )]))
        self.assertEqual(rows[1][5:7], ["", ""])
        self.assertEqual(rows[1][8:10], ["", ""])

    def test_decimals_phones_formula_prefixes_and_csv_quoting_are_preserved(self):
        rows = self.assert_export_ok(page([complete_row(
            item_name="=SUM(A1:A2)",
            specification="+规格,带逗号",
            purchase_quantity="-12.50",
            purchase_amount="@99.90",
            supplier_name='供应商 "甲"',
        )]))
        self.assertEqual(rows[1][1], "'=SUM(A1:A2)")
        self.assertEqual(rows[1][2], "'+规格,带逗号")
        self.assertEqual(rows[1][3], "'-12.50")
        self.assertEqual(rows[1][4], "'@99.90")
        self.assertEqual(rows[1][9], "'+8613800138000")
        self.assertEqual(rows[1][7], '供应商 "甲"')

    def test_single_file_mode_empty_result_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "ledger.csv"
            result = self.run_export(page([]), output_path)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(output_path.exists())
            self.assertEqual(json.loads(result.stdout), {
                "files_written": 0,
                "mode": "single-file",
                "rows_exported": 0,
            })

    def test_single_file_mode_empty_result_with_overwrite_leaves_existing_file_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "ledger.csv"
            original = b"sentinel existing csv bytes"
            output_path.write_bytes(original)
            result = self.run_export(page([]), output_path, "--overwrite")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output_path.read_bytes(), original)
            self.assertEqual(json.loads(result.stdout)["files_written"], 0)

    def test_delete_input_removes_agent_owned_json_after_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "ledger.csv"
            input_path = output_path.with_suffix(".json")
            result = self.run_export(page([complete_row()]), output_path, "--delete-input")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(output_path.exists())
            self.assertFalse(input_path.exists())

    def test_delete_input_removes_agent_owned_json_after_validation_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "ledger.csv"
            input_path = output_path.with_suffix(".json")
            result = self.run_export(
                page([complete_row(purchase_date="bad-date")]),
                output_path,
                "--delete-input",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output_path.exists())
            self.assertFalse(input_path.exists())

    def test_delete_input_rejects_same_input_and_output_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            shared_path = Path(tmp) / "ledger.json"
            shared_path.write_text(
                json.dumps(page([complete_row()]), ensure_ascii=False),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    str(shared_path),
                    str(shared_path),
                    "--overwrite",
                    "--delete-input",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("input JSON and output CSV must be different files", result.stderr)
            self.assertFalse(shared_path.exists())

    def run_store_month(self, payload, output_dir, month):
        input_path = output_dir / "ledger.json"
        input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(input_path), "--store-month-dir", str(output_dir), "--month", month],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

    def test_store_month_mode_creates_conventional_store_files_without_store_name_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            payload = page([
                complete_row(store_name="通州店", receipt_id="TZ-20260901-001", item_name="牛奶"),
                complete_row(store_name="海淀店", receipt_id="HD-20260902-001", item_name="苹果", purchase_date="2026-09-16"),
            ])
            result = self.run_store_month(payload, output_dir, "2026-09")
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(result.stdout)
            self.assertEqual(summary["mode"], "store-month")
            self.assertEqual(summary["files_written"], 2)
            self.assertEqual(summary["rows_appended"], 2)
            tongzhou_path = output_dir / "食品经营单位进货台帐_通州店_2026-09.csv"
            self.assertTrue(tongzhou_path.exists())
            self.assertEqual(self.read_csv(tongzhou_path), [
                HEADERS,
                ["TZ-20260901-001", "牛奶", "250ml", "12.50", "99.90", "2026-09-01", "180天", "上海供应商A", "上海市黄浦区", "'+8613800138000", "2026-09-15"],
            ])
            haidian_path = output_dir / "食品经营单位进货台帐_海淀店_2026-09.csv"
            self.assertTrue(haidian_path.exists())
            self.assertEqual(self.read_csv(haidian_path)[1][0:2], ["HD-20260902-001", "苹果"])

    def test_store_month_mode_maintains_existing_file_by_receipt_not_row_deduping(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            output_path = output_dir / "食品经营单位进货台帐_通州店_2026-09.csv"
            with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(HEADERS)
                writer.writerow(["TZ-OLD", "牛奶", "250ml", "1", "8.00", "2026-09-01", "180天", "旧供应商", "地址", "电话", "2026-09-01"])
            before = output_path.read_text(encoding="utf-8-sig")
            payload = page([
                complete_row(store_name="通州店", receipt_id="TZ-OLD", item_name="应被整单跳过", purchase_date="2026-09-02"),
                complete_row(store_name="通州店", receipt_id="TZ-NEW", item_name="豆腐", purchase_date="2026-09-03"),
                complete_row(store_name="通州店", receipt_id="TZ-NEW", item_name="豆腐", purchase_date="2026-09-03"),
            ])
            result = self.run_store_month(payload, output_dir, "2026-09")
            self.assertEqual(result.returncode, 0, result.stderr)
            rows = self.read_csv(output_path)
            self.assertEqual(rows[1][0:2], ["TZ-OLD", "牛奶"])
            self.assertEqual([row[0] for row in rows[2:]], ["TZ-NEW", "TZ-NEW"])
            self.assertEqual([row[1] for row in rows[2:]], ["豆腐", "豆腐"])
            self.assertNotEqual(output_path.read_text(encoding="utf-8-sig"), before)
            summary = json.loads(result.stdout)
            self.assertEqual(summary["receipts_skipped"], 1)
            self.assertEqual(summary["receipts_appended"], 1)
            self.assertEqual(summary["rows_appended"], 2)

    def test_store_month_mode_empty_result_writes_nothing_and_leaves_existing_file_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            output_path = output_dir / "食品经营单位进货台帐_通州店_2026-09.csv"
            output_path.write_text("sentinel", encoding="utf-8")
            result = self.run_store_month(page([]), output_dir, "2026-09")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output_path.read_text(encoding="utf-8"), "sentinel")
            self.assertEqual(json.loads(result.stdout)["files_written"], 0)

    def test_store_month_mode_validates_all_inputs_before_touching_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            output_path = output_dir / "食品经营单位进货台帐_通州店_2026-09.csv"
            output_path.write_text("sentinel", encoding="utf-8")
            payload = page([
                complete_row(store_name="通州店", receipt_id="TZ-GOOD", purchase_date="2026-09-03"),
                complete_row(store_name="海淀店", receipt_id="HD-BAD", purchase_date="2026-10-01"),
            ])
            result = self.run_store_month(payload, output_dir, "2026-09")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("requested month", result.stderr)
            self.assertEqual(output_path.read_text(encoding="utf-8"), "sentinel")
            self.assertFalse((output_dir / "食品经营单位进货台帐_海淀店_2026-09.csv").exists())

    def test_store_month_mode_rejects_invalid_existing_file_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            bad_path = output_dir / "食品经营单位进货台帐_通州店_2026-09.csv"
            with bad_path.open("w", encoding="utf-8-sig", newline="") as handle:
                csv.writer(handle).writerows([["wrong"], ["TZ-OLD"]])
            payload = page([complete_row(store_name="通州店", receipt_id="TZ-NEW", purchase_date="2026-09-03")])
            result = self.run_store_month(payload, output_dir, "2026-09")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("existing CSV header", result.stderr)
            self.assertEqual(self.read_csv(bad_path), [["wrong"], ["TZ-OLD"]])

    def test_store_month_mode_rejects_store_names_that_collide_after_filesystem_normalization(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            payload = page([
                complete_row(store_name="Alpha", receipt_id="ALPHA-001", purchase_date="2026-09-03"),
                complete_row(store_name="alpha", receipt_id="LOWER-001", purchase_date="2026-09-04"),
            ])
            result = self.run_store_month(payload, output_dir, "2026-09")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("filename collision", result.stderr)
            self.assertEqual(list(output_dir.glob("*.csv")), [])

    def test_store_month_mode_rejects_windows_invalid_store_filename_characters_before_writing(self):
        for character in '<>"|?*':
            with self.subTest(character=character):
                with tempfile.TemporaryDirectory() as tmp:
                    output_dir = Path(tmp)
                    payload = page([
                        complete_row(store_name=f"A{character}B", receipt_id="BAD-STORE", purchase_date="2026-09-03"),
                    ])
                    result = self.run_store_month(payload, output_dir, "2026-09")
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("store_name", result.stderr)
                    self.assertEqual(list(output_dir.glob("*.csv")), [])

    def test_rejects_invalid_dates(self):
        self.assert_export_fails(page([complete_row(purchase_date="2026-9-15")]), "purchase_date")
        self.assert_export_fails(page([complete_row(purchase_date="2026-02-30")]), "purchase_date")

    def test_preserves_numeric_production_batch_identifiers(self):
        for batch in ("12345678", "20260901", "2026-09-01"):
            with self.subTest(batch=batch):
                rows = self.assert_export_ok(page([complete_row(production_date_or_batch=batch)]))
                self.assertEqual(rows[1][5], batch)

    def test_rejects_wrong_dataset_mode_and_presentation(self):
        bad = page([complete_row()])
        bad["dataset"] = "business"
        self.assert_export_fails(bad, "dataset")
        bad = page([complete_row()])
        bad["mode"] = "summary"
        self.assert_export_fails(bad, "mode")
        bad = page([complete_row()])
        bad["presentation"] = {**PROFILE, "title": "wrong"}
        self.assert_export_fails(bad, "presentation")
        bad = page([complete_row()])
        bad["presentation"] = {**PROFILE, "columns": list(reversed(PROFILE["columns"]))}
        self.assert_export_fails(bad, "presentation")

    def test_rejects_missing_presentation_and_unsupported_aliases(self):
        valid = page([complete_row()])
        missing = dict(valid)
        del missing["presentation"]
        self.assert_export_fails(missing, "presentation")

        for alias in ("profile", "presentationProfile", "structuredProfile"):
            alias_only = dict(missing)
            alias_only[alias] = PROFILE
            with self.subTest(alias=alias):
                self.assert_export_fails(alias_only, "presentation")

    def test_rejects_missing_required_fields_and_non_scalar_values(self):
        row = complete_row()
        del row["supplier_name"]
        self.assert_export_fails(page([row]), "supplier_name")
        self.assert_export_fails(page([complete_row(item_name=["牛奶"])]), "scalar")
        self.assert_export_fails(page([complete_row(specification={"value": "250ml"})]), "scalar")

    def test_rejects_duplicate_page_payloads(self):
        duplicate = page([complete_row()])
        self.assert_export_fails([duplicate, duplicate], "duplicate")

    def test_rejects_existing_output_without_overwrite_and_overwrites_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "ledger.csv"
            output_path.write_text("existing", encoding="utf-8")
            result = self.run_export(page([complete_row()]), output_path)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(output_path.read_text(encoding="utf-8"), "existing")
            result = self.run_export(page([complete_row()]), output_path, "--overwrite")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotEqual(output_path.read_text(encoding="utf-8-sig"), "existing")

    def test_no_partial_output_on_validation_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "ledger.csv"
            result = self.run_export(page([complete_row(purchase_date="bad-date")]), output_path)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output_path.exists())
            self.assertEqual(list(Path(tmp).glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
