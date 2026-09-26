"""IMAP read (R1) and SMTP send (R3, always behind approval). Credentials come from the vault:
{"imap_host", "smtp_host", "smtp_port", "username", "password", "from_addr"}."""

from __future__ import annotations

import email
import imaplib
import smtplib
from email.header import decode_header, make_header
from email.message import EmailMessage
from typing import Any

from pydantic import BaseModel, Field

from personal_agent.tools.base import ToolContext


class MailListParams(BaseModel):
    folder: str = "INBOX"
    limit: int = Field(default=10, ge=1, le=50)
    unseen_only: bool = False


class MailSendParams(BaseModel):
    to: list[str] = Field(min_length=1)
    subject: str
    body: str


def _dec(v: str | None) -> str:
    return str(make_header(decode_header(v))) if v else ""


def mail_list(args: dict[str, Any], ctx: ToolContext) -> list[dict[str, Any]]:
    p = MailListParams.model_validate(args)
    c = ctx.credentials or {}
    with imaplib.IMAP4_SSL(c["imap_host"]) as imap:
        imap.login(c["username"], c["password"])
        imap.select(p.folder, readonly=True)
        _, data = imap.search(None, "UNSEEN" if p.unseen_only else "ALL")
        ids = data[0].split()[-p.limit :]
        out = []
        for i in reversed(ids):
            _, msg_data = imap.fetch(i, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            raw = msg_data[0][1] if msg_data and isinstance(msg_data[0], tuple) else b""
            m = email.message_from_bytes(raw)
            out.append({"from": _dec(m["From"]), "subject": _dec(m["Subject"]), "date": m["Date"]})
        return out


def mail_send(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    p = MailSendParams.model_validate(args)
    c = ctx.credentials or {}
    msg = EmailMessage()
    msg["From"] = c.get("from_addr", c["username"])
    msg["To"] = ", ".join(p.to)
    msg["Subject"] = p.subject
    msg.set_content(p.body)
    with smtplib.SMTP_SSL(c["smtp_host"], int(c.get("smtp_port", 465))) as smtp:
        smtp.login(c["username"], c["password"])
        smtp.send_message(msg)
    return {"sent_to": p.to}
