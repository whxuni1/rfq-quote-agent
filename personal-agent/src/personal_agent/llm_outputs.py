"""Structured outputs expected from the LLM (validated; never trusted for authorisation)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class RouteDecision(BaseModel):
    kind: Literal["chat", "new_goal"]
    goal_title: str | None = None


class PlannedStep(BaseModel):
    description: str
    capability: str
    success_criteria: str = ""


class PlanOutput(BaseModel):
    title: str
    capabilities: list[str]
    steps: list[PlannedStep] = Field(min_length=1, max_length=8)
    rationale: str = ""


class StepDecision(BaseModel):
    kind: Literal["call_tool", "finish_step", "replan", "fail"]
    tool: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    reason: str = ""


class ChatReply(BaseModel):
    reply: str
    used_memory_ids: list[str] = Field(default_factory=list)
