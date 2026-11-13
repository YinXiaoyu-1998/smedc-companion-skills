from email import policy
from email.parser import BytesParser
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import smtp_submission


class SMTPSubmissionTests(unittest.TestCase):
    def test_frozen_html_submission_persists_only_a_complete_acceptance(self):
        class Relay:
            def __init__(self):
                self.recipients = []
                self.messages = []

            def close(self):
                pass

            def mail(self, sender):
                self.sender = sender
                return 250, b"ok"

            def rcpt(self, recipient):
                self.recipients.append(recipient)
                return 250, b"ok"

            def data(self, payload):
                self.messages.append(BytesParser(policy=policy.default).parsebytes(payload))
                return 250, b"queued"

        html = "<html>营业周报</html>"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mail.json"
            path.write_text(json.dumps({
                "workflowId": "workflow", "actionId": "action", "correlationMarker": "marker",
                "identityHash": "a" * 64, "artifactHash": hashlib.sha256(html.encode()).hexdigest(),
                "sender": "sender@example.test", "recipients": ["reader@example.test"],
                "subject": "Weekly report", "body": "Summary", "bodyType": "plain",
                "attachment": {"filename": "report.html", "content": html},
            }), encoding="utf-8")
            relay = Relay()
            with patch.object(smtp_submission, "connect", return_value=relay):
                receipt = smtp_submission.submit(path)
                with patch.object(sys, "argv", ["smtp_submission.py", "submit", str(path)]):
                    self.assertEqual(smtp_submission.main(), {"state": "unknown"})
            self.assertEqual(receipt["state"], "accepted")
            self.assertEqual(json.loads(path.with_suffix(".receipt.json").read_text()), receipt)
            self.assertEqual(relay.recipients, ["reader@example.test"])
            self.assertEqual(len(relay.messages), 1)
            self.assertEqual(relay.messages[0]["Message-ID"], receipt["messageId"])
            self.assertEqual(next(relay.messages[0].iter_attachments()).get_payload(decode=True), html.encode())
