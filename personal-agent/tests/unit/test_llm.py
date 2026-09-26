from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from personal_agent.config import Settings
from personal_agent.llm import ChatMessage, StructuredOutputError, complete_structured
from personal_agent.llm.fake import FakeLLMClient
from personal_agent.llm.openai_compat import OpenAICompatClient


class Out(BaseModel):
    x: int


async def test_structured_repairs_invalid_json() -> None:
    replies = iter(["not json", "```json\n{\"x\": 3}\n```"])
    llm = FakeLLMClient(lambda _r, _m: next(replies))
    out, tokens = await complete_structured(llm, [ChatMessage(role="user", content="hi")], Out, role="router")
    assert out.x == 3 and tokens > 0
    # the repair turn carries the validation error back to the model
    assert "不合法" in llm.calls[1][1][-1].content


async def test_structured_gives_up() -> None:
    llm = FakeLLMClient(lambda _r, _m: "{}")
    with pytest.raises(StructuredOutputError):
        await complete_structured(llm, [ChatMessage(role="user", content="hi")], Out, role="router", max_repairs=1)
    assert len(llm.calls) == 2


class _FakeCompletions:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] = {}

    async def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        msg = SimpleNamespace(content='{"x": 1}')
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=SimpleNamespace(total_tokens=42))


async def test_openai_compat_uses_deepseek_defaults() -> None:
    comp = _FakeCompletions()
    fake = SimpleNamespace(chat=SimpleNamespace(completions=comp))
    s = Settings(llm_api_key="k")
    client = OpenAICompatClient(s, client=fake)  # type: ignore[arg-type]
    resp = await client.chat([ChatMessage(role="user", content="q")], role="planner", json_mode=True)
    assert resp.tokens == 42
    assert comp.kwargs["model"] == "deepseek-v4-pro"
    assert comp.kwargs["response_format"] == {"type": "json_object"}
    assert s.llm_base_url == "https://api.deepseek.com"
    await client.chat([ChatMessage(role="user", content="q")], role="router")
    assert comp.kwargs["model"] == "deepseek-flash" and "response_format" not in comp.kwargs


def test_openai_compat_requires_key() -> None:
    with pytest.raises(ValueError):
        OpenAICompatClient(Settings(llm_api_key=""))


def test_settings_from_env() -> None:
    s = Settings.from_env({
        "DEEPSEEK_API_KEY": "sk", "PA_MODEL_PLANNER": "deepseek-reasoner",
        "PA_EGRESS_ALLOWLIST": "Example.com, github.com", "PA_DATA_DIR": "/tmp/pa",
    })
    assert s.llm_api_key == "sk" and s.models["planner"] == "deepseek-reasoner"
    assert s.models["router"] == "deepseek-flash"
    assert s.egress_allowlist == ["example.com", "github.com"]
    assert str(s.db_path) == "/tmp/pa/agent.db"
