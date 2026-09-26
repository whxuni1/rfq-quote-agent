"""Local, reversible writes: todos, markdown documents, e-mail drafts."""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from personal_agent.ids import new_id
from personal_agent.tools.base import ToolContext


class TodoAddParams(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    due: str | None = None


class TodoListParams(BaseModel):
    include_done: bool = False


class DocWriteParams(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1)


class MailDraftParams(BaseModel):
    to: list[str] = Field(min_length=1)
    subject: str
    body: str


def _db(ctx: ToolContext) -> sqlite3.Connection:
    conn = sqlite3.connect(str(Path(ctx.data_dir) / "agent.db"))
    conn.row_factory = sqlite3.Row
    return conn


def todo_add(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    p = TodoAddParams.model_validate(args)
    tid = new_id("todo")
    with _db(ctx) as conn:
        conn.execute(
            "INSERT INTO todos (todo_id, text, due, done, created_at) VALUES (?,?,?,0,?)",
            (tid, p.text, p.due, datetime.now(UTC).isoformat()),
        )
    return {"todo_id": tid}


def todo_list(args: dict[str, Any], ctx: ToolContext) -> list[dict[str, Any]]:
    p = TodoListParams.model_validate(args)
    q = "SELECT todo_id, text, due, done FROM todos" + ("" if p.include_done else " WHERE done=0")
    with _db(ctx) as conn:
        return [dict(r) for r in conn.execute(q + " ORDER BY created_at")]


def _slug(title: str) -> str:
    return re.sub(r"[^\w\-]+", "-", title, flags=re.UNICODE).strip("-")[:60] or "doc"


def doc_write(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    p = DocWriteParams.model_validate(args)
    d = Path(ctx.data_dir) / "docs"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{datetime.now(UTC):%Y%m%d-%H%M%S}-{_slug(p.title)}.md"
    path.write_text(f"# {p.title}\n\n{p.content}\n", encoding="utf-8")
    return {"path": str(path)}


def mail_draft(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    p = MailDraftParams.model_validate(args)
    msg = EmailMessage()
    msg["To"] = ", ".join(p.to)
    msg["Subject"] = p.subject
    msg.set_content(p.body)
    d = Path(ctx.data_dir) / "drafts"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{new_id('draft')}.eml"
    path.write_bytes(bytes(msg))
    return {"draft_path": str(path)}
