import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
REGISTRY_TOOL = ROOT / "scripts" / "registry_fixture_tool.py"
SCOPED_DATASETS = ("business", "dishes", "dish_catalog")


class ContractFixtureTests(unittest.TestCase):
    def load_json(self, relative_path: str) -> dict:
        return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))

    def test_openai_yaml_loads(self) -> None:
        data = yaml.safe_load((ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8"))

        self.assertEqual(data["interface"]["display_name"], "SMEDC Business Analysis")
        self.assertIn("$smedc-business-analysis", data["interface"]["default_prompt"])
        self.assertGreaterEqual(len(data["interface"]["short_description"]), 25)
        self.assertLessEqual(len(data["interface"]["short_description"]), 64)

    def test_config_has_no_tenant_default_company_or_store_buckets(self) -> None:
        config = self.load_json("config/business-analysis.json")

        self.assertNotIn("company", config)
        self.assertNotIn("storeNormalization", config)
        self.assertNotIn("storeBuckets", config)

    def test_config_required_for_values_reference_report_modules(self) -> None:
        config = self.load_json("config/business-analysis.json")
        report_modules = set(config["reportModules"])

        for dataset_name, dataset_config in config["datasets"].items():
            with self.subTest(dataset=dataset_name):
                required_for = set(dataset_config["requiredFor"])
                self.assertTrue(required_for)
                self.assertLessEqual(required_for, report_modules)

    def test_config_fields_exist_in_registry_fixture(self) -> None:
        config = self.load_json("config/business-analysis.json")
        registry = self.load_json("tests/fixtures/registry_response.json")
        registry_fields = {
            dataset["dataset"]: {field["canonicalName"] for field in dataset["fields"]}
            for dataset in registry["datasets"]
        }

        self.assertEqual(set(config["datasets"]), {"business", "dishes", "dish_catalog"})
        self.assertEqual(set(registry_fields), {"business", "dishes", "dish_catalog"})

        for dataset_name, fields in config["fields"].items():
            with self.subTest(dataset=dataset_name):
                self.assertLessEqual(set(fields.values()), registry_fields[dataset_name])

    def test_registry_fixture_matches_authoritative_current_registries(self) -> None:
        service_repo = os.environ.get("SME_DATA_CENTER_REPO")
        if not service_repo:
            self.skipTest("set SME_DATA_CENTER_REPO to run exact cross-repo registry parity")
        completed = subprocess.run(
            [sys.executable, str(REGISTRY_TOOL), "check", "--service-repo", service_repo],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)

    def test_registry_fixture_tool_documents_portable_service_repo_selection(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(REGISTRY_TOOL), "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--service-repo", completed.stdout)
        self.assertIn("SME_DATA_CENTER_REPO", completed.stdout)

    def test_registry_fixture_is_full_for_skill_datasets(self) -> None:
        registry = self.load_json("tests/fixtures/registry_response.json")

        self.assertEqual(tuple(dataset["dataset"] for dataset in registry["datasets"]), SCOPED_DATASETS)
        self.assertEqual(
            {dataset["dataset"]: len(dataset["fields"]) for dataset in registry["datasets"]},
            {"business": 152, "dishes": 51, "dish_catalog": 14},
        )

    def test_coverage_fixtures_use_dataset_specific_source_shape(self) -> None:
        for file_name in ["coverage_business.json", "coverage_dishes.json"]:
            with self.subTest(fixture=file_name):
                coverage = json.loads((FIXTURES / file_name).read_text(encoding="utf-8"))
                self.assertEqual(coverage["accessMode"], "partition_extract")
                for enterprise in coverage["enterprises"]:
                    self.assertIn("enterpriseName", enterprise)
                    self.assertIn("startDate", enterprise)
                    self.assertIn("endDate", enterprise)
                    self.assertIn("partitionCount", enterprise)
                    self.assertIn("stores", enterprise)

        catalog_coverage = self.load_json("tests/fixtures/coverage_dish_catalog.json")
        self.assertEqual(catalog_coverage["dataset"], "dish_catalog")
        self.assertEqual(catalog_coverage["metadataPolicy"], "current")
        self.assertGreater(catalog_coverage["rowCount"], 0)
        self.assertTrue(catalog_coverage["lastUpdatedAt"].endswith("Z"))
        self.assertNotIn("sources", catalog_coverage)


if __name__ == "__main__":
    unittest.main()
