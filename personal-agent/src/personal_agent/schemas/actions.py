from __future__ import annotations

from datetime import datetime
from enum import IntEnum
from typing import Any, Literal

from pydantic import Field

from personal_agent.schemas.common import Frozen, utcnow


class RiskLevel(IntEnum):
    R0 = 0  # read local
    R1 = 1  # read external
    R2 = 2  # reversible write
    R3 = 3  # externally visible / irreversible
    R4 = 4  # money / identity


class ToolSpec(Frozen):
    name: str
    capability: str
    risk: RiskLevel
    description: str
    params_schema: dict[str, Any]
    required_scopes: list[str] = Field(default_factory=list)
    network: bool = False  # tool reaches the internet (args carry a URL or query)
    rate_limit_per_min: int = 30
    timeout_s: float = 30.0


class ActionRequest(Frozen):
    action_id: str
    goal_id: str
    step_id: str
    tool: str
    args: dict[str, Any]


Decision = Literal["allow", "deny", "needs_approval"]


class SentinelVerdict(Frozen):
    action_id: str
    decision: Decision
    risk: RiskLevel
    matched_rules: list[str]
    reason: str


class ApprovalRequest(Frozen):
    request_id: str
    goal_id: str
    actions: list[ActionRequest]
    verdicts: list[SentinelVerdict]
    human_summary: str
    created_at: datetime = Field(default_factory=utcnow)


class ApprovalDecision(Frozen):
    request_id: str
    decisions: dict[str, Literal["approve", "reject"]]
    edited_args: dict[str, dict[str, Any]] = Field(default_factory=dict)
    decided_at: datetime = Field(default_factory=utcnow)


class ToolResult(Frozen):
    action_id: str
    ok: bool
    output: Any = None
    trust: Literal["trusted", "untrusted"] = "trusted"
    truncated: bool = False
    error: str | None = None
    discovered_domains: list[str] = Field(default_factory=list)
