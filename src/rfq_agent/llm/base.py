"""LLMClient 抽象。sub-agent 只依赖本协议，不直接 import 任何厂商 SDK。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

# 消息格式与主流 chat API 一致：{"role": "system"|"user"|"assistant", "content": "..."}
Message = Mapping[str, str]


class LLMError(Exception):
    """LLM 调用失败（网络、限流、空响应等）。"""


class LLMClient(Protocol):
    async def chat(self, messages: Sequence[Message]) -> str:
        """发送一轮对话，返回 assistant 文本。"""
        ...
