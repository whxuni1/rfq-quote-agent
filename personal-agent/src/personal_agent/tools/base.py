from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from personal_agent.schemas.actions import ToolSpec
from personal_agent.schemas.common import Frozen


class ToolContext(Frozen):
    """JSON-serialisable context handed to a sandboxed tool worker."""

    data_dir: str
    allowed_domains: list[str] = Field(default_factory=list)
    searxng_url: str = ""
    credentials: dict[str, Any] | None = None


class ToolOutput(Frozen):
    output: Any = None
    discovered_domains: list[str] = Field(default_factory=list)


LocalFn = Callable[[dict[str, Any]], Any]


@dataclass(frozen=True)
class Tool:
    spec: ToolSpec
    params: type[BaseModel]
    # Exactly one of these is set:
    sandboxed_fn: str | None = None  # "module:function", run in a worker subprocess
    local_fn: LocalFn | None = None  # in-process, only for R0 local reads
    untrusted_output: bool = False
