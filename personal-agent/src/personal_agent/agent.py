"""PersonalAgent: wires everything together and handles one inbound message at a time."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from personal_agent.audit import AuditLog
from personal_agent.config import Settings
from personal_agent.goals import GoalEngine
from personal_agent.llm import ChatMessage, LLMClient, StructuredOutputError, complete_structured
from personal_agent.llm_outputs import ChatReply, RouteDecision
from personal_agent.memory import MemoryService, format_memories
from personal_agent.prompts import load_prompt
from personal_agent.schemas import (
    ApprovalDecision,
    Goal,
    GoalStatus,
    InboundMessage,
    OutboundMessage,
    RiskLevel,
    StructuredAction,
)
from personal_agent.store.db import Database
from personal_agent.tools.builtin import register_builtin_tools
from personal_agent.tools.registry import ToolRegistry
from personal_agent.tools.runner import ToolRunner
from personal_agent.vault import Vault


class MemorySearchParams(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=8, ge=1, le=20)


class PersonalAgent:
    def __init__(self, settings: Settings, llm: LLMClient, db: Database | None = None) -> None:
        self.settings = settings
        self.llm = llm
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.db = db or Database(settings.db_path)
        self.audit = AuditLog(self.db)
        self.memory = MemoryService(self.db)
        self.vault = Vault(self.db, settings.vault_passphrase) if settings.vault_passphrase else None
        self.registry = ToolRegistry()
        register_builtin_tools(self.registry)
        self.registry.register(
            name="memory.search", capability="memory.read", risk=RiskLevel.R0,
            description="检索用户的个人记忆（事实、偏好）", params=MemorySearchParams,
            local_fn=lambda a: [
                m.model_dump(include={"memory_id", "subject", "predicate", "value"})
                for m in self.memory.recall(a["query"], a["limit"])
            ],
        )
        self.runner = ToolRunner(self.registry, self.vault, data_dir=str(settings.data_dir),
                                 searxng_url=settings.searxng_url)
        self.goals = GoalEngine(
            self.db, llm, self.registry, self.runner, self.memory, self.audit,
            egress_allowlist=settings.egress_allowlist, memory_recall_limit=settings.memory_recall_limit,
        )

    # ---- entry point -------------------------------------------------------------------
    async def handle(self, msg: InboundMessage) -> list[OutboundMessage]:
        if msg.structured_action is not None:
            return await self._handle_action(msg.structured_action)
        if not msg.text.strip():
            return []
        out: list[OutboundMessage] = []
        try:
            stored, _ = await self.memory.extract_from_user(self.llm, msg.text)
        except StructuredOutputError:
            stored = []
        if stored:
            out.append(OutboundMessage(
                text="已记住：" + "；".join(f"{m.predicate}={m.value}" for m in stored),
                used_memory_ids=[m.memory_id for m in stored],
            ))
        route = await self._route(msg.text)
        if route.kind == "new_goal":
            goal = self.goals.create(msg.user_id, msg.text, route.goal_title or msg.text[:20])
            goal = await self.goals.run(goal.goal_id)
            out.extend(self.describe_goal(goal, include_plan=True))
        else:
            out.append(await self._chat(msg.text))
        return out

    async def _route(self, text: str) -> RouteDecision:
        msgs = [ChatMessage(role="system", content=load_prompt("router")),
                ChatMessage(role="user", content=text)]
        try:
            route, _ = await complete_structured(self.llm, msgs, RouteDecision, role="router")
        except StructuredOutputError:
            return RouteDecision(kind="chat")
        return route

    async def _chat(self, text: str) -> OutboundMessage:
        memories = self.memory.recall(text, self.settings.memory_recall_limit)
        pending = [g for g in self.goals.list_goals() if g.status == GoalStatus.WAITING_APPROVAL]
        ctx = f"用户相关记忆：\n{format_memories(memories)}\n\n待审批目标数：{len(pending)}\n\n用户消息：{text}"
        msgs = [ChatMessage(role="system", content=load_prompt("chat")), ChatMessage(role="user", content=ctx)]
        try:
            reply, _ = await complete_structured(self.llm, msgs, ChatReply, role="chat")
        except StructuredOutputError:
            return OutboundMessage(text="抱歉，我这次没能生成回复。")
        known = {m.memory_id for m in memories}
        return OutboundMessage(text=reply.reply, used_memory_ids=[i for i in reply.used_memory_ids if i in known])

    async def _handle_action(self, a: StructuredAction) -> list[OutboundMessage]:
        match a.kind:
            case "approve" | "reject":
                found = self.goals.get_approval(a.target_id)
                if found is None:
                    return [OutboundMessage(text=f"找不到审批 {a.target_id}")]
                req, _ = found
                chosen = set(a.action_ids) or {x.action_id for x in req.actions}
                decisions = {x.action_id: (a.kind if x.action_id in chosen else "reject") for x in req.actions}
                goal = await self.goals.decide(ApprovalDecision(request_id=req.request_id,
                                                                decisions=decisions))
                return self.describe_goal(goal)
            case "cancel_goal":
                return self.describe_goal(self.goals.cancel(a.target_id))
            case "confirm_memory":
                m = self.memory.confirm(a.target_id)
                return [OutboundMessage(text=f"已确认记忆 {m.memory_id}" if m else "没有这条待确认记忆")]
            case "forget_memory":
                ok = self.memory.forget(a.target_id)
                self.audit.append("memory_forgotten", {"memory_id": a.target_id})
                return [OutboundMessage(text="已删除" if ok else "没有这条记忆")]
        return []  # pragma: no cover

    # ---- presentation ------------------------------------------------------------------
    def describe_goal(self, goal: Goal, include_plan: bool = False) -> list[OutboundMessage]:
        out: list[OutboundMessage] = []
        if include_plan and goal.plan:
            steps = "\n".join(f"  {i + 1}. {s.description} [{s.capability}]" for i, s in enumerate(goal.plan.steps))
            out.append(OutboundMessage(
                goal_id=goal.goal_id,
                text=(f"目标「{goal.title}」({goal.goal_id})\n"
                      f"授权能力：{', '.join(goal.allowed_capabilities)}\n计划：\n{steps}"),
            ))
        if goal.status == GoalStatus.WAITING_APPROVAL and goal.pending_approval_id:
            found = self.goals.get_approval(goal.pending_approval_id)
            assert found is not None
            req, _ = found
            lines = [f"⚠️ 需要你批准（{req.request_id}）："]
            for act, v in zip(req.actions, req.verdicts, strict=True):
                lines.append(f"  - [R{int(v.risk)}] {act.tool} {json.dumps(act.args, ensure_ascii=False)}")
                lines.append(f"    原因：{v.reason}；规则：{', '.join(v.matched_rules)}")
            lines.append(f"用 /approve {req.request_id} 或 /reject {req.request_id} 决定。")
            out.append(OutboundMessage(goal_id=goal.goal_id, approval_request_id=req.request_id, text="\n".join(lines)))
        elif goal.status == GoalStatus.COMPLETED:
            out.append(OutboundMessage(goal_id=goal.goal_id, text=goal.result or "完成。"))
        elif goal.status in (GoalStatus.FAILED, GoalStatus.CANCELLED):
            reason = self._last_reason(goal)
            out.append(OutboundMessage(goal_id=goal.goal_id, text=f"目标{goal.status.value}：{reason}"))
        return out

    def _last_reason(self, goal: Goal) -> str:
        entries = [e for e in self.audit.entries(goal.goal_id) if e["kind"] == "goal_status"]
        return str(entries[-1]["payload"].get("reason", "")) if entries else ""

    def data_path(self, *parts: str) -> Path:
        return self.settings.data_dir.joinpath(*parts)
