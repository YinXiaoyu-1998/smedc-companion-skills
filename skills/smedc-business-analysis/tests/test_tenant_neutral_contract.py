import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
ORG_NAME = "示例餐饮管理有限公司"
ORG_ERROR = "SMEDC account organization"
REMOVED_SEED_PATTERNS = [
    "mai" + "jia",
    "麦" + "家",
    "Mai" + "jia",
    "麦" + "家小馆",
    "荣京" + "道店",
    "龙玥" + "城店",
    "经海" + "路店",
    "国粹" + "苑店",
    "上海" + "沙龙店",
    "文化" + "园店",
    "苏州" + "街店",
    "常营" + "店",
    "通州" + "保利店",
]


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )


def h1_texts(html: str) -> list[str]:
    return [re.sub(r"<[^>]+>", "", value).strip() for value in re.findall(r"<h1[^>]*>(.*?)</h1>", html, re.DOTALL)]


class TenantNeutralContractTests(unittest.TestCase):
    def render_report(self, runner: str, fixture_name: str) -> str:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        output_dir = Path(temporary.name)
        report_path = output_dir / "report.html"
        completed = run_script(
            f"scripts/{runner}",
            "--bundle",
            str(FIXTURES / fixture_name),
            "--current-user",
            str(FIXTURES / "current_user_response.json"),
            "--output-dir",
            str(output_dir / "facts"),
            "--report",
            str(report_path),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return report_path.read_text(encoding="utf-8")

    def test_current_user_fixture_organization_name_reaches_all_report_h1_titles(self) -> None:
        cases = [
            ("run_business_report.py", "diagnosis_bundle.json"),
            ("run_weekly_report.py", "weekly_bundle.json"),
            ("run_monthly_report.py", "monthly_bundle.json"),
        ]
        for runner, fixture_name in cases:
            with self.subTest(runner=runner):
                html = self.render_report(runner, fixture_name)
                headings = h1_texts(html)
                self.assertTrue(headings, html[:500])
                self.assertTrue(all(ORG_NAME in heading for heading in headings), headings)

    def test_blank_non_string_or_missing_organization_name_fails_closed(self) -> None:
        invalid_users = [
            {"user": {"displayName": "测试员工", "email": "qa@example.invalid", "organizationName": ""}},
            {"user": {"displayName": "测试员工", "email": "qa@example.invalid", "organizationName": "   "}},
            {"user": {"displayName": "测试员工", "email": "qa@example.invalid", "organizationName": 123}},
            {"user": {"displayName": "测试员工", "email": "qa@example.invalid"}},
        ]
        for payload in invalid_users:
            with self.subTest(payload=payload):
                temporary = tempfile.TemporaryDirectory()
                self.addCleanup(temporary.cleanup)
                output_dir = Path(temporary.name)
                current_user = output_dir / "current_user.json"
                current_user.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                report_path = output_dir / "report.html"
                completed = run_script(
                    "scripts/run_weekly_report.py",
                    "--bundle",
                    str(FIXTURES / "weekly_bundle.json"),
                    "--current-user",
                    str(current_user),
                    "--output-dir",
                    str(output_dir / "facts"),
                    "--report",
                    str(report_path),
                )
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn(ORG_ERROR, completed.stderr)
                self.assertFalse(report_path.exists())

    def test_no_fallback_infers_company_from_user_or_business_data(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        output_dir = Path(temporary.name)
        current_user = output_dir / "current_user.json"
        current_user.write_text(
            json.dumps(
                {
                    "user": {
                        "displayName": "备选显示名",
                        "email": "fallback-company@example.invalid",
                        "role": "employee",
                        "clearance": 3,
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        completed = run_script(
            "scripts/run_business_report.py",
            "--bundle",
            str(FIXTURES / "diagnosis_bundle.json"),
            "--current-user",
            str(current_user),
            "--output-dir",
            str(output_dir / "facts"),
            "--report",
            str(output_dir / "report.html"),
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(ORG_ERROR, completed.stderr)
        self.assertNotIn("备选显示名", completed.stdout + completed.stderr)
        self.assertNotIn("fallback-company", completed.stdout + completed.stderr)

    def test_distributed_content_has_no_removed_seed_names(self) -> None:
        for path in sorted(ROOT.rglob("*")):
            if (
                path.is_dir()
                or "tests" in path.relative_to(ROOT).parts
                or "__pycache__" in path.parts
                or any(part.startswith(".") for part in path.relative_to(ROOT).parts)
            ):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for pattern in REMOVED_SEED_PATTERNS:
                with self.subTest(path=path.relative_to(ROOT), pattern=pattern):
                    self.assertNotIn(pattern, text)


if __name__ == "__main__":
    unittest.main()
