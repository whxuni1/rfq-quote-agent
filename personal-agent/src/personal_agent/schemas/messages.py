from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from personal_agent.schemas.common import Frozen, utcnow


class StructuredAction(Frozen):
    """A button press / signed command from an authenticated channel.

    Approvals are accepted ONLY through this, never from free text.
    """

    kind: Literal["approve", "reject", "cancel_goal", "confirm_memory", "forget_memory"]
    target_id: str
    action_ids: list[str] = Field(default_factory=list)  # empty = all actions in the request


class InboundMessage(Frozen):
    message_id: str
    channel: Literal["cli", "web", "test"]
    user_id: str
    text: str = ""
    structured_action: StructuredAction | None = None
    received_at: datetime = Field(default_factory=utcnow)


class OutboundMessage(Frozen):
    text: str
    used_memory_ids: list[str] = Field(default_factory=list)
    goal_id: str | None = None
    approval_request_id: str | None = None
