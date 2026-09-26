"""Deterministic LLM for tests: a handler decides each reply from (role, messages)."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from personal_agent.config import ModelRole
from personal_agent.llm.base import ChatMessage, LLMResponse

Handler = Callable[[ModelRole, list[ChatMessage]], "str | dict[str, Any]"]


class FakeLLMClient:
    def __init__(self, handler: Handler) -> None:
        self._handler = handler
        self.calls: list[tuple[ModelRole, list[ChatMessage]]] = []

    async def chat(
        self, messages: list[ChatMessage], *, role: ModelRole, json_mode: bool = False
    ) -> LLMResponse:
        self.calls.append((role, messages))
        out = self._handler(role, messages)
        text = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
        return LLMResponse(content=text, tokens=len(text) // 4 + 1)
