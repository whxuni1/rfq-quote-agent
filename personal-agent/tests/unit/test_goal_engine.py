from __future__ import annotations

from typing import Any

from pa_testkit import Script

from personal_agent.agent import PersonalAgent
from personal_agent.config import Settings
from personal_agent.goals import apply_event
from personal_agent.llm.fake import FakeLLMClient
from personal_agent.schemas import ApprovalDecision, GoalBudget, GoalStatus


def plan(*steps: tuple[str, str], caps: list[str] | None = None) -> dict[str, Any]:
    return {"title": "目标", "capabilities": caps or [c for _, c in steps],
            "steps": [{"description": d, "capability": c} for d, c in steps]}


async def test_plan_execute_complete(agent: PersonalAgent, script: Script) -> None:
    script.planner = lambda _p: plan(("加待办", "todo.write"), caps=["todo.write", "root.shell"])
    script.executor_steps = [
        {"kind": "call_tool", "tool": "todo.add", "args": {"text": "买牛奶"}},
        {"kind": "finish_step", "summary": "已添加"},
    ]
    script.summarizer = lambda p: "搞定：" + p.split("步骤摘要：")[1].strip()
    g = agent.goals.create("me", "提醒我买牛奶", "买牛奶")
    g = await agent.goals.run(g.goal_id)
    assert g.status == GoalStatus.COMPLETED
    assert g.allowed_capabilities == ["todo.write"]  # unknown capability filtered out
    assert g.actions_used == 1 and g.tokens_used > 0
    assert g.result is not None and "已添加" in g.result
    # projection is reproducible from the event log
    assert agent.goals.load(g.goal_id).model_dump() == g.model_dump()
    assert agent.audit.verify()


async def test_denied_action_is_fed_back_and_replan(agent: PersonalAgent, script: Script) -> None:
    script.planner = lambda _p: plan(("读网页", "web.read"))
    script.executor_steps = [
        {"kind": "call_tool", "tool": "web.fetch", "args": {"url": "https://evil.example/"}},
        {"kind": "replan", "reason": "域名被拒"},
        {"kind": "finish_step", "summary": "改用其他来源"},
    ]
    g = await agent.goals.run(agent.goals.create("me", "查资料", "查资料").goal_id)
    assert g.status == GoalStatus.COMPLETED and g.replans == 1 and g.plan and g.plan.version == 2
    assert "denied: \"Sentinel 拒绝" in script.executor_inputs[1]
    assert g.actions_used == 0  # denied actions don't consume budget


async def test_replan_limit_and_fail(agent: PersonalAgent, script: Script) -> None:
    script.planner = lambda _p: plan(("x", "todo.read"))
    script.executor_steps = [{"kind": "replan", "reason": "r"}] * 5
    g = agent.goals.create("me", "x", "x", GoalBudget(max_replans=1))
    g = await agent.goals.run(g.goal_id)
    assert g.status == GoalStatus.FAILED and g.replans == 1
    script.executor_steps = [{"kind": "fail", "reason": "impossible"}]
    g = await agent.goals.run(agent.goals.create("me", "y", "y").goal_id)
    assert g.status == GoalStatus.FAILED


async def test_action_budget(agent: PersonalAgent, script: Script) -> None:
    script.planner = lambda _p: plan(("列待办", "todo.read"))
    script.executor_steps = [{"kind": "call_tool", "tool": "todo.list", "args": {}}] * 10
    g = agent.goals.create("me", "x", "x", GoalBudget(max_steps=2, max_actions_per_step=10))
    g = await agent.goals.run(g.goal_id)
    assert g.status == GoalStatus.FAILED and g.actions_used == 2


async def test_per_step_action_cap_triggers_replan(agent: PersonalAgent, script: Script) -> None:
    script.planner = lambda _p: plan(("列待办", "todo.read"))
    script.executor_steps = [{"kind": "call_tool", "tool": "todo.list", "args": {}}] * 2
    g = agent.goals.create("me", "x", "x", GoalBudget(max_actions_per_step=2, max_replans=0))
    g = await agent.goals.run(g.goal_id)
    assert g.status == GoalStatus.FAILED


async def test_invalid_planner_output_fails_goal(agent: PersonalAgent, script: Script) -> None:
    script.planner = lambda _p: {"nonsense": True}
    g = await agent.goals.run(agent.goals.create("me", "x", "x").goal_id)
    assert g.status == GoalStatus.FAILED


async def _to_approval(agent: PersonalAgent, script: Script) -> str:
    agent.vault.put("mail", {"username": "me", "password": "pw123456", "smtp_host": "smtp.invalid"},  # type: ignore[union-attr]
                    ["mail.send"])
    script.planner = lambda _p: plan(("发邮件", "mail.send"))
    script.executor_steps = [
        {"kind": "call_tool", "tool": "mail.send",
         "args": {"to": ["zs@example.com"], "subject": "会议", "body": "周二"}},
    ]
    g = await agent.goals.run(agent.goals.create("me", "给张三发邮件", "发邮件").goal_id)
    assert g.status == GoalStatus.WAITING_APPROVAL and g.pending_approval_id
    return g.goal_id


async def test_restart_recovery_and_reject(settings: Settings, script: Script) -> None:
    first = PersonalAgent(settings, FakeLLMClient(script.handler))
    goal_id = await _to_approval(first, script)
    first.db.close()
    # "process restart": brand-new agent on the same database
    second = PersonalAgent(settings, FakeLLMClient(script.handler))
    g = second.goals.load(goal_id)
    assert g.status == GoalStatus.WAITING_APPROVAL
    assert [x.goal_id for x in await second.goals.resume_all()] == []  # waiting goals are not auto-run
    req, decided = second.goals.get_approval(g.pending_approval_id or "") or (None, True)
    assert req is not None and not decided
    script.executor_steps = [{"kind": "finish_step", "summary": "用户拒绝，未发送"}]
    g = await second.goals.decide(ApprovalDecision(request_id=req.request_id,
                                                   decisions={req.actions[0].action_id: "reject"}))
    assert g.status == GoalStatus.COMPLETED
    assert g.step_logs[req.actions[0].step_id][0].outcome == "rejected"
    # a decided approval can't be replayed
    try:
        await second.goals.decide(ApprovalDecision(request_id=req.request_id,
                                                   decisions={req.actions[0].action_id: "approve"}))
        raise AssertionError("expected error")
    except RuntimeError:
        pass


async def test_edited_args_rejudged(agent: PersonalAgent, script: Script) -> None:
    goal_id = await _to_approval(agent, script)
    g = agent.goals.load(goal_id)
    req, _ = agent.goals.get_approval(g.pending_approval_id or "") or (None, None)
    assert req is not None
    aid = req.actions[0].action_id
    script.executor_steps = [{"kind": "finish_step", "summary": "x"}]
    g = await agent.goals.decide(ApprovalDecision(
        request_id=req.request_id, decisions={aid: "approve"}, edited_args={aid: {"to": "not-a-list"}}))
    assert g.step_logs[req.actions[0].step_id][0].outcome == "denied"


async def test_approved_send_executes_and_fails_cleanly(agent: PersonalAgent, script: Script) -> None:
    goal_id = await _to_approval(agent, script)
    g = agent.goals.load(goal_id)
    req, _ = agent.goals.get_approval(g.pending_approval_id or "") or (None, None)
    assert req is not None
    script.executor_steps = [{"kind": "finish_step", "summary": "发送失败"}]
    g = await agent.goals.decide(ApprovalDecision(request_id=req.request_id,
                                                  decisions={req.actions[0].action_id: "approve"}))
    entry = g.step_logs[req.actions[0].step_id][0]
    assert entry.outcome == "error" and "pw123456" not in str(entry.output)  # smtp.invalid unreachable


async def test_cancel_and_resume(agent: PersonalAgent, script: Script) -> None:
    goal_id = await _to_approval(agent, script)
    g = agent.goals.cancel(goal_id)
    assert g.status == GoalStatus.CANCELLED and g.pending_approval_id is None
    assert agent.goals.cancel(goal_id).status == GoalStatus.CANCELLED
    # a goal left in CREATED (crash before planning) is resumed at startup
    script.planner = lambda _p: plan(("x", "todo.read"))
    created = agent.goals.create("me", "x", "x")
    resumed = await agent.goals.resume_all()
    assert [r.goal_id for r in resumed] == [created.goal_id] and resumed[0].status == GoalStatus.COMPLETED


def test_apply_event_requires_created() -> None:
    from personal_agent.schemas import GoalEvent, GoalEventType

    ev = GoalEvent(event_id="e", goal_id="g", seq=1, type=GoalEventType.RESULT, payload={"text": "x"})
    try:
        apply_event(None, ev)
        raise AssertionError("expected error")
    except RuntimeError:
        pass
