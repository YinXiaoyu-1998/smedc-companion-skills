import re
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


class SkillContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.skill_text = (ROOT / "SKILL.md").read_text(encoding="utf-8")

    def test_skill_frontmatter_has_discovery_metadata(self) -> None:
        # openai.yaml is parsed separately by test_contract_fixtures.py.
        self.assertTrue(self.skill_text.startswith("---\n"))
        metadata = yaml.safe_load(self.skill_text.split("---", 2)[1])
        self.assertEqual(metadata["name"], "smedc-business-analysis")
        self.assertIsInstance(metadata["description"], str)
        self.assertTrue(metadata["description"].strip())

    def test_launcher_pin_and_prerequisite_repository(self) -> None:
        pins = re.findall(r"smedc-mcp-launcher@([^\s`\"']+)", self.skill_text)
        self.assertTrue(pins)
        self.assertEqual(set(pins), {"0.7.0"})
        self.assertIn("https://github.com/YinXiaoyu-1998/smedc-mcp-skill", self.skill_text)

    def test_skill_documents_required_smedc_mcp_tools(self) -> None:
        required_tools = [
            "smedc_get_current_user",
            "list_structured_datasets",
            "describe_structured_dataset_coverage",
            "download_structured_partitions",
            "query_structured_dataset",
            "get_partition_import_status",
        ]
        for tool_name in required_tools:
            with self.subTest(tool=tool_name):
                self.assertIn(tool_name, self.skill_text)

    def test_documented_python_entrypoints_exist(self) -> None:
        scripts = set(re.findall(r"python3 (scripts/[a-z_]+\.py)", self.skill_text))
        self.assertTrue(scripts)
        self.assertTrue({
            "scripts/run_business_report.py",
            "scripts/run_weekly_report.py",
            "scripts/run_monthly_report.py",
            "scripts/build_query_plan.py",
            "scripts/load_partition_extract.py",
            "scripts/assemble_query_bundle.py",
        }.issubset(scripts))
        for script in scripts:
            with self.subTest(script=script):
                self.assertTrue((ROOT / script).is_file())


if __name__ == "__main__":
    unittest.main()
