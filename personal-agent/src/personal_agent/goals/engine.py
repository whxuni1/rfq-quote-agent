"""Goal Engine: the only component that advances a goal's state.

Event-sourced: every transition is appended to `goal_events`; a Goal is rebuilt by
replaying its events, so a process restart never loses a goal. LLM calls (planner,
executor, summariser) only *propose*; the Sentinel decides and the engine records.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict, deque
from typing import Any

from personal_agent.audit import AuditLog
from personal_agent.ids import new_id
from personal_agent.llm import ChatMessage, LLMClient, StructuredOutputError, complete_structured
from personal_agent.llm_outputs import PlanOutput, StepDecision
from personal_agent.log import get_logger
from personal_agent.memory import MemoryService, format_memories
from personal_agent.netpolicy import host_of, is_private_host, registrable_domain, urls_in
from personal_agent.prompts import load_prompt
from personal_agent.schemas import (
    TERMINAL_STATUSES,
    ActionRequest,
    ApprovalDecision,
    ApprovalRequest,
    Goal,
    GoalBudget,
    GoalEvent,
    GoalEventType,
    GoalStatus,
    Plan,
    PlanStep,
    SentinelVerdict,
    StepLogEntry,
    ToolResult,
)
from personal_agent.schemas.common import utcnow
from personal_agent.schemas.goals import Outcome
from personal_agent.sentinel import SentinelContext, judge, sanitize_capabilities
from personal_agent.store.db import Database
from personal_agent.tools.registry import ToolRegistry
from personal_agent.tools.runner import ToolRunner

E = GoalEventType
_RESUMABLE = (GoalStatus.CREATED, GoalStatus.PLANNING, GoalStatus.REPLANNING, GoalStatus.RUNNING)


class GoalEngineError(RuntimeError):
    pass


# --------------------------------------------------------------------------------------
# Projection (pure): events -> Goal
# --------------------------------------------------------------------------------------
def apply_event(goal: Goal | None, ev: GoalEvent) -> Goal:
    p = ev.payload
    if ev.type == E.CREATED:
        return Goal(
            goal_id=ev.goal_id, user_id=p["user_id"], title=p["title"], original_request=p["request"],
            allowed_capabilities=[], budget=GoalBudget.model_validate(p["budget"]),
            allowed_domains=p.get("allowed_domains", []), created_at=ev.at,
        )
    if goal is None:
        raise GoalEngineError(f"event {ev.type} before CREATED for {ev.goal_id}")
    match ev.type:
        case E.STATUS_CHANGED:
            goal.status = GoalStatus(p["to"])
            if goal.status == GoalStatus.REPLANNING:
                goal.replans += 1
        case E.PLAN_CREATED:
            goal.plan = Plan.model_validate(p["plan"])
            goal.title = p.get("title", goal.title)
            goal.allowed_capabilities = p["capabilities"]
            goal.current_step = 0
        case E.STEP_STARTED:
            goal.step_logs.setdefault(p["step_id"], [])
        case E.STEP_FINISHED:
            goal.step_summaries[p["step_id"]] = p["summary"]
            goal.current_step += 1
        case E.ACTION_RESOLVED:
            entry = StepLogEntry.model_validate(p["entry"])
            goal.step_logs.setdefault(p["step_id"], []).append(entry)
            if entry.outcome in ("ok", "error"):
                goal.actions_used += 1
            for d in p.get("discovered_domains", []):
                if d not in goal.allowed_domains:
                    goal.allowed_domains.append(d)
        case E.APPROVAL_REQUESTED:
            goal.pending_approval_id = p["request_id"]
        case E.APPROVAL_DECIDED:
            goal.pending_approval_id = None
        case E.TOKENS_USED:
            goal.tokens_used += int(p["tokens"])
        case E.RESULT:
            goal.result = p["text"]
        case E.ACTION_JUDGED:
            pass
    return goal


class GoalEngine:
    def __init__(
        self,
        db: Database,
        llm: LLMClient,
        registry: ToolRegistry,
        runner: ToolRunner,
        memory: MemoryService,
        audit: AuditLog,
        *,
        egress_allowlist: list[str],
        memory_recall_limit: int = 12,
    ) -> None:
        self._db = db
        self._llm = llm
        self._registry = registry
        self._runner = runner
        self._memory = memory
        self._audit = audit
        self._egress = egress_allowlist
        self._recall_limit = memory_recall_limit
        self._calls: dict[str, deque[float]] = defaultdict(deque)

    # ---- event store -------------------------------------------------------------------
    def _events(self, goal_id: str) -> list[GoalEvent]:
        rows = self._db.conn.execute(
            "SELECT * FROM goal_events WHERE goal_id=? ORDER BY seq", (goal_id,)
        ).fetchall()
        return [
            GoalEvent(event_id=r["event_id"], goal_id=r["goal_id"], seq=r["seq"], type=GoalEventType(r["type"]),
                      payload=json.loads(r["payload"]), at=r["at"])
            for r in rows
        ]

    def _emit(self, goal: Goal | None, goal_id: str, type_: GoalEventType, payload: dict[str, Any]) -> Goal:
        row = self._db.conn.execute(
            "SELECT COALESCE(MAX(seq), 0) AS s FROM goal_events WHERE goal_id=?", (goal_id,)
        ).fetchone()
        ev = GoalEvent(event_id=new_id("ev"), goal_id=goal_id, seq=int(row["s"]) + 1, type=type_, payload=payload)
        self._db.conn.execute(
            "INSERT INTO goal_events (goal_id, seq, event_id, type, payload, at) VALUES (?,?,?,?,?,?)",
            (goal_id, ev.seq, ev.event_id, ev.type.value,
             json.dumps(payload, ensure_ascii=False, default=str), ev.at.isoformat()),
        )
        return apply_event(goal, ev)

    def _status(self, goal: Goal, to: GoalStatus, reason: str = "") -> Goal:
        get_logger("goal_engine", goal_id=goal.goal_id).info("status", frm=goal.status, to=to, reason=reason)
        self._audit.append("goal_status", {"from": goal.status, "to": to, "reason": reason}, goal.goal_id)
        return self._emit(goal, goal.goal_id, E.STATUS_CHANGED, {"from": goal.status, "to": to, "reason": reason})

    def load(self, goal_id: str) -> Goal:
        goal: Goal | None = None
        for ev in self._events(goal_id):
            goal = apply_event(goal, ev)
        if goal is None:
            raise GoalEngineError(f"unknown goal {goal_id}")
        return goal

    def list_goals(self) -> list[Goal]:
        ids = [r["goal_id"] for r in self._db.conn.execute("SELECT DISTINCT goal_id FROM goal_events")]
        return sorted((self.load(i) for i in ids), key=lambda g: g.created_at)

    def get_approval(self, request_id: str) -> tuple[ApprovalRequest, bool] | None:
        row = self._db.conn.execute("SELECT body, decided FROM approvals WHERE request_id=?", (request_id,)).fetchone()
        return (ApprovalRequest.model_validate_json(row["body"]), bool(row["decided"])) if row else None

    # ---- public API --------------------------------------------------------------------
    def create(self, user_id: str, request: str, title: str, budget: GoalBudget | None = None) -> Goal:
        goal_id = new_id("goal")
        # URLs the user typed themselves are trusted destinations for this goal.
        domains = sorted({registrable_domain(h) for u in urls_in(request)
                          if (h := host_of(u)) and not is_private_host(h)})
        goal = self._emit(None, goal_id, E.CREATED, {
            "user_id": user_id, "title": title, "request": request,
            "budget": (budget or GoalBudget()).model_dump(), "allowed_domains": domains,
        })
        self._audit.append("goal_created", {"title": title, "request": request}, goal_id)
        return goal

    async def run(self, goal_id: str) -> Goal:
        """Advance the goal until it completes, fails, or needs the user."""
        goal = self.load(goal_id)
        while goal.status not in TERMINAL_STATUSES and goal.status != GoalStatus.WAITING_APPROVAL:
            if goal.status in (GoalStatus.CREATED, GoalStatus.PLANNING, GoalStatus.REPLANNING):
                goal = await self._plan(goal)
            elif goal.status == GoalStatus.RUNNING:
                goal = await self._tick(goal)
            else:  # SLEEPING: woken by the scheduler (v0.2)
                break
        return goal

    async def resume_all(self) -> list[Goal]:
        """Called at startup: continue every goal interrupted mid-flight."""
        return [await self.run(g.goal_id) for g in self.list_goals() if g.status in _RESUMABLE]

    def cancel(self, goal_id: str) -> Goal:
        goal = self.load(goal_id)
        if goal.status in TERMINAL_STATUSES:
            return goal
        if goal.pending_approval_id:
            self._db.conn.execute("UPDATE approvals SET decided=1 WHERE request_id=?", (goal.pending_approval_id,))
            goal = self._emit(goal, goal_id, E.APPROVAL_DECIDED, {"request_id": goal.pending_approval_id,
                                                                  "cancelled": True})
        return self._status(goal, GoalStatus.CANCELLED, "cancelled by user")

    async def decide(self, decision: ApprovalDecision) -> Goal:
        found = self.get_approval(decision.request_id)
        if found is None:
            raise GoalEngineError(f"unknown approval {decision.request_id}")
        req, decided = found
        goal = self.load(req.goal_id)
        if decided or goal.pending_approval_id != req.request_id:
            raise GoalEngineError(f"approval {req.request_id} is no longer pending")
        self._db.conn.execute("UPDATE approvals SET decided=1 WHERE request_id=?", (req.request_id,))
        self._audit.append("approval_decided", decision.model_dump(mode="json"), goal.goal_id)
        goal = self._emit(goal, goal.goal_id, E.APPROVAL_DECIDED, decision.model_dump(mode="json"))
        for action in req.actions:
            choice = decision.decisions.get(action.action_id, "reject")
            if choice == "reject":
                goal = self._resolve(goal, action, "rejected", "用户拒绝了该操作")
                continue
            if action.action_id in decision.edited_args:
                # Edited arguments are a new action: they must pass the Sentinel again.
                action = action.model_copy(update={"args": decision.edited_args[action.action_id]})
                verdict = self._judge(goal, action)
                if verdict.decision == "deny":
                    goal = self._resolve(goal, action, "denied", verdict.reason)
                    continue
            goal = await self._execute(goal, action)
        goal = self._status(goal, GoalStatus.RUNNING, "approval decided")
        return await self.run(goal.goal_id)

    # ---- planning ----------------------------------------------------------------------
    async def _plan(self, goal: Goal) -> Goal:
        replanning = goal.status == GoalStatus.REPLANNING
        if goal.status == GoalStatus.CREATED:
            goal = self._status(goal, GoalStatus.PLANNING)
        memories = self._memory.recall(goal.original_request, self._recall_limit)
        context = {
            "goal": goal.original_request,
            "available_tools": self._registry.describe(),
            "user_memories": format_memories(memories),
        }
        if replanning and goal.plan:
            context["completed_step_summaries"] = [
                goal.step_summaries[s.step_id] for s in goal.plan.steps if s.step_id in goal.step_summaries
            ]
            context["replan_reason"] = self._last_replan_reason(goal)
        msgs = [
            ChatMessage(role="system", content=load_prompt("planner")),
            ChatMessage(role="user", content=json.dumps(context, ensure_ascii=False)),
        ]
        try:
            out, tokens = await complete_structured(self._llm, msgs, PlanOutput, role="planner")
        except StructuredOutputError as e:
            return self._status(goal, GoalStatus.FAILED, f"planner output invalid: {e}")
        goal = self._emit(goal, goal.goal_id, E.TOKENS_USED, {"tokens": tokens})
        version = (goal.plan.version + 1) if goal.plan else 1
        caps = sanitize_capabilities(out.capabilities + [s.capability for s in out.steps], self._registry)
        steps = [
            PlanStep(step_id=f"v{version}s{i + 1}", description=s.description, capability=s.capability,
                     success_criteria=s.success_criteria)
            for i, s in enumerate(out.steps)
        ]
        plan = Plan(version=version, steps=steps, rationale=out.rationale)
        goal = self._emit(goal, goal.goal_id, E.PLAN_CREATED, {
            "plan": plan.model_dump(), "capabilities": caps, "title": out.title or goal.title,
            "used_memory_ids": [m.memory_id for m in memories],
        })
        self._audit.append("plan_created", {"plan": plan.model_dump(), "capabilities": caps}, goal.goal_id)
        return self._status(goal, GoalStatus.RUNNING, "plan ready")

    def _last_replan_reason(self, goal: Goal) -> str:
        for ev in reversed(self._events(goal.goal_id)):
            if ev.type == E.STATUS_CHANGED and ev.payload.get("to") == GoalStatus.REPLANNING:
                return str(ev.payload.get("reason", ""))
        return ""

    # ---- execution ---------------------------------------------------------------------
    async def _tick(self, goal: Goal) -> Goal:
        assert goal.plan is not None
        if goal.current_step >= len(goal.plan.steps):
            return await self._finish(goal)
        if goal.actions_used >= goal.budget.max_steps:
            return self._status(goal, GoalStatus.FAILED, f"动作预算耗尽（{goal.budget.max_steps} 次）")
        if goal.tokens_used >= goal.budget.max_llm_tokens:
            return self._status(goal, GoalStatus.FAILED, f"token 预算耗尽（{goal.budget.max_llm_tokens}）")

        step = goal.plan.steps[goal.current_step]
        if step.step_id not in goal.step_logs:
            goal = self._emit(goal, goal.goal_id, E.STEP_STARTED, {"step_id": step.step_id})
        if len(goal.step_logs[step.step_id]) >= goal.budget.max_actions_per_step:
            limit = goal.budget.max_actions_per_step
            return self._replan_or_fail(goal, f"步骤 {step.step_id} 超过 {limit} 次动作仍未完成")

        try:
            decision, tokens = await complete_structured(
                self._llm, self._executor_messages(goal, step), StepDecision, role="planner"
            )
        except StructuredOutputError as e:
            return self._status(goal, GoalStatus.FAILED, f"executor output invalid: {e}")
        goal = self._emit(goal, goal.goal_id, E.TOKENS_USED, {"tokens": tokens})

        match decision.kind:
            case "finish_step":
                return self._emit(goal, goal.goal_id, E.STEP_FINISHED,
                                  {"step_id": step.step_id, "summary": decision.summary})
            case "replan":
                return self._replan_or_fail(goal, decision.reason)
            case "fail":
                return self._status(goal, GoalStatus.FAILED, decision.reason or "executor gave up")
            case "call_tool":
                action = ActionRequest(action_id=new_id("act"), goal_id=goal.goal_id, step_id=step.step_id,
                                       tool=decision.tool or "", args=decision.args)
                verdict = self._judge(goal, action)
                if verdict.decision == "deny":
                    return self._resolve(goal, action, "denied", f"Sentinel 拒绝：{verdict.reason}")
                if verdict.decision == "needs_approval":
                    return self._request_approval(goal, action, verdict)
                return await self._execute(goal, action)
        raise GoalEngineError(f"unhandled decision {decision.kind}")  # pragma: no cover

    def _replan_or_fail(self, goal: Goal, reason: str) -> Goal:
        if goal.replans >= goal.budget.max_replans:
            return self._status(goal, GoalStatus.FAILED, f"重规划次数用尽：{reason}")
        return self._status(goal, GoalStatus.REPLANNING, reason)

    def _executor_messages(self, goal: Goal, step: PlanStep) -> list[ChatMessage]:
        assert goal.plan is not None
        log_lines = []
        for e in goal.step_logs.get(step.step_id, []):
            tool = self._registry.get(e.tool)
            out = json.dumps(e.output, ensure_ascii=False, default=str)
            if e.outcome == "ok" and tool is not None and tool.untrusted_output:
                out = f"<untrusted_tool_output>{out}</untrusted_tool_output>"
            log_lines.append(f"- {e.tool}({json.dumps(e.args, ensure_ascii=False)}) → {e.outcome}: {out}")
        context = {
            "original_goal": goal.original_request,
            "plan": [f"{s.step_id}: {s.description}" for s in goal.plan.steps],
            "completed_step_summaries": {k: v for k, v in goal.step_summaries.items()},
            "current_step": step.model_dump(),
            "tools_for_this_goal": self._registry.describe(goal.allowed_capabilities),
            "user_memories": format_memories(self._memory.recall(goal.original_request, self._recall_limit)),
        }
        return [
            ChatMessage(role="system", content=load_prompt("executor")),
            ChatMessage(role="user", content=json.dumps(context, ensure_ascii=False)
                        + "\n\n本步骤已执行的动作：\n" + ("\n".join(log_lines) or "（无）")),
        ]

    def _judge(self, goal: Goal, action: ActionRequest) -> SentinelVerdict:
        now = time.monotonic()
        recent = {}
        for name, q in self._calls.items():
            while q and now - q[0] > 60:
                q.popleft()
            recent[name] = len(q)
        ctx = SentinelContext(
            allowed_capabilities=goal.allowed_capabilities,
            allowed_domains=sorted(set(self._egress) | set(goal.allowed_domains)),
            sensitive_values=self._memory.sensitive_values(),
            recent_calls_last_min=recent,
        )
        verdict = judge(action, self._registry, ctx)
        self._emit(goal, goal.goal_id, E.ACTION_JUDGED,
                   {"action": action.model_dump(), "verdict": verdict.model_dump(mode="json")})
        self._audit.append("sentinel", {"action": action.model_dump(), "verdict": verdict.model_dump(mode="json")},
                           goal.goal_id)
        get_logger("sentinel", goal_id=goal.goal_id, step_id=action.step_id).info(
            "verdict", tool=action.tool, decision=verdict.decision, rules=verdict.matched_rules)
        return verdict

    def _request_approval(self, goal: Goal, action: ActionRequest, verdict: SentinelVerdict) -> Goal:
        req = ApprovalRequest(
            request_id=new_id("apr"), goal_id=goal.goal_id, actions=[action], verdicts=[verdict],
            human_summary=f"{action.tool} {json.dumps(action.args, ensure_ascii=False)}（原因：{verdict.reason}）",
        )
        self._db.conn.execute("INSERT INTO approvals (request_id, goal_id, body, decided) VALUES (?,?,?,0)",
                              (req.request_id, goal.goal_id, req.model_dump_json()))
        self._audit.append("approval_requested", req.model_dump(mode="json"), goal.goal_id)
        goal = self._emit(goal, goal.goal_id, E.APPROVAL_REQUESTED, {"request_id": req.request_id})
        return self._status(goal, GoalStatus.WAITING_APPROVAL, verdict.reason)

    async def _execute(self, goal: Goal, action: ActionRequest) -> Goal:
        self._calls[action.tool].append(time.monotonic())
        allowed = sorted(set(self._egress) | set(goal.allowed_domains))
        result: ToolResult = await self._runner.execute(action, allowed)
        self._audit.append("tool_result", {"action_id": action.action_id, "tool": action.tool, "ok": result.ok,
                                           "error": result.error, "truncated": result.truncated}, goal.goal_id)
        return self._resolve(goal, action, "ok" if result.ok else "error",
                             result.output if result.ok else result.error, result.discovered_domains)

    def _resolve(self, goal: Goal, action: ActionRequest, outcome: Outcome, output: Any,
                 discovered: list[str] | None = None) -> Goal:
        entry = StepLogEntry(action_id=action.action_id, tool=action.tool, args=action.args,
                             outcome=outcome, output=output)
        return self._emit(goal, goal.goal_id, E.ACTION_RESOLVED, {
            "step_id": action.step_id, "entry": entry.model_dump(mode="json"),
            "discovered_domains": discovered or [],
        })

    async def _finish(self, goal: Goal) -> Goal:
        assert goal.plan is not None
        summaries = "\n".join(f"{s.step_id} {s.description}: {goal.step_summaries.get(s.step_id, '')}"
                              for s in goal.plan.steps)
        memories = format_memories(self._memory.recall(goal.original_request, self._recall_limit))
        resp = await self._llm.chat([
            ChatMessage(role="system", content=load_prompt("summarizer")),
            ChatMessage(role="user", content=f"用户目标：{goal.original_request}\n\n用户相关记忆：\n{memories}"
                                             f"\n\n步骤摘要：\n{summaries}"),
        ], role="chat")
        goal = self._emit(goal, goal.goal_id, E.TOKENS_USED, {"tokens": resp.tokens})
        goal = self._emit(goal, goal.goal_id, E.RESULT, {"text": resp.content, "at": utcnow().isoformat()})
        return self._status(goal, GoalStatus.COMPLETED, "all steps finished")
