from __future__ import annotations

from collections.abc import Iterator

import pytest
from pa_testkit import Script

from personal_agent import cli
from personal_agent.agent import PersonalAgent


async def test_cli_session(agent: PersonalAgent, script: Script, monkeypatch: pytest.MonkeyPatch,
                           capsys: pytest.CaptureFixture[str]) -> None:
    script.memory = lambda t: {"candidates": [
        {"type": "fact", "subject": "user", "predicate": "allergy", "value": "花生", "evidence": t}]}
    script.router = lambda t: {"kind": "new_goal", "goal_title": "待办"} if "待办" in t else {"kind": "chat"}
    script.planner = lambda _p: {"title": "待办", "capabilities": ["todo.write"],
                                 "steps": [{"description": "加", "capability": "todo.write"}]}
    script.executor_steps = [{"kind": "call_tool", "tool": "todo.add", "args": {"text": "x"}},
                             {"kind": "finish_step", "summary": "ok"}]
    lines: Iterator[str] = iter([
        "", "/help", "我对花生过敏", "加个待办", "/goals", "/memories", "/audit nothing",
        "/vault-add mail mail.read", "/resume", "/forget nope", "/quit",
    ])
    monkeypatch.setattr("builtins.input", lambda _p="": next(lines))
    monkeypatch.setattr(cli.getpass, "getpass", lambda _p="": '{"password": "pw-12345"}')
    await cli._loop(agent)
    out = capsys.readouterr().out
    assert "已记住" in out and "[completed]" in out and "🔒" in out and "已保存 cred_" in out
    assert "没有这条记忆" in out and "pw-12345" not in out


def test_main_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PA_LLM_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(SystemExit):
        cli.main()
