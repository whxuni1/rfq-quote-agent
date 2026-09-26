from __future__ import annotations

import pytest

from personal_agent.agent import PersonalAgent
from personal_agent.config import Settings
from personal_agent.llm.fake import FakeLLMClient
from personal_agent.schemas import RiskLevel
from personal_agent.tools.builtin.web import WebFetchParams, WebSearchParams


@pytest.fixture
def agent(settings: Settings, llm: FakeLLMClient) -> PersonalAgent:
    a = PersonalAgent(settings, llm)
    a.registry.register(name="web.search", capability="web.read", risk=RiskLevel.R1, network=True,
                        untrusted_output=True, description="search", params=WebSearchParams,
                        sandboxed_fn="fake_web:search")
    a.registry.register(name="web.fetch", capability="web.read", risk=RiskLevel.R1, network=True,
                        untrusted_output=True, description="fetch", params=WebFetchParams,
                        sandboxed_fn="fake_web:fetch")
    return a
