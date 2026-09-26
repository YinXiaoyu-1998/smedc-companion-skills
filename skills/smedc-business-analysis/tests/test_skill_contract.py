import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SkillContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.skill_text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        cls.openai_yaml_text = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")

    def test_skill_frontmatter_and_discovery_metadata_are_publish_ready(self) -> None:
        self.assertRegex(self.skill_text, r"(?s)^---\n.*name: smedc-business-analysis\n")
        self.assertRegex(self.skill_text, r"(?m)^description: Use when .+SMEDC.+structured business datasets")
        self.assertIn("**Required prerequisite:** Use `smedc-mcp`", self.skill_text)
        self.assertIn("$smedc-business-analysis", self.openai_yaml_text)
        self.assertIn("diagnosis", self.openai_yaml_text)

    def test_launcher_contract_is_explicit(self) -> None:
        self.assertIn("smedc-mcp-launcher@0.6.0", self.skill_text)
        self.assertIn("MCP entry is `smedc`", self.skill_text)
        self.assertNotIn("latest launcher version currently approved", self.skill_text)

    def test_missing_prerequisite_is_offered_but_never_installed_silently(self) -> None:
        self.assertIn("https://github.com/YinXiaoyu-1998/smedc-mcp-skill", self.skill_text)
        self.assertIn("If `smedc-mcp` is not installed", self.skill_text)
        self.assertIn("explicitly authorizes", self.skill_text)
        self.assertIn("Never install it silently", self.skill_text)
        self.assertIn("do not begin report data access", self.skill_text)
        self.assertIn("Never install or import `smedc-delivery-ledger` automatically", self.skill_text)

    def test_skill_names_only_the_required_smedc_mcp_tools(self) -> None:
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

        self.assertIn("only for manifest jobs whose `tool` is `query_structured_dataset`", self.skill_text)
        self.assertIn("Do not request, reveal, copy, or persist presigned URLs", self.skill_text)

    def test_skill_maps_supported_report_types_to_commands(self) -> None:
        expected_commands = {
            "diagnosis": "python3 scripts/run_business_report.py",
            "weekly": "python3 scripts/run_weekly_report.py",
            "monthly": "python3 scripts/run_monthly_report.py",
        }
        for report_type, command in expected_commands.items():
            with self.subTest(report_type=report_type):
                self.assertRegex(self.skill_text, rf"\b{report_type}\b")
                self.assertIn(command, self.skill_text)
        self.assertIn("python3 scripts/build_query_plan.py", self.skill_text)
        self.assertIn("python3 scripts/load_partition_extract.py", self.skill_text)
        self.assertIn("python3 scripts/assemble_query_bundle.py", self.skill_text)

    def test_skill_honors_explicit_report_periods(self) -> None:
        for phrase in [
            "Data coverage decides which modules can be shown",
            "it must never change the requested reporting period",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.skill_text)

    def test_skill_specifies_tool_order_pagination_and_response_filenames(self) -> None:
        ordered_markers = [
            "Use `smedc-mcp`",
            "Call `smedc_get_current_user`",
            "Call `list_structured_datasets`",
            "Call `describe_structured_dataset_coverage`",
            "run `python3 scripts/build_query_plan.py`",
            "call `download_structured_partitions`",
            "Call `query_structured_dataset`",
            "python3 scripts/load_partition_extract.py",
            "Run `python3 scripts/assemble_query_bundle.py`",
            "Run the report runner",
        ]
        positions = [self.skill_text.index(marker) for marker in ordered_markers]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("nextCursor", self.skill_text)
        self.assertIn("until the returned `nextCursor` is `null`", self.skill_text)
        self.assertIn("save an array of page envelopes", self.skill_text)
        self.assertIn("jobs[].outputFile", self.skill_text)
        self.assertIn("query-results/", self.skill_text)
        self.assertIn("registry_response.json", self.skill_text)
        self.assertIn("coverage_business.json", self.skill_text)
        self.assertIn("coverage_dishes.json", self.skill_text)
        self.assertIn("coverage_dish_catalog.json", self.skill_text)

    def test_skill_requires_partial_report_notices_provenance_and_cleanup(self) -> None:
        for phrase in [
            "partial or empty report",
            "Hide charts, tables, navigation items",
            "concise business language",
            "Never expose coverage tables",
            "QUERY_RESPONSE_ERROR",
            "QUERY_RESPONSE_MISSING",
            "Provenance",
            "technical provenance",
            "durable evidence",
            "Launcher partition CSVs",
            "cleanup-only",
            "finally",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.skill_text)

    def test_skill_excludes_removed_and_unsafe_workflows(self) -> None:
        self.assertNotIn("npm install -g", self.skill_text)
        self.assertIsNone(re.search(r"npm install .*smedc-mcp-launcher", self.skill_text))

        for required_boundary in [
            "Do not use direct HTTP",
            "Do not handle passwords or tokens",
            "Do not request, reveal, copy, or persist presigned URLs",
            "Do not ingest user-provided local CSV, XLSX, or workbook files",
            "Do not add monthly profit",
        ]:
            with self.subTest(required_boundary=required_boundary):
                self.assertIn(required_boundary, self.skill_text)

        forbidden_patterns = [
            r"monthly_profit",
            r"profit[- ]workbook workflow",
            r"signed[- ]download workflow",
            r"direct HTTP workflow",
            r"password workflow",
            r"token-handling workflow",
            r"local (?:CSV|XLSX|workbook) workflow",
        ]
        for pattern in forbidden_patterns:
            with self.subTest(pattern=pattern):
                self.assertIsNone(re.search(pattern, self.skill_text, flags=re.IGNORECASE))


if __name__ == "__main__":
    unittest.main()
