from __future__ import annotations

from pathlib import Path

import pytest
from pa_testkit import Script

from personal_agent.agent import PersonalAgent
from personal_agent.config import Settings
from personal_agent.llm.fake import FakeLLMClient


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        llm_api_key="test", data_dir=tmp_path / "data", egress_allowlist=["wikipedia.org"],
        vault_passphrase="correct horse battery staple",
    )


@pytest.fixture
def script() -> Script:
    return Script()


@pytest.fixture
def llm(script: Script) -> FakeLLMClient:
    return FakeLLMClient(script.handler)


@pytest.fixture
def agent(settings: Settings, llm: FakeLLMClient) -> PersonalAgent:
    return PersonalAgent(settings, llm)

