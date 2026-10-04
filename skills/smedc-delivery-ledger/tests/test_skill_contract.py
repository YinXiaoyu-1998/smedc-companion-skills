"""Check distributed archive guidance and removal of obsolete runtime entrypoints."""

import re
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = SKILL_ROOT.parents[1]


class LedgerSkillContractTests(unittest.TestCase):
    def test_local_generation_runtime_is_removed(self):
        self.assertFalse((SKILL_ROOT / "requirements.txt").exists())
        self.assertFalse((SKILL_ROOT / "config").exists())
        runtime = [path for path in SKILL_ROOT.rglob("*.py")
                   if "tests" not in path.relative_to(SKILL_ROOT).parts]
        self.assertEqual(runtime, [])
        for name in ("export_ledger.py", "export_ledger_csv.py",
                     "test_export_ledger_xlsx.py", "test_export_ledger_csv.py",
                     "ledger-pages.json"):
            self.assertEqual(list(SKILL_ROOT.rglob(name)), [])

    def test_published_workflow_uses_verified_launcher_pin(self):
        documents = [SKILL_ROOT / "SKILL.md", SKILL_ROOT / "agents/openai.yaml",
                     REPOSITORY_ROOT / "README.md", REPOSITORY_ROOT / "README.zh.md"]
        for path in documents:
            with self.subTest(path=path):
                text = path.read_text(encoding="utf-8")
                pins = re.findall(r"smedc-mcp-launcher@([^\s`]+)", text)
                self.assertTrue(set(pins) <= {"0.7.0"})
                self.assertNotIn("python3 scripts/export_ledger", text)
        text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("smedc-mcp-launcher@0.7.0", text)
        self.assertIn("independently verified", text)
        self.assertNotIn("once published", text)

    def test_interface_invokes_archive_skill_without_retired_exports(self):
        text = (SKILL_ROOT / "agents/openai.yaml").read_text(encoding="utf-8")
        self.assertIn("$smedc-delivery-ledger", text)
        self.assertIn("server daily PDF archives", text)
        self.assertNotRegex(text, r"XLSX|CSV|monthly|text phone")

    def test_upload_completion_waits_for_service_daily_generation(self):
        text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("refresh_ledger_pdfs", text)
        self.assertIn("Do not submit a generation request", text)
        self.assertIn("03:00 Asia/Shanghai", text)
        self.assertIn("Employee agents, including admins, cannot", text)
        self.assertIn("upload completion does not mean PDF completion", text)
        self.assertIn("skipping healthy PDFs", text)
        self.assertIn("Do not claim an old PDF contains new receipts/photos", text)


if __name__ == "__main__":
    unittest.main()
