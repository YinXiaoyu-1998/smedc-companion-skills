"""Submit a frozen workflow message through the host's SMTP configuration."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import smtplib
import ssl
import sys
from datetime import datetime, timezone
from email import policy
from email.message import EmailMessage

ADDRESS = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
MARKER = re.compile(r"[A-Za-z0-9_-]{1,64}")


def connect(sender):
    host = os.environ["SMTP_HOST"]
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASS"]
    if not host or not password or sender.lower() != user.lower() or not ADDRESS.fullmatch(user):
        raise ValueError("SMTP identity mismatch")
    secure = os.environ.get("SMTP_SECURE", "false").lower() == "true"
    port = int(os.environ.get("SMTP_PORT", "465" if secure else "587"))
    context = ssl.create_default_context()
    client = (
        smtplib.SMTP_SSL(host, port, timeout=12, context=context)
        if secure
        else smtplib.SMTP(host, port, timeout=12)
    )
    try:
        if not secure:
            client.starttls(context=context)
        client.login(user, password)
        return client
    except Exception:
        client.close()
        raise


def write_receipt(path, value):
    temporary = path.with_suffix(".tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(value, handle)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def message_for(request):
    sender, recipients = request["sender"], request["recipients"]
    marker, subject = request["correlationMarker"], request["subject"]
    if (
        not recipients or len(set(recipients)) != len(recipients)
        or not all(ADDRESS.fullmatch(a) for a in [sender, *recipients])
        or not MARKER.fullmatch(marker)
        or any(c in subject for c in "\r\n")
    ):
        raise ValueError("Invalid frozen envelope")
    text = request["body"]
    attachment = request.get("attachment")
    artifact = (attachment["content"] if attachment else text).encode("utf-8")
    if hashlib.sha256(artifact).hexdigest() != request["artifactHash"]:
        raise ValueError("Frozen mail artifact mismatch")
    msg = EmailMessage(policy=policy.SMTP)
    msg["From"], msg["To"] = sender, ", ".join(recipients)
    msg["Subject"] = f"{subject} [{marker}]"
    message_key = hashlib.sha256(
        f"{request['workflowId']}:{request['actionId']}:{marker}".encode()
    ).hexdigest()
    msg["Message-ID"] = f"<smedc-{message_key[:40]}@{sender.rsplit('@', 1)[1]}>"
    msg.set_content(text, subtype=request["bodyType"], charset="utf-8")
    if attachment:
        filename = attachment["filename"]
        if not filename.lower().endswith(".html") or any(c in filename for c in "/\\\r\n"):
            raise ValueError("Invalid HTML attachment name")
        msg.add_attachment(artifact, maintype="text", subtype="html", filename=filename)
    return msg


def submit(request_path):
    request = json.loads(request_path.read_text(encoding="utf-8"))
    msg = message_for(request)
    payload = msg.as_bytes()
    receipt_path = request_path.with_suffix(".receipt.json")
    dispatched_path = request_path.with_suffix(".dispatched")
    with contextlib.closing(connect(request["sender"])) as client:
        # Require all authorized recipients before DATA. A partial envelope never sends.
        code, _ = client.mail(request["sender"])
        if code == 250:
            for recipient in request["recipients"]:
                code, _ = client.rcpt(recipient)
                if code not in (250, 251, 252):
                    break
            else:
                code = None
        if code is not None:
            return {"state": "rejected"} if 400 <= code < 600 else {"state": "unknown"}
        # Exclusive durable marker: do not replay DATA even if the caller or SMTP connection dies.
        with dispatched_path.open("x", encoding="utf-8") as handle:
            handle.write(str(msg["Message-ID"]))
            handle.flush()
            os.fsync(handle.fileno())
        fd = os.open(dispatched_path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        try:
            code, _ = client.data(payload)
        except smtplib.SMTPDataError as exc:
            code = exc.smtp_code
        if code != 250:
            return {"state": "unknown"}
        receipt = {
            "state": "accepted",
            "workflowId": request["workflowId"],
            "actionId": request["actionId"],
            "identityHash": request["identityHash"],
            "artifactHash": request["artifactHash"],
            "correlationMarker": request["correlationMarker"],
            "messageId": str(msg["Message-ID"]),
            "responseCode": code,
            "verifiedAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        }
        write_receipt(receipt_path, receipt)
        return receipt


def main():
    mode, arg = sys.argv[1:]
    os.umask(0o077)
    if mode == "check":
        with contextlib.closing(connect(arg)):
            return {"state": "ready"}
    path = Path(arg)
    if mode == "receipt":
        path = path.with_suffix(".receipt.json")
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"state": "unknown"}
    if mode == "submit":
        if path.with_suffix(".dispatched").exists():
            return {"state": "unknown"}
        return submit(path)
    raise ValueError("Unsupported operation")


if __name__ == "__main__":
    try:
        print(json.dumps(main()))
    except (OSError, ValueError, KeyError, TypeError, smtplib.SMTPException):
        # Provider errors may contain credentials, addresses or payload fragments.
        print(json.dumps({"state": "unknown"}))
