"""Contract checks for the distributed SMEDC inspection companion skill."""

import json
import re
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = SKILL_ROOT.parents[1]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class InspectionSkillContractTests(unittest.TestCase):
    def test_skill_metadata_and_readme_discovery_are_complete(self):
        text = read(SKILL_ROOT / "SKILL.md")
        frontmatter = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
        self.assertIsNotNone(frontmatter)
        self.assertIn("name: smedc-inspection", frontmatter.group(1))
        self.assertIn("企业智脑（SMEDC）", frontmatter.group(1))
        self.assertIn("Use for", frontmatter.group(1))

        interface = read(SKILL_ROOT / "agents/openai.yaml")
        self.assertIn("$smedc-inspection", interface)
        self.assertIn("all four public inspection tools", interface)

        link = "(skills/smedc-inspection/SKILL.md)"
        for readme in ("README.md", "README.zh.md"):
            with self.subTest(readme=readme):
                content = read(REPOSITORY_ROOT / readme)
                self.assertIn(link, content)
                self.assertIn("smedc-inspection ~/.agents/skills/smedc-inspection", content)

    def test_examples_keep_command_wrappers_and_flat_photo_upload(self):
        text = read(SKILL_ROOT / "SKILL.md")
        examples = [
            json.loads(block)
            for block in re.findall(r"```json\n(.*?)\n```", text, re.DOTALL)
        ]
        self.assertEqual(len(examples), 3)

        create = next(
            item for item in examples if item.get("command", {}).get("action") == "create"
        )
        self.assertEqual(
            set(create["command"]),
            {"action", "templateId", "enterpriseKey", "definition"},
        )
        self.assertIn("questions", create["command"]["definition"])

        patch = next(
            item for item in examples if item.get("command", {}).get("action") == "patch"
        )
        self.assertEqual(set(patch["command"]), {"action", "patches"})
        sheet = patch["command"]["patches"][0]
        self.assertEqual(
            set(sheet),
            {"sheetId", "templateVersionId", "requestId", "changes"},
        )
        self.assertEqual(
            {change["op"] for change in sheet["changes"]},
            {"fill", "appendPhotos"},
        )

        upload = next(item for item in examples if "command" not in item)
        self.assertEqual(
            set(upload),
            {
                "enterpriseKey",
                "storeId",
                "inspectionDate",
                "requestId",
                "mediaType",
                "filePath",
            },
        )
        self.assertNotIn("fileBase64", text)
        self.assertIn("localPath", text)
        self.assertIn("never upload content", text)

    def test_candidate_and_human_activation_boundaries_remain_explicit(self):
        text = read(SKILL_ROOT / "SKILL.md")
        for marker in (
            "source candidate",
            "not a launch claim",
            "all four public tools",
            "approved exact",
            "launcher pin",
            "explicit user decision",
            "official questionnaire rows",
            "red lines",
            "conditional evidence exceptions",
            "pure synthetic example",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
