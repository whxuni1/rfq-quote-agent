"""确定性 mock LLM：按顺序回放固定响应，并记录收到的消息，供测试断言。"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from rfq_agent.llm.base import LLMError, Message


class MockLLMClient:
    def __init__(self, responses: Sequence[str]) -> None:
        self._responses = list(responses)
        self.calls: list[list[dict[str, str]]] = []

    @classmethod
    def from_file(cls, path: str | Path) -> MockLLMClient:
        """从 JSON 文件加载回放序列：顶层为数组，元素为字符串或任意 JSON（会被序列化）。"""
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError(f"{path}: 回放文件顶层必须是数组")
        return cls([r if isinstance(r, str) else json.dumps(r, ensure_ascii=False) for r in raw])

    async def chat(self, messages: Sequence[Message]) -> str:
        self.calls.append([dict(m) for m in messages])
        if not self._responses:
            raise LLMError("MockLLMClient: 回放响应已耗尽")
        return self._responses.pop(0)
