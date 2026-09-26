from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field

from personal_agent.schemas.common import Frozen, utcnow


class MemoryType(StrEnum):
    FACT = "fact"
    PREFERENCE = "preference"


class MemoryItem(Frozen):
    memory_id: str
    type: MemoryType
    subject: str
    predicate: str
    value: str
    sensitive: bool = False
    source: Literal["user_statement", "user_explicit", "untrusted_content"]
    evidence: str
    status: Literal["active", "pending_confirm", "superseded"] = "active"
    created_at: datetime = Field(default_factory=utcnow)


class MemoryCandidate(Frozen):
    type: MemoryType
    subject: str
    predicate: str
    value: str
    evidence: str
    sensitive: bool = False


class MemoryExtraction(Frozen):
    candidates: list[MemoryCandidate] = Field(default_factory=list)
