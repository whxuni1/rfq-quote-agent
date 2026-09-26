"""Sentinel: deterministic action guard. Pure function of (request, tool spec, context).

It never trusts the LLM's description of an action; only the registered ToolSpec and the
concrete arguments. Rules run in order; the first `deny` wins, otherwise the strictest
of allow < needs_approval.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import Field, ValidationError

from personal_agent.netpolicy import domain_allowed, host_of, is_private_host, urls_in
from personal_agent.schemas.actions import ActionRequest, Decision, RiskLevel, SentinelVerdict
from personal_agent.schemas.common import Frozen
from personal_agent.tools.registry import ToolRegistry


class SentinelContext(Frozen):
    allowed_capabilities: list[str]
    allowed_domains: list[str]  # global allowlist ∪ domains discovered in this goal
    sensitive_values: list[str] = Field(default_factory=list)
    recent_calls_last_min: dict[str, int] = Field(default_factory=dict)  # tool -> count


_ORDER: dict[Decision, int] = {"allow": 0, "needs_approval": 1, "deny": 2}


class _Acc:
    def __init__(self) -> None:
        self.decision: Decision = "allow"
        self.rules: list[str] = []
        self.reasons: list[str] = []

    def hit(self, rule: str, decision: Decision, reason: str) -> None:
        self.rules.append(rule)
        if decision != "allow":
            self.reasons.append(reason)
        if _ORDER[decision] > _ORDER[self.decision]:
            self.decision = decision


def _contains_sensitive(args: dict[str, Any], values: list[str]) -> bool:
    blob = json.dumps(args, ensure_ascii=False).lower()
    return any(v and v.lower() in blob for v in values)


def judge(req: ActionRequest, registry: ToolRegistry, ctx: SentinelContext) -> SentinelVerdict:
    acc = _Acc()
    tool = registry.get(req.tool)

    def verdict(risk: RiskLevel) -> SentinelVerdict:
        return SentinelVerdict(
            action_id=req.action_id, decision=acc.decision, risk=risk, matched_rules=acc.rules,
            reason="; ".join(acc.reasons) or "ok",
        )

    # 1. tool exists, args valid
    if tool is None:
        acc.hit("TOOL_UNKNOWN", "deny", f"未注册的工具 {req.tool}")
        return verdict(RiskLevel.R4)
    spec = tool.spec
    try:
        tool.params.model_validate(req.args)
    except ValidationError as e:
        acc.hit("ARGS_INVALID", "deny", f"参数不合法: {e.errors()[0]['msg']}")
        return verdict(spec.risk)

    # 2. capability granted to this goal
    if spec.capability not in ctx.allowed_capabilities:
        acc.hit("CAPABILITY_NOT_GRANTED", "deny", f"目标未授权能力 {spec.capability}")
        return verdict(spec.risk)

    # 3. egress: every URL in args must be public and allowlisted
    if spec.network:
        for url in urls_in(req.args):
            host = host_of(url)
            if is_private_host(host):
                acc.hit("EGRESS_PRIVATE_HOST", "deny", f"禁止访问内网/本机地址 {host}")
            elif not domain_allowed(host, ctx.allowed_domains):
                acc.hit("EGRESS_NOT_ALLOWLISTED", "deny", f"域名 {host} 不在白名单或本目标搜索结果中")
        if acc.decision == "deny":
            return verdict(spec.risk)
        acc.hit("EGRESS_OK", "allow", "")

    # 4. sensitive data leaving the machine
    if (spec.network or spec.risk >= RiskLevel.R3) and _contains_sensitive(req.args, ctx.sensitive_values):
        acc.hit("SENSITIVE_DATA_EGRESS", "needs_approval", "参数包含敏感个人信息，将发往外部")

    # 5. rate limit
    if ctx.recent_calls_last_min.get(spec.name, 0) >= spec.rate_limit_per_min:
        acc.hit("RATE_LIMIT", "deny", f"{spec.name} 超过每分钟 {spec.rate_limit_per_min} 次")
        return verdict(spec.risk)

    # 6. risk policy
    if spec.risk >= RiskLevel.R3:
        acc.hit(f"RISK_R{int(spec.risk)}_APPROVAL", "needs_approval", f"R{int(spec.risk)} 动作需用户批准")
    else:
        acc.hit(f"RISK_R{int(spec.risk)}_ALLOW", "allow", "")
    return verdict(spec.risk)




def sanitize_capabilities(proposed: list[str], registry: ToolRegistry) -> list[str]:
    known = set(registry.capabilities())
    return sorted({c for c in proposed if c in known})
