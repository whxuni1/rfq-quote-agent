"""OpenAI-compatible chat client. Default target: DeepSeek (https://api.deepseek.com)."""

from __future__ import annotations

from typing import Any

from openai import AsyncOpenAI

from personal_agent.config import ModelRole, Settings
from personal_agent.llm.base import ChatMessage, LLMResponse


class OpenAICompatClient:
    def __init__(self, settings: Settings, client: AsyncOpenAI | None = None) -> None:
        if client is None and not settings.llm_api_key:
            raise ValueError("PA_LLM_API_KEY (or DEEPSEEK_API_KEY) is not set")
        self._settings = settings
        self._client = client or AsyncOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)

    async def chat(
        self, messages: list[ChatMessage], *, role: ModelRole, json_mode: bool = False
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self._settings.models[role],
            "messages": [m.model_dump() for m in messages],
            "temperature": 0.0 if json_mode else 0.7,
        }
        if json_mode:
            # DeepSeek supports json_object (not json_schema); the schema goes in the prompt.
            kwargs["response_format"] = {"type": "json_object"}
        resp = await self._client.chat.completions.create(**kwargs)
        content = resp.choices[0].message.content or ""
        tokens = resp.usage.total_tokens if resp.usage else 0
        return LLMResponse(content=content, tokens=tokens)
