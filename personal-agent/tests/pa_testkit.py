"""Test helpers shared by unit and eval suites."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from personal_agent.config import ModelRole
from personal_agent.llm.base import ChatMessage
from personal_agent.prompts import load_prompt

PROMPTS = ("router", "planner", "executor", "summarizer", "memory_extract", "chat")


def prompt_kind(messages: list[ChatMessage]) -> str:
    first = messages[0].content
    for name in PROMPTS:
        if first == load_prompt(name):
            return name
    raise AssertionError(f"unknown prompt: {first[:40]}")


def user_payload(messages: list[ChatMessage]) -> str:
    return next(m.content for m in messages if m.role == "user")


class Script:
    """Scriptable fake LLM. Each hook receives the user payload of the call."""

    def __init__(self) -> None:
        self.memory: Callable[[str], dict[str, Any]] = lambda _t: {"candidates": []}
        self.router: Callable[[str], dict[str, Any]] = lambda _t: {"kind": "chat"}
        self.chat: Callable[[str], dict[str, Any]] = lambda _t: {"reply": "好的", "used_memory_ids": []}
        self.planner: Callable[[str], dict[str, Any]] = lambda _t: {
            "title": "t", "capabilities": [], "steps": [{"description": "answer", "capability": "memory.read"}]}
        self.executor_steps: list[dict[str, Any]] = []
        self.summarizer: Callable[[str], str] = lambda _t: "完成"
        self.executor_inputs: list[str] = []

    def handler(self, role: ModelRole, messages: list[ChatMessage]) -> str | dict[str, Any]:
        kind = prompt_kind(messages)
        payload = user_payload(messages)
        if kind == "memory_extract":
            return self.memory(payload)
        if kind == "router":
            return self.router(payload)
        if kind == "chat":
            return self.chat(payload)
        if kind == "planner":
            return self.planner(payload)
        if kind == "summarizer":
            return self.summarizer(payload)
        self.executor_inputs.append(payload)
        if not self.executor_steps:
            return {"kind": "finish_step", "summary": "done"}
        return self.executor_steps.pop(0)


def dumps(o: Any) -> str:
    return json.dumps(o, ensure_ascii=False)
