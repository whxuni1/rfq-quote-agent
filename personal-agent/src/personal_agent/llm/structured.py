"""Structured output: JSON mode + schema in prompt + Pydantic validation + bounded repair."""

from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from personal_agent.config import ModelRole
from personal_agent.llm.base import ChatMessage, LLMClient

T = TypeVar("T", bound=BaseModel)

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class StructuredOutputError(RuntimeError):
    pass


def _schema_instruction(model: type[BaseModel]) -> str:
    schema = json.dumps(model.model_json_schema(), ensure_ascii=False)
    return f"只输出一个 JSON 对象（不要 markdown），必须符合以下 JSON Schema：\n{schema}"


async def complete_structured(
    llm: LLMClient,
    messages: list[ChatMessage],
    model: type[T],
    *,
    role: ModelRole,
    max_repairs: int = 2,
) -> tuple[T, int]:
    """Returns (parsed model, tokens used)."""
    convo = [*messages, ChatMessage(role="system", content=_schema_instruction(model))]
    tokens = 0
    last_err = ""
    for _ in range(max_repairs + 1):
        resp = await llm.chat(convo, role=role, json_mode=True)
        tokens += resp.tokens
        raw = _FENCE.sub("", resp.content.strip())
        try:
            return model.model_validate_json(raw), tokens
        except ValidationError as e:
            last_err = str(e)[:2000]
            convo = [
                *convo,
                ChatMessage(role="assistant", content=resp.content),
                ChatMessage(role="user", content=f"上面的输出不合法：{last_err}\n请修正后只输出 JSON。"),
            ]
    raise StructuredOutputError(f"{model.__name__}: {last_err}")
