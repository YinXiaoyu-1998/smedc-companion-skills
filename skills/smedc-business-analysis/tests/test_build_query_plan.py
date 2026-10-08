import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
SCRIPT = ROOT / "scripts" / "build_query_plan.py"
ORG_ERROR = "SMEDC account organization"


class BuildQueryPlanTests(unittest.TestCase):
    def run_plan(
        self,
        report_type: str = "weekly",
        *,
        empty_dish_catalog: bool = False,
        current_user: Path | None = FIXTURES / "current_user_response.json",
        store_name_contains: list[str] | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], dict]:
        completed, output = self.run_plan_command(
            report_type=report_type,
            empty_dish_catalog=empty_dish_catalog,
            current_user=current_user,
            store_name_contains=store_name_contains,
        )
        return completed, json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}

    def run_plan_command(
        self,
        report_type: str = "weekly",
        *,
        empty_dish_catalog: bool = False,
        current_user: Path | None = FIXTURES / "current_user_response.json",
        store_name_contains: list[str] | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        run_dir = Path(temporary.name)
        coverage_dir = run_dir / "coverage"
        coverage_dir.mkdir()
        for dataset in ("business", "dishes", "dish_catalog"):
            (coverage_dir / f"coverage_{dataset}.json").write_bytes(
                (FIXTURES / f"coverage_{dataset}.json").read_bytes()
            )
        if empty_dish_catalog:
            (coverage_dir / "coverage_dish_catalog.json").write_text(
                json.dumps({"dataset": "dish_catalog", "metadataPolicy": "snapshot", "sources": []}),
                encoding="utf-8",
            )
        output = run_dir / "manifest.json"
        command = [
            sys.executable,
            str(SCRIPT),
            "--report-type",
            report_type,
            "--enterprise-name",
            "示例企业",
            "--current-start",
            "2026-07-25",
            "--current-end",
            "2026-07-31",
            "--previous-start",
            "2026-07-18",
            "--previous-end",
            "2026-07-24",
            "--yoy-start",
            "2025-07-26",
            "--yoy-end",
            "2025-08-01",
            "--registry-response",
            str(FIXTURES / "registry_response.json"),
            "--coverage-dir",
            str(coverage_dir),
            "--output",
            str(output),
        ]
        if current_user is not None:
            command[6:6] = ["--current-user", str(current_user)]
        if store_name_contains is not None:
            command.extend(["--store-name-contains", *store_name_contains])
        completed = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        return completed, output

    def test_weekly_plan_downloads_only_contiguous_partition_windows(self) -> None:
        completed, manifest = self.run_plan()
        self.assertEqual(completed.returncode, 0, completed.stderr)

        extracts = manifest["extracts"]
        self.assertEqual([entry["input"]["dataset"] for entry in extracts], ["business", "dishes", "dishes"])
        self.assertTrue(all(entry["tool"] == "download_structured_partitions" for entry in extracts))
        self.assertTrue(all(entry["input"]["enterpriseName"] == "示例企业" for entry in extracts))
        self.assertEqual(
            [(entry["input"]["startDate"], entry["input"]["endDate"]) for entry in extracts if entry["input"]["dataset"] == "business"],
            [("20240803", "20260731")],
        )

        self.assertEqual(manifest["report"]["trendWindows"], {
            "current": {"start": "2025-08-02", "end": "2026-07-31"},
            "priorYear": {"start": "2024-08-03", "end": "2025-08-01"},
        })
        self.assertIn("business_52_week_store_trend", {job["id"] for job in manifest["jobs"]})
        self.assertIn("business_52_week_prior_year_store_trend", {job["id"] for job in manifest["jobs"]})

        partition_jobs = [job for job in manifest["jobs"] if job["input"]["dataset"] in {"business", "dishes"}]
        self.assertTrue(partition_jobs)
        self.assertTrue(all(job["tool"] == "local_partition_aggregate" for job in partition_jobs))
        self.assertEqual(
            {job["input"]["dataset"] for job in manifest["jobs"] if job["tool"] == "query_structured_dataset"},
            {"dish_catalog"},
        )
        self.assertEqual(manifest["metadata"]["organization_name"], "示例餐饮管理有限公司")

    def test_diagnosis_plan_needs_one_business_extract_and_no_row_query(self) -> None:
        completed, manifest = self.run_plan("diagnosis")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(len(manifest["extracts"]), 1)
        self.assertEqual(manifest["extracts"][0]["input"]["dataset"], "business")
        self.assertTrue(all(job["tool"] == "local_partition_aggregate" for job in manifest["jobs"]))

    def test_store_name_filter_is_preserved_for_every_report_type(self) -> None:
        for report_type in ("diagnosis", "weekly", "monthly"):
            with self.subTest(report_type=report_type):
                completed, manifest = self.run_plan(report_type, store_name_contains=[" 示例一 ", "示例三", "示例一"])
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(manifest["report"]["storeNameContains"], ["示例一", "示例三"])
                self.assertTrue(all("storeIds" not in item["input"] for item in manifest["extracts"]))

    def test_blank_store_name_fragment_fails_before_writing_manifest(self) -> None:
        completed, output = self.run_plan_command(store_name_contains=["   "])
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("store-name-contains values must be non-blank", completed.stderr)
        self.assertFalse(output.exists())

    def test_weekly_plan_omits_catalog_job_when_no_snapshot_is_readable(self) -> None:
        completed, manifest = self.run_plan(empty_dish_catalog=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertFalse(any(job["input"]["dataset"] == "dish_catalog" for job in manifest["jobs"]))
        self.assertIn(
            {
                "code": "COVERAGE_WINDOW_MISSING",
                "dataset": "dish_catalog",
                "window": "current",
                "module": "stallAttribution",
            },
            manifest["notices"],
        )

    def test_missing_current_user_flag_fails_before_writing_manifest(self) -> None:
        completed, output = self.run_plan_command(current_user=None)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(ORG_ERROR, completed.stderr)
        self.assertFalse(output.exists())

    def test_missing_current_user_file_fails_before_writing_manifest(self) -> None:
        completed, output = self.run_plan_command(current_user=Path("/tmp/smedc-missing-current-user.json"))
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(ORG_ERROR, completed.stderr)
        self.assertFalse(output.exists())

    def test_malformed_current_user_fails_before_writing_manifest(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        current_user = Path(temporary.name) / "current_user.json"
        current_user.write_text("{not-json", encoding="utf-8")
        completed, output = self.run_plan_command(current_user=current_user)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(ORG_ERROR, completed.stderr)
        self.assertFalse(output.exists())

    def test_blank_or_non_string_current_user_organization_fails_before_writing_manifest(self) -> None:
        invalid_users = [
            {"user": {"organizationName": ""}},
            {"user": {"organizationName": "   "}},
            {"user": {"organizationName": 123}},
        ]
        for payload in invalid_users:
            with self.subTest(payload=payload):
                temporary = tempfile.TemporaryDirectory()
                self.addCleanup(temporary.cleanup)
                current_user = Path(temporary.name) / "current_user.json"
                current_user.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                completed, output = self.run_plan_command(current_user=current_user)
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn(ORG_ERROR, completed.stderr)
                self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
