from __future__ import annotations

from pydantic import Field

from personal_agent.schemas.common import Frozen


class CredentialHandle(Frozen):
    """What the agent and LLM see. Never contains the secret."""

    handle_id: str
    service: str
    scopes: list[str] = Field(default_factory=list)
