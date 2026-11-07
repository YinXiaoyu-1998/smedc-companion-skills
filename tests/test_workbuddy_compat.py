"""Regression tests for the additive WorkBuddy host adapter.

These tests are host-neutral: no browser CLI, mail server, MCP server or
network access is required. They prove (a) the Codex sources and repository
CI assertions are untouched, and (b) the new local components behave as
documented. Browser CLI calls are mocked so argument wiring is verified
without a live daemon.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import re
import shlex
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
WORKBUDDY = ROOT / "workbuddy"
SCRIPTS = WORKBUDDY / "scripts"
GENERATED = WORKBUDDY / "overlays" / "generated"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


wb_state = load_module("wb_state", SCRIPTS / "wb_state.py")
wb_mail = load_module("wb_mail", SCRIPTS / "wb_mail.py")
wb_schedule = load_module("wb_schedule", SCRIPTS / "wb_schedule.py")
wb_browser = load_module("wb_browser", SCRIPTS / "wb_browser.py")
wb_overlays = load_module("wb_overlays", WORKBUDDY / "overlays" / "build_overlays.py")


def committed_overlays() -> dict[tuple[str, str], str]:
    return wb_overlays.committed_files() if hasattr(wb_overlays, "committed_files") else {
        (rel.parts[0], "/".join(rel.parts[1:])): p.read_text(encoding="utf-8")
        for p in GENERATED.rglob("*.md")
        for rel in [p.relative_to(GENERATED)]
        if len(rel.parts) >= 2
    }


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
        self.assertEqual(state["prevHash"], "")
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

    def test_empty_evidence_is_rejected(self) -> None:
        self.init_state()
        args = wb_state.build_parser().parse_args([
            "save-progress", "--root", str(self.root),
            "--task-id", "business", "--scope-hash", "b" * 64,
        ])
        with self.assertRaises(ValueError):
            wb_state.cmd_save_progress(args)
        self.assertEqual(wb_state.load(self.root)["completed"], {})

    def test_blocked_run_cannot_close_as_succeeded(self) -> None:
        self.init_state()
        parser = wb_state.build_parser()
        with contextlib.redirect_stdout(io.StringIO()):
            wb_state.cmd_mark_blocked(parser.parse_args([
                "mark-blocked", "--root", str(self.root),
                "--task-id", "email", "--reason", "native mail unavailable"]))
        with self.assertRaises(ValueError):
            wb_state.cmd_close(parser.parse_args([
                "close", "--root", str(self.root), "--outcome", "succeeded"]))
        with contextlib.redirect_stdout(io.StringIO()):
            wb_state.cmd_close(parser.parse_args([
                "close", "--root", str(self.root), "--outcome", "partial"]))
        self.assertEqual(wb_state.load(self.root)["outcome"], "partial")

    def test_rollback_is_detected_by_journal(self) -> None:
        self.init_state()
        revision_one = (self.root / "state.json").read_text(encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            wb_state.cmd_save_progress(wb_state.build_parser().parse_args([
                "save-progress", "--root", str(self.root),
                "--task-id", "business", "--scope-hash", "b" * 64,
                "--evidence", str(self.evidence)]))
        self.assertEqual(wb_state.load(self.root)["revision"], 2)
        (self.root / "state.json").write_text(revision_one, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "rollback|journal"):
            wb_state.load(self.root)

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


class BrowserBridgeTests(unittest.TestCase):
    def fake_run(self, payload: dict, returncode: int = 0):
        return mock.Mock(returncode=returncode,
                         stdout=json.dumps(payload), stderr="")

    def download_args(self, *extra: str):
        return wb_browser.build_parser().parse_args([
            "download", "--session", "s1", "--dest", "/tmp/a.xlsx", *extra])

    def test_download_uses_bsk_out_flag(self) -> None:
        with mock.patch.object(wb_browser.subprocess, "run",
                               return_value=self.fake_run({"ok": True})) as run:
            args = self.download_args("--target", "@e3",
                                      "--context", "ctx", "--observation", "obs")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(wb_browser.cmd_download(args), 0)
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[0], "bsk")
        self.assertIn("--out", cmd)
        self.assertNotIn("--output", cmd)
        self.assertIn("/tmp/a.xlsx", cmd)
        self.assertIn("--timeout", cmd)
        self.assertIn("--json", cmd)

    def test_download_requires_a_trigger(self) -> None:
        args = self.download_args("--context", "ctx", "--observation", "obs")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(wb_browser.cmd_download(args), 1)
        self.assertIn("trigger", json.loads(out.getvalue())["error"])

    def test_download_requires_context_and_observation(self) -> None:
        args = self.download_args("--target", "@e3")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(wb_browser.cmd_download(args), 1)
        self.assertIn("context", json.loads(out.getvalue())["error"])

    def test_download_wires_trigger_and_context(self) -> None:
        with mock.patch.object(wb_browser.subprocess, "run",
                               return_value=self.fake_run({"ok": True})) as run:
            args = self.download_args("--target", "@e3", "--context", "ctx",
                                      "--observation", "obs", "--overwrite")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(wb_browser.cmd_download(args), 0)
        cmd = run.call_args.args[0]
        for token in ("@e3", "--context", "ctx", "--observation", "obs", "--overwrite"):
            self.assertIn(token, cmd)

    def test_session_lost_error_has_recovery_hint(self) -> None:
        payload = {"code": "not_found",
                   "message": "session not registered or already stopped"}
        with mock.patch.object(wb_browser.subprocess, "run",
                               return_value=self.fake_run(payload, returncode=1)):
            result = wb_browser.run_bsk(["snapshot", "--session", "s1"])
        self.assertFalse(result["ok"])
        self.assertIn("recovery", result)

    def test_exit_code_only_errors_are_reported(self) -> None:
        payload = {"code": None, "message": "missing target", "exit_code": 2}
        with mock.patch.object(wb_browser.subprocess, "run",
                               return_value=self.fake_run(payload, returncode=1)):
            result = wb_browser.run_bsk(["download", "--session", "s1"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["message"], "missing target")



class MailDegradationTests(unittest.TestCase):
    def plan_args(self, artifact: Path, workspace: Path):
        return wb_mail.build_parser().parse_args([
            "plan", "--workflow", "weekly-business-report",
            "--artifact", str(artifact), "--workspace", str(workspace),
            "--allowed-sender", "sender@example.invalid",
            "--host-sender", "agent@example.invalid",
            "--recipients", json.dumps(["reader@example.invalid"]),
        ])

    def test_plan_is_blocked_and_delivers_locally(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "weekly-report.html"
            artifact.write_text("<html>report</html>", encoding="utf-8")
            workspace = root / "runs" / "run-002"
            plan = wb_mail.build_plan(self.plan_args(artifact, workspace))
            self.assertEqual(plan["status"], "blocked")
            self.assertFalse(plan["sent"])
            self.assertEqual(plan["providerReadback"], "unavailable")
            delivered = Path(plan["localDelivery"]["path"])
            self.assertTrue(delivered.is_file())
            self.assertEqual(plan["localDelivery"]["sha256"],
                             hashlib.sha256(delivered.read_bytes()).hexdigest())

    def test_delivery_never_overwrites_earlier_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "weekly-report.html"
            workspace = root / "runs" / "run-003"
            artifact.write_text("A", encoding="utf-8")
            first = wb_mail.build_plan(self.plan_args(artifact, workspace))
            artifact.write_text("B", encoding="utf-8")
            second = wb_mail.build_plan(self.plan_args(artifact, workspace))
            first_path = Path(first["localDelivery"]["path"])
            second_path = Path(second["localDelivery"]["path"])
            self.assertNotEqual(first_path, second_path)
            self.assertEqual(first_path.read_text(encoding="utf-8"), "A")
            self.assertEqual(second_path.read_text(encoding="utf-8"), "B")
            artifact.write_text("A", encoding="utf-8")
            third = wb_mail.build_plan(self.plan_args(artifact, workspace))
            self.assertEqual(third["localDelivery"]["path"], str(first_path))
            self.assertTrue(third["localDelivery"]["reused"])

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

    def test_spec_declares_tool_binding(self) -> None:
        spec = wb_schedule.spec_for("weekly-business-report", "/tmp/dedicated-workspace")
        self.assertIn("requiredTools", spec)
        self.assertIn("toolBinding", spec)
        self.assertIn("notificationPolicyNote", spec)
        self.assertNotIn("notificationPolicy", spec)

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
        generated = committed_overlays()
        expected = {(name, rel): text
                    for name, files in wb_overlays.generate().items()
                    for rel, text in files.items()}
        self.assertEqual(set(generated), set(expected))
        for key, text in expected.items():
            with self.subTest(overlay="/".join(key)):
                self.assertEqual(generated[key], text)
                self.assertIn("WorkBuddy", text)

    def test_no_host_specific_tokens_survive(self) -> None:
        for key, text in committed_overlays().items():
            for pattern in wb_overlays.FORBIDDEN_PATTERNS:
                with self.subTest(overlay="/".join(key), pattern=pattern):
                    self.assertIsNone(re.search(pattern, text))

    def test_references_are_adapted_too(self) -> None:
        keys = set(committed_overlays())
        self.assertIn(("smedc-workflows", "references/browser.md"), keys)
        self.assertIn(("download-meituan-business-data", "SKILL.md"), keys)

    def test_check_subcommand_exits_zero(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(wb_overlays.cmd_check(None), 0)


if __name__ == "__main__":
    unittest.main()
