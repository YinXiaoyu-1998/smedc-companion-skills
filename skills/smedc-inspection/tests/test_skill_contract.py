"""Check the distribution links and the synthetic inspection walkthrough."""

import json
import re
import shlex
import unittest
import uuid
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
        cls.templates = [command for command in cls.commands if command.get("action") == "create_active"]
        cls.creates = [command for command in cls.commands if command.get("action") == "create"]

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

    def test_guidance_describes_targets_without_copy_mode_or_free_form_names(self):
        self.assertNotIn("copyMode", self.entrypoint)
        self.assertNotIn("multiple-copy", self.entrypoint)
        self.assertIn(self.reference, self.entrypoint)
        for target_type in TARGET_TYPES:
            self.assertIn(f"`{target_type}`", self.entrypoint)
        self.assertIn("`employeeUid`", self.entrypoint)
        self.assertIn("`departmentId`", self.entrypoint)
        self.assertIn("free-form", self.entrypoint)
        self.assertIn("template, store, inspection date, and target", self.entrypoint)
        for snapshot in ("`targetType`", "`targetId`", "`targetName`"):
            self.assertIn(snapshot, self.entrypoint)

    def test_guidance_covers_same_names_authorization_replay_and_both_entrypoints(self):
        text = self.entrypoint.lower()
        for phrase in (
            "same-name",
            "directory read access",
            "unauthorized",
            "recheck",
            "snapshot",
            "partial",
            "retired",
            "requestid",
            "idempotency",
            "replay",
            "web",
            "mcp",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_example_templates_use_a_target_type_instead_of_copy_mode(self):
        self.assertTrue(self.templates)
        self.assertNotIn("copyMode", self.examples)
        for command in self.templates:
            definition = command["definition"]
            self.assertIn("targetType", definition)
            self.assertNotIn("copyMode", definition)
            self.assertIn(definition["targetType"], TARGET_TYPES)
            self.assertTrue(definition["storeIds"])
            self.assertTrue(all("category" not in question for question in definition["questions"]))

    def test_example_candidate_queries_use_the_active_store_and_enterprise_scope(self):
        template = self.templates[0]
        employee_requests = [
            payload["request"]
            for payload in self.payloads
            if payload.get("request", {}).get("action") == "list_employees"
        ]
        self.assertEqual(len(employee_requests), 1)
        employee_request = employee_requests[0]
        self.assertEqual(employee_request["enterpriseKey"], template["enterpriseKey"])
        self.assertEqual(employee_request["status"], "active")
        self.assertIn(employee_request["storeId"], template["definition"]["storeIds"])
        self.assertNotIn("management", employee_request)

        directory_requests = [
            payload["request"]
            for payload in self.payloads
            if payload.get("request", {}).get("action") == "list_directory"
        ]
        self.assertEqual(len(directory_requests), 1)
        self.assertEqual(directory_requests[0]["enterpriseKey"], template["enterpriseKey"])
        self.assertNotIn("management", directory_requests[0])

    def test_example_candidates_show_same_names_and_active_departments(self):
        employee_pages = [payload for payload in self.payloads if "employees" in payload]
        self.assertEqual(len(employee_pages), 1)
        employee_page = employee_pages[0]
        self.assertEqual(employee_page["access"], "all")
        self.assertIsNone(employee_page["nextCursor"])
        employees = employee_page["employees"]
        self.assertGreaterEqual(len(employees), 2)
        self.assertEqual(len({employee["name"] for employee in employees}), 1)
        self.assertEqual(len({employee["employeeUid"] for employee in employees}), len(employees))
        self.assertTrue(all(employee["status"] == "active" for employee in employees))
        self.assertTrue(
            all(
                employee["scope"]["ownership"] == "store"
                and employee["scope"]["storeId"] == self.templates[0]["definition"]["storeIds"][0]
                for employee in employees
            )
        )

        department_pages = [payload for payload in self.payloads if "departments" in payload]
        self.assertEqual(len(department_pages), 1)
        departments = department_pages[0]["departments"]
        self.assertTrue(any(department["status"] == "active" for department in departments))
        self.assertTrue(any(department["status"] == "retired" for department in departments))

    def test_example_creates_cover_store_employee_and_department_without_a_name(self):
        self.assertEqual(len(self.creates), 3)
        template = self.templates[0]
        store_id = template["definition"]["storeIds"][0]
        employee_ids = {
            employee["employeeUid"]
            for payload in self.payloads
            if "employees" in payload
            for employee in payload["employees"]
        }
        active_department_ids = {
            department["departmentId"]
            for payload in self.payloads
            if "departments" in payload
            for department in payload["departments"]
            if department["status"] == "active"
        }
        shapes = set()
        for command in self.creates:
            self.assertNotIn("name", command)
            self.assertEqual(command["enterpriseKey"], template["enterpriseKey"])
            self.assertEqual(command["storeId"], store_id)
            has_employee = "employeeUid" in command
            has_department = "departmentId" in command
            self.assertFalse(has_employee and has_department)
            if has_employee:
                self.assertIn(command["employeeUid"], employee_ids)
                shapes.add("employee")
            elif has_department:
                self.assertIn(command["departmentId"], active_department_ids)
                shapes.add("department")
            else:
                shapes.add("store")
        self.assertEqual(shapes, TARGET_TYPES)

    def test_example_day_summary_returns_target_snapshots_for_same_name_people(self):
        day_pages = [payload for payload in self.payloads if isinstance(payload.get("items"), list)]
        self.assertEqual(len(day_pages), 1)
        template_entries = [
            item for item in day_pages[0]["items"] if item.get("kind") == "template"
        ]
        self.assertEqual(template_entries[0]["targetType"], self.templates[0]["definition"]["targetType"])
        sheets = [item for item in day_pages[0]["items"] if item.get("kind") == "sheet"]
        self.assertGreaterEqual(len(sheets), 2)
        for sheet in sheets:
            self.assertIn(sheet["targetType"], TARGET_TYPES)
            uuid.UUID(sheet["targetId"])
            self.assertTrue(sheet["targetName"].strip())
        same_name_targets = {
            (sheet["targetName"], sheet["targetId"]) for sheet in sheets
        }
        self.assertEqual(len({name for name, _ in same_name_targets}), 1)
        self.assertEqual(len({target_id for _, target_id in same_name_targets}), len(sheets))

    def test_example_upload_and_patch_match_the_store_version_and_template(self):
        template = self.templates[0]
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
