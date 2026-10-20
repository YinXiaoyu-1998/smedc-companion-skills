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

    def test_launcher_pin_is_owned_by_core_skill(self) -> None:
        pins = re.findall(r"smedc-mcp-launcher@([^\s`\"']+)", self.skill_text)
        self.assertEqual(pins, [])
        self.assertIn("approved exact pin from the current core Skill", self.skill_text)
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

    def test_name_association_and_cost_card_analysis_stay_local(self) -> None:
        self.assertIn("references/dish_name_association.zh.md", self.skill_text)
        association = (ROOT / "references/dish_name_association.zh.md").read_text(encoding="utf-8")
        self.assertLess(association.index("matched_product_name"), association.index("product_name`（菜品名称）"))
        for contract in ["多个候选", "不把两列同时连接", "不在导入时重写名称"]:
            self.assertIn(contract, association)
        guide = (ROOT / "references/cost_cards.zh.md").read_text(encoding="utf-8")
        for contract in ["download_cost_cards", "38", "finally", "Decimal", "sourceDocumentId",
                         "importBatchId", "revision", "不混合两份", "例外", "单位", "候选"]:
            with self.subTest(contract=contract):
                self.assertIn(contract, guide)
        self.assertIn("现有报表 runner", guide)
        self.assertIn("不生成唯一最终配方", guide)

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
