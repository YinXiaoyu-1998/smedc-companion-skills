"""Regression tests for the additive WorkBuddy host adapter.

These tests are host-neutral: no browser CLI, mail server, MCP server or
network access is required. They prove (a) the Codex sources and repository
CI assertions are untouched, and (b) the new local components behave as
documented.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import re
import shlex
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKBUDDY = ROOT / "workbuddy"
SCRIPTS = WORKBUDDY / "scripts"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


wb_state = load_module("wb_state", SCRIPTS / "wb_state.py")
wb_mail = load_module("wb_mail", SCRIPTS / "wb_mail.py")
wb_schedule = load_module("wb_schedule", SCRIPTS / "wb_schedule.py")
wb_overlays = load_module("wb_overlays", WORKBUDDY / "overlays" / "build_overlays.py")


class RepositoryInvariantTests(unittest.TestCase):
    def test_codex_source_skill_files_are_not_overlays(self) -> None:
        for path in (ROOT / "skills").glob("*/SKILL.md"):
            with self.subTest(path=path.relative_to(ROOT)):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("WorkBuddy overlay", text)
                self.assertTrue(text.startswith("---"))

    def test_no_launcher_pin_in_distributed_documents(self) -> None:
        documents = list((ROOT / "skills").rglob("*.md"))
        documents += list((ROOT / "skills").rglob("*.yaml"))
        documents += [ROOT / "README.md", ROOT / "README.zh.md"]
        pattern = r"smedc-mcp-launcher@[^\s`]+|launcher[/\\]+versions[/\\]+\d"
        for path in documents:
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertNotRegex(path.read_text(encoding="utf-8"), pattern)

    def test_readme_install_assertions_still_hold(self) -> None:
        source = "https://github.com/YinXiaoyu-1998/smedc-mcp-skill.git"
        destination = "~/.agents/skills/smedc-mcp"
        for name in ("README.md", "README.zh.md"):
            with self.subTest(readme=name):
                text = (ROOT / name).read_text(encoding="utf-8")
                commands = [shlex.split(line) for line in text.splitlines()
                            if line.startswith(("git clone ", "cp "))]
                clones = [args for args in commands if args[:3] == ["git", "clone", source]]
                self.assertEqual(len(clones), 1)
                self.assertEqual(len(clones[0]), 4)
                checkout = clones[0][3].rstrip("/")
                self.assertNotEqual(checkout, destination)
                self.assertIn(["cp", "-R", f"{checkout}/skills/smedc-mcp", destination],
                              commands)

    def test_hard_limits_are_documented(self) -> None:
        text = (WORKBUDDY / "HOST_MAP.md").read_text(encoding="utf-8")
        for marker in ("Not substitutable", "allowedSender", "Goal lifecycle",
                       "native-adapters.js", "blocked"):
            self.assertIn(marker, text)


class StateMachineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "runs" / "run-001"
        self.root.mkdir(parents=True)
        self.evidence = self.root / "proof.json"
        self.evidence.write_text('{"verified": true}', encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def init_state(self):
        args = wb_state.build_parser().parse_args([
            "init", "--root", str(self.root),
            "--workflow", "meituan-daily-ingestion",
            "--run-id", "run-001", "--binding-hash", "a" * 64,
            "--window", json.dumps({"startDate": "2026-11-06", "endDate": "2026-11-06"}),
        ])
        with contextlib.redirect_stdout(io.StringIO()):
            wb_state.cmd_init(args)
        return wb_state.load(self.root)

    def test_init_load_and_hash_chain(self) -> None:
        state = self.init_state()
        self.assertEqual(state["runId"], "run-001")
        self.assertEqual(state["revision"], 1)
        self.assertEqual(state["status"], "open")
        self.assertEqual(state["stateHash"], wb_state.state_hash(state))
        raw = (self.root / "state.json").read_text(encoding="utf-8")
        tampered = json.loads(raw)
        tampered["completed"]["fake"] = {"scopeHash": "x", "evidence": []}
        (self.root / "state.json").write_text(json.dumps(tampered), encoding="utf-8")
        with self.assertRaises(ValueError):
            wb_state.load(self.root)

    def test_progress_evidence_and_verify(self) -> None:
        self.init_state()
        parser = wb_state.build_parser()
        save_args = parser.parse_args([
            "save-progress", "--root", str(self.root),
            "--task-id", "business", "--scope-hash", "b" * 64,
            "--evidence", str(self.evidence),
        ])
        with contextlib.redirect_stdout(io.StringIO()):
            wb_state.cmd_save_progress(save_args)
        state = wb_state.load(self.root)
        entry = state["completed"]["business"]
        self.assertEqual(entry["evidence"][0]["sha256"],
                         hashlib.sha256(self.evidence.read_bytes()).hexdigest())
        verify_args = parser.parse_args(["verify", "--root", str(self.root)])
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(wb_state.cmd_verify(verify_args), 0)
        self.assertTrue(json.loads(out.getvalue())["ok"])
        self.evidence.write_text("changed", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()) as out2:
            self.assertEqual(wb_state.cmd_verify(verify_args), 1)
        self.assertEqual(len(json.loads(out2.getvalue())["brokenEvidence"]), 1)

    def test_resume_matches_run_id_and_close_is_final(self) -> None:
        self.init_state()
        parser = wb_state.build_parser()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(wb_state.cmd_resume(parser.parse_args(
                ["resume", "--root", str(self.root), "--run-id", "run-001"])), 0)
        with self.assertRaises(ValueError):
            wb_state.cmd_resume(parser.parse_args(
                ["resume", "--root", str(self.root), "--run-id", "other"]))
        with contextlib.redirect_stdout(io.StringIO()):
            wb_state.cmd_close(parser.parse_args(
                ["close", "--root", str(self.root), "--outcome", "partial"]))
        with self.assertRaises(ValueError):
            wb_state.cmd_resume(parser.parse_args(["resume", "--root", str(self.root)]))
        self.assertEqual(wb_state.load(self.root)["outcome"], "partial")

    def test_shared_root_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            wb_state.resolve_root(str(Path.home()))
        with self.assertRaises(ValueError):
            wb_state.resolve_root("relative/path")


class MailDegradationTests(unittest.TestCase):
    def test_plan_is_blocked_and_delivers_locally(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "weekly-report.html"
            artifact.write_text("<html>report</html>", encoding="utf-8")
            workspace = root / "runs" / "run-002"
            args = wb_mail.build_parser().parse_args([
                "plan", "--workflow", "weekly-business-report",
                "--artifact", str(artifact), "--workspace", str(workspace),
                "--allowed-sender", "sender@example.invalid",
                "--host-sender", "agent@example.invalid",
                "--recipients", json.dumps(["reader@example.invalid"]),
            ])
            plan = wb_mail.build_plan(args)
            self.assertEqual(plan["status"], "blocked")
            self.assertFalse(plan["sent"])
            self.assertEqual(plan["providerReadback"], "unavailable")
            delivered = Path(plan["localDelivery"]["path"])
            self.assertTrue(delivered.is_file())
            self.assertEqual(plan["localDelivery"]["sha256"],
                             hashlib.sha256(delivered.read_bytes()).hexdigest())

    def test_note_forbids_sender_override(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()) as out:
            wb_mail.cmd_note(wb_mail.build_parser().parse_args(["note"]))
        note = json.loads(out.getvalue())
        self.assertIn("sender override", note["forbidden"])


class ScheduleTests(unittest.TestCase):
    def test_specs_never_guess_a_rrule(self) -> None:
        for workflow in wb_schedule.WORKFLOWS:
            spec = wb_schedule.spec_for(workflow, "/tmp/dedicated-workspace")
            self.assertIsNone(spec["rrule"])
            self.assertTrue(spec["requiresUserConfirmation"])
            self.assertEqual(spec["status"], "PAUSED")
            self.assertIn("wb_state.py", spec["prompt"])
            self.assertIn("mcp__smedc__", spec["prompt"])

    def test_specs_command_reports_created_false(self) -> None:
        args = wb_schedule.build_parser().parse_args([
            "--workspace", "/tmp/dedicated-workspace", "specs"])
        with contextlib.redirect_stdout(io.StringIO()) as out:
            wb_schedule.cmd_specs(args)
        payload = json.loads(out.getvalue())
        self.assertFalse(payload["created"])
        self.assertEqual(len(payload["workflows"]), 3)


class OverlayTests(unittest.TestCase):
    def test_generated_overlays_match_sources(self) -> None:
        generated = {p.parent.name: p.read_text(encoding="utf-8")
                     for p in (WORKBUDDY / "overlays" / "generated").glob("*/SKILL.md")}
        expected = wb_overlays.generate()
        self.assertEqual(set(generated), set(expected))
        for name, text in expected.items():
            with self.subTest(skill=name):
                self.assertEqual(generated[name], text)
                self.assertIn("WorkBuddy", text)

    def test_overlays_remove_codex_browser_tokens(self) -> None:
        expected = wb_overlays.generate()
        for name in ("download-meituan-business-data", "reply-meituan-reviews"):
            if name in expected:
                self.assertNotIn("cua_repl", expected[name])

    def test_check_subcommand_exits_zero(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(wb_overlays.cmd_check(None), 0)


if __name__ == "__main__":
    unittest.main()
