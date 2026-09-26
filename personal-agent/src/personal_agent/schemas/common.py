from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

JsonDict = dict[str, Any]


def utcnow() -> datetime:
    return datetime.now(UTC)


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
