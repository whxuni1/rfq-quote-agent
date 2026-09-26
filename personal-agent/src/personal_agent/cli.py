"""Interactive CLI channel.

Commands: /approve <id> [action_id...] · /reject <id> · /cancel <goal_id> · /goals · /memories
          /forget <memory_id> · /confirm <memory_id> · /audit <goal_id> · /vault-add <service> <scope,...>
          /resume · /quit
"""

from __future__ import annotations

import asyncio
import getpass
import json
import sys

from personal_agent.agent import PersonalAgent
from personal_agent.config import Settings
from personal_agent.ids import new_id
from personal_agent.llm.openai_compat import OpenAICompatClient
from personal_agent.schemas import InboundMessage, OutboundMessage, StructuredAction

_ACTIONS = {"/approve": "approve", "/reject": "reject", "/cancel": "cancel_goal",
            "/forget": "forget_memory", "/confirm": "confirm_memory"}


def _print(msgs: list[OutboundMessage]) -> None:
    for m in msgs:
        print(f"\n🤖 {m.text}")
        if m.used_memory_ids:
            print(f"   (用到的记忆: {', '.join(m.used_memory_ids)})")


async def _loop(agent: PersonalAgent) -> None:
    for g in await agent.goals.resume_all():
        _print(agent.describe_goal(g))
    print("个人 Agent 已启动。输入消息，/help 查看命令，/quit 退出。")
    while True:
        try:
            line = await asyncio.to_thread(input, "\n你> ")
        except (EOFError, KeyboardInterrupt):
            return
        line = line.strip()
        if not line:
            continue
        cmd, *rest = line.split()
        if cmd == "/quit":
            return
        try:
            await _dispatch(agent, line, cmd, rest)
        except Exception as e:  # LLM/network errors must not kill the session; goals stay resumable
            print(f"\n⚠️ 出错了：{type(e).__name__}: {e}（进行中的目标可用 /resume 继续）")


async def _dispatch(agent: PersonalAgent, line: str, cmd: str, rest: list[str]) -> None:
    if cmd == "/help":
        print(__doc__)
    elif cmd in _ACTIONS and rest:
        action = StructuredAction(kind=_ACTIONS[cmd], target_id=rest[0], action_ids=rest[1:])
        _print(await agent.handle(InboundMessage(message_id=new_id("msg"), channel="cli", user_id="me",
                                                 structured_action=action)))
    elif cmd == "/goals":
        for g in agent.goals.list_goals():
            print(f"  {g.goal_id}  [{g.status.value}]  {g.title}")
    elif cmd == "/memories":
        for m in agent.memory.list_items(None):
            flag = "🔒" if m.sensitive else "  "
            print(f"  {flag} {m.memory_id} [{m.status}] {m.subject}.{m.predicate} = {m.value}")
    elif cmd == "/audit" and rest:
        for e in agent.audit.entries(rest[0]):
            print(f"  {e['at']} {e['kind']}: {json.dumps(e['payload'], ensure_ascii=False)[:200]}")
    elif cmd == "/vault-add" and len(rest) == 2:
        if agent.vault is None:
            print("未配置 PA_VAULT_PASSPHRASE")
            return
        raw = getpass.getpass("凭据 JSON（不回显）: ")
        h = agent.vault.put(rest[0], json.loads(raw), rest[1].split(","))
        print(f"  已保存 {h.handle_id} scopes={h.scopes}")
    elif cmd == "/resume":
        for g in await agent.goals.resume_all():
            _print(agent.describe_goal(g))
    else:
        _print(await agent.handle(InboundMessage(message_id=new_id("msg"), channel="cli", user_id="me",
                                                 text=line)))


def main() -> None:
    settings = Settings.from_env()
    try:
        llm = OpenAICompatClient(settings)
    except ValueError as e:
        sys.exit(str(e))
    asyncio.run(_loop(PersonalAgent(settings, llm)))


if __name__ == "__main__":
    main()
