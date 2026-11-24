"""Check the distribution links and the synthetic inspection walkthrough."""

import json
import re
import shlex
import unittest
from pathlib import Path, PurePosixPath


SKILL_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = SKILL_ROOT.parents[1]


class InspectionSkillContractTests(unittest.TestCase):
    def test_both_readmes_link_and_install_the_inspection_companion(self):
        expected_copy = [
            "cp",
            "-R",
            "/tmp/smedc-companion-skills/skills/smedc-inspection",
            "~/.agents/skills/smedc-inspection",
        ]
        for name in ("README.md", "README.zh.md"):
            with self.subTest(readme=name):
                content = (REPOSITORY_ROOT / name).read_text(encoding="utf-8")
                self.assertIn("(skills/smedc-inspection/SKILL.md)", content)
                copies = [
                    shlex.split(line) for line in content.splitlines() if line.startswith("cp ")
                ]
                self.assertIn(expected_copy, copies)

    def test_example_upload_and_patch_match_the_store_and_template(self):
        entrypoint = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        reference = "references/examples.md"
        self.assertIn(f"({reference})", entrypoint)
        text = (SKILL_ROOT / reference).read_text(encoding="utf-8")
        payloads = [
            json.loads(block)
            for block in re.findall(r"```json\n(.*?)\n```", text, re.DOTALL)
        ]
        draft = next(p["command"] for p in payloads if p.get("command", {}).get("action") == "create_active")
        patch = next(p["command"] for p in payloads if p.get("command", {}).get("action") == "patch")
        upload = next(p for p in payloads if "command" not in p)
        self.assertEqual(upload["enterpriseKey"], draft["enterpriseKey"])
        self.assertIn(upload["storeId"], draft["definition"]["storeIds"])
        self.assertTrue(PurePosixPath(upload["filePath"]).is_absolute())
        self.assertNotIn("localPath", upload)
        self.assertNotIn("fileBase64", upload)

        components = {
            component["componentId"]: component
            for question in draft["definition"]["questions"]
            for component in question["components"]
        }
        fill, attach = patch["patches"][0]["changes"]
        self.assertEqual(fill["op"], "fill")
        score = components[fill["componentId"]]
        self.assertEqual(score["kind"], "score")
        self.assertLessEqual(score["minTenths"], fill["value"], score["maxTenths"])
        self.assertEqual(attach["op"], "appendPhotos")
        self.assertEqual(components[attach["componentId"]]["kind"], "photo")
