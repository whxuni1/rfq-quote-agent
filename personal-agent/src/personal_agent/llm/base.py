from __future__ import annotations

from typing import Literal, Protocol

from personal_agent.config import ModelRole
from personal_agent.schemas.common import Frozen


class ChatMessage(Frozen):
    role: Literal["system", "user", "assistant"]
    content: str


class LLMResponse(Frozen):
    content: str
    tokens: int = 0


class LLMClient(Protocol):
    async def chat(
        self, messages: list[ChatMessage], *, role: ModelRole, json_mode: bool = False
    ) -> LLMResponse: ...
