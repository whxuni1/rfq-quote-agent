"""Personal memory: write (dedupe/supersede), recall (lexical, CJK-aware), forget, export."""

from __future__ import annotations

import re
from typing import Literal

from personal_agent.ids import new_id
from personal_agent.llm import ChatMessage, LLMClient, complete_structured
from personal_agent.prompts import load_prompt
from personal_agent.schemas.memory import MemoryCandidate, MemoryExtraction, MemoryItem
from personal_agent.store.db import Database

Source = Literal["user_statement", "user_explicit", "untrusted_content"]

_SENSITIVE_HINTS = (
    "allerg", "health", "medical", "diagnos", "medication", "bank", "salary", "income", "passport",
    "id_number", "religion", "politic", "address", "phone",
    "过敏", "健康", "疾病", "病", "药", "医", "银行", "工资", "收入", "身份证", "护照", "宗教", "政治", "住址", "电话",
)
_WORD = re.compile(r"[a-z0-9]+")
_CJK = re.compile(r"[一-鿿]+")


def _terms(text: str) -> set[str]:
    t = text.lower()
    terms = {w for w in _WORD.findall(t) if len(w) > 1}
    for run in _CJK.findall(t):
        terms.update(run[i : i + 2] for i in range(len(run) - 1))
        if len(run) == 1:
            terms.add(run)
    return terms


def is_sensitive(c: MemoryCandidate) -> bool:
    blob = f"{c.predicate} {c.value}".lower()
    return c.sensitive or any(h in blob for h in _SENSITIVE_HINTS)


class MemoryService:
    def __init__(self, db: Database) -> None:
        self._db = db

    # ---- storage -------------------------------------------------------------------------
    def _save(self, item: MemoryItem) -> None:
        self._db.conn.execute(
            "INSERT OR REPLACE INTO memories (memory_id, status, body) VALUES (?,?,?)",
            (item.memory_id, item.status, item.model_dump_json()),
        )

    def get(self, memory_id: str) -> MemoryItem | None:
        row = self._db.conn.execute("SELECT body FROM memories WHERE memory_id=?", (memory_id,)).fetchone()
        return MemoryItem.model_validate_json(row["body"]) if row else None

    def list_items(self, status: str | None = "active") -> list[MemoryItem]:
        q = "SELECT body FROM memories" + (" WHERE status=?" if status else "") + " ORDER BY memory_id"
        rows = self._db.conn.execute(q, (status,) if status else ()).fetchall()
        return [MemoryItem.model_validate_json(r["body"]) for r in rows]

    def add(self, c: MemoryCandidate, source: Source) -> MemoryItem | None:
        """Returns the stored item, or None if it duplicates an active memory."""
        key = (c.subject.strip().lower(), c.predicate.strip().lower())
        for old in self.list_items("active"):
            if (old.subject.lower(), old.predicate.lower()) != key:
                continue
            if old.value.strip() == c.value.strip():
                return None
            if source != "untrusted_content":
                self._save(old.model_copy(update={"status": "superseded"}))
        item = MemoryItem(
            memory_id=new_id("mem"), type=c.type, subject=c.subject, predicate=c.predicate, value=c.value,
            sensitive=is_sensitive(c), source=source, evidence=c.evidence[:500],
            status="pending_confirm" if source == "untrusted_content" else "active",
        )
        self._save(item)
        return item

    def confirm(self, memory_id: str) -> MemoryItem | None:
        item = self.get(memory_id)
        if item is None or item.status != "pending_confirm":
            return None
        confirmed = item.model_copy(update={"status": "active", "source": "user_explicit"})
        self._save(confirmed)
        return confirmed

    def forget(self, memory_id: str) -> bool:
        cur = self._db.conn.execute("DELETE FROM memories WHERE memory_id=?", (memory_id,))
        return cur.rowcount > 0

    def export(self) -> list[dict[str, object]]:
        return [m.model_dump(mode="json") for m in self.list_items(None)]

    # ---- recall --------------------------------------------------------------------------
    def recall(self, query: str, limit: int = 12) -> list[MemoryItem]:
        q = _terms(query)
        scored: list[tuple[float, MemoryItem]] = []
        for m in self.list_items("active"):
            t = _terms(f"{m.subject} {m.predicate} {m.value}")
            overlap = len(q & t)
            # Preferences/facts about the user are always weakly relevant to planning.
            score = overlap + (0.1 if m.subject.lower() in ("user", "用户") else 0.0)
            if overlap or m.type == "preference":
                scored.append((score, m))
        scored.sort(key=lambda x: (-x[0], x[1].memory_id))
        return [m for _, m in scored[:limit]]

    def sensitive_values(self) -> list[str]:
        return [m.value for m in self.list_items("active") if m.sensitive and len(m.value) >= 2]

    # ---- extraction ----------------------------------------------------------------------
    async def extract_from_user(self, llm: LLMClient, user_text: str) -> tuple[list[MemoryItem], int]:
        """Only the user's own words are mined; tool output never is."""
        msgs = [
            ChatMessage(role="system", content=load_prompt("memory_extract")),
            ChatMessage(role="user", content=user_text),
        ]
        extraction, tokens = await complete_structured(llm, msgs, MemoryExtraction, role="memory")
        explicit = bool(re.search(r"记住|remember", user_text, re.IGNORECASE))
        stored = [
            item
            for c in extraction.candidates
            if (item := self.add(c, "user_explicit" if explicit else "user_statement")) is not None
        ]
        return stored, tokens


def format_memories(items: list[MemoryItem]) -> str:
    if not items:
        return "（无相关记忆）"
    return "\n".join(f"- [{m.memory_id}] {m.subject}.{m.predicate} = {m.value}" for m in items)
