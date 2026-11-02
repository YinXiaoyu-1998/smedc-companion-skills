import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_log.py"


class AuditCliTests(unittest.TestCase):
    def test_write_error_is_durably_unknown_and_credentials_are_redacted(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary).resolve()
            start = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "start",
                    "--run-dir",
                    str(run),
                    "--meta-json",
                    json.dumps(
                        {
                            "stage": "publish",
                            "tool": "synthetic",
                            "effect": "external_write",
                        }
                    ),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(start.returncode, 0, start.stderr)
            call = json.loads(start.stdout)["callId"]
            error = {
                "isError": True,
                "message": "Timeout after dispatch; Bearer SYNTHETIC_SECRET",
                "access_token": "SYNTHETIC_SECRET",
            }
            finish = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "finish",
                    "--run-dir",
                    str(run),
                    "--call-id",
                    call,
                    "--status",
                    "failed",
                    "--payload-json",
                    json.dumps(error),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(finish.returncode, 0, finish.stderr)
            record = json.loads((run / "call-audit" / f"{call}.json").read_text())
            self.assertEqual(record["status"], "unknown")
            self.assertNotIn("SYNTHETIC_SECRET", json.dumps(record))
            self.assertIn("Timeout after dispatch", record["result"]["message"])
            check = subprocess.run(
                [sys.executable, str(SCRIPT), "check", "--run-dir", str(run)],
                capture_output=True,
                text=True,
            )
            state = json.loads(check.stdout)
            self.assertEqual(state["externalWriteUnknown"], [call])
            self.assertFalse(state["journalComplete"])
