from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from personal_agent.schemas.common import Frozen, utcnow


class GoalStatus(StrEnum):
    CREATED = "created"
    PLANNING = "planning"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    SLEEPING = "sleeping"
    REPLANNING = "replanning"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = frozenset({GoalStatus.COMPLETED, GoalStatus.FAILED, GoalStatus.CANCELLED})


class GoalBudget(Frozen):
    max_steps: int = 30  # tool actions across the whole goal
    max_llm_tokens: int = 200_000
    max_replans: int = 3
    max_actions_per_step: int = 6


class PlanStep(Frozen):
    step_id: str
    description: str
    capability: str
    success_criteria: str = ""


class Plan(Frozen):
    version: int = 1
    steps: list[PlanStep]
    rationale: str = ""


class GoalEventType(StrEnum):
    CREATED = "created"
    STATUS_CHANGED = "status_changed"
    PLAN_CREATED = "plan_created"
    STEP_STARTED = "step_started"
    STEP_FINISHED = "step_finished"
    ACTION_JUDGED = "action_judged"
    ACTION_RESOLVED = "action_resolved"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_DECIDED = "approval_decided"
    TOKENS_USED = "tokens_used"
    RESULT = "result"


class GoalEvent(Frozen):
    event_id: str
    goal_id: str
    seq: int
    type: GoalEventType
    payload: dict[str, Any]
    at: datetime = Field(default_factory=utcnow)


Outcome = Literal["ok", "error", "denied", "rejected"]


class StepLogEntry(Frozen):
    """One tool interaction inside a step, as seen by the executor LLM."""

    action_id: str
    tool: str
    args: dict[str, Any]
    outcome: Outcome
    output: Any = None


class Goal(BaseModel):
    """Projection of a goal's event stream. Owned exclusively by the GoalEngine."""

    model_config = ConfigDict(extra="forbid")

    goal_id: str
    user_id: str
    title: str
    original_request: str
    allowed_capabilities: list[str]
    status: GoalStatus = GoalStatus.CREATED
    budget: GoalBudget = Field(default_factory=GoalBudget)
    plan: Plan | None = None
    current_step: int = 0
    step_logs: dict[str, list[StepLogEntry]] = Field(default_factory=dict)
    step_summaries: dict[str, str] = Field(default_factory=dict)
    actions_used: int = 0
    tokens_used: int = 0
    replans: int = 0
    pending_approval_id: str | None = None
    allowed_domains: list[str] = Field(default_factory=list)
    result: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
