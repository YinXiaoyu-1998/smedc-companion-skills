"""Check the distribution links and the synthetic inspection walkthrough."""

import json
import re
import shlex
import unittest
from pathlib import Path, PurePosixPath


SKILL_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = SKILL_ROOT.parents[1]
TARGET_TYPES = {"store", "employee", "department"}


def json_payloads(text):
    return [
        json.loads(block)
        for block in re.findall(r"```json\n(.*?)\n```", text, re.DOTALL)
    ]


class InspectionSkillContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entrypoint = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        cls.reference = "references/examples.md"
        cls.examples = (SKILL_ROOT / cls.reference).read_text(encoding="utf-8")
        cls.payloads = json_payloads(cls.examples)
        cls.commands = [payload["command"] for payload in cls.payloads if "command" in payload]
        cls.template = next(command for command in cls.commands if command["action"] == "create_active")

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

    def test_target_examples_use_the_directory_and_create_contracts(self):
        template = self.template
        definition = template["definition"]
        store_id = definition["storeIds"][0]
        enterprise = {"enterpriseKey": template["enterpriseKey"]}
        self.assertEqual(definition["targetType"], "employee")
        self.assertNotIn("copyMode", self.examples)
        self.assertNotIn("copyMode", self.entrypoint)
        self.assertTrue(all("category" not in question for question in definition["questions"]))
        self.assertEqual(
            [payload["request"] for payload in self.payloads if "request" in payload],
            [
                {"action": "list_employees", **enterprise, "storeId": store_id, "status": "active"},
                {"action": "list_directory", **enterprise},
            ],
        )

        employees = next(page["employees"] for page in self.payloads if "employees" in page)
        employee_ids = {row["employeeUid"] for row in employees}
        self.assertEqual(len({row["name"] for row in employees}), 1)
        self.assertEqual(len(employee_ids), 2)
        self.assertEqual({row["status"] for row in employees}, {"active"})
        self.assertEqual({row["scope"]["storeId"] for row in employees}, {store_id})
        departments = next(page["departments"] for page in self.payloads if "departments" in page)
        self.assertEqual({row["status"] for row in departments}, {"active"})
        department_ids = {row["departmentId"] for row in departments}

        selectors = set()
        for command in self.commands:
            if command["action"] != "create":
                continue
            self.assertEqual(command["enterpriseKey"], enterprise["enterpriseKey"])
            self.assertEqual(command["storeId"], store_id)
            self.assertNotIn("name", command)
            selector = tuple(field for field in ("employeeUid", "departmentId") if field in command)
            if selector == ("employeeUid",):
                self.assertIn(command["employeeUid"], employee_ids)
            if selector == ("departmentId",):
                self.assertIn(command["departmentId"], department_ids)
            selectors.add(selector)
        self.assertEqual(selectors, {(), ("employeeUid",), ("departmentId",)})

        day = next(page["items"] for page in self.payloads if "items" in page)
        self.assertEqual(day[0]["targetType"], definition["targetType"])
        sheets = [item for item in day if item["kind"] == "sheet"]
        self.assertEqual({sheet["targetType"] for sheet in sheets}, {"employee"})
        self.assertEqual({sheet["targetId"] for sheet in sheets}, employee_ids)
        self.assertEqual({sheet["targetName"] for sheet in sheets}, {employees[0]["name"]})

    def test_example_upload_and_patch_match_the_store_version_and_template(self):
        template = self.template
        self.assertIn(f"({self.reference})", self.entrypoint)
        patch = next(command for command in self.commands if command.get("action") == "patch")
        upload = next(payload for payload in self.payloads if "filePath" in payload)
        day_page = next(payload for payload in self.payloads if "items" in payload)
        sheet = next(item for item in day_page["items"] if item.get("kind") == "sheet")
        self.assertEqual(upload["enterpriseKey"], template["enterpriseKey"])
        self.assertIn(upload["storeId"], template["definition"]["storeIds"])
        self.assertTrue(PurePosixPath(upload["filePath"]).is_absolute())
        self.assertNotIn("localPath", upload)
        self.assertNotIn("fileBase64", upload)
        self.assertEqual(patch["patches"][0]["sheetId"], sheet["sheetId"])
        self.assertEqual(patch["patches"][0]["templateVersionId"], sheet["templateVersionId"])

        components = {
            component["componentId"]: component
            for question in template["definition"]["questions"]
            for component in question["components"]
        }
        fill, attach = patch["patches"][0]["changes"]
        self.assertEqual(fill["op"], "fill")
        score = components[fill["componentId"]]
        self.assertEqual(score["kind"], "score")
        self.assertLessEqual(score["minTenths"], fill["value"], score["maxTenths"])
        self.assertEqual(attach["op"], "appendPhotos")
        self.assertEqual(components[attach["componentId"]]["kind"], "photo")


if __name__ == "__main__":
    unittest.main()
