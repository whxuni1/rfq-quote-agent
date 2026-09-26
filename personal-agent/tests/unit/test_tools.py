from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from personal_agent.schemas import ActionRequest, RiskLevel
from personal_agent.store.db import Database
from personal_agent.tools.base import ToolContext
from personal_agent.tools.builtin import register_builtin_tools, web
from personal_agent.tools.registry import ToolRegistry
from personal_agent.tools.runner import ToolRunner
from personal_agent.vault import Vault


class Empty(BaseModel):
    pass


def slow_tool(args: dict[str, Any], ctx: ToolContext) -> None:
    time.sleep(5)


def leaky_tool(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    import os

    creds = ctx.credentials or {}
    return {"echo": f"token is {creds.get('token')}", "env_has_key": "PA_LLM_API_KEY" in os.environ}


def make(tmp_path: Path) -> tuple[ToolRegistry, ToolRunner, Vault]:
    db = Database(tmp_path / "agent.db")
    reg = ToolRegistry()
    register_builtin_tools(reg)
    vault = Vault(db, "pw")
    return reg, ToolRunner(reg, vault, data_dir=str(tmp_path)), vault


def act(tool: str, **args: Any) -> ActionRequest:
    return ActionRequest(action_id="a", goal_id="g", step_id="s", tool=tool, args=args)


async def test_local_tools_in_sandbox(tmp_path: Path) -> None:
    _, runner, _ = make(tmp_path)
    r = await runner.execute(act("todo.add", text="买牛奶"), [])
    assert r.ok, r.error
    r = await runner.execute(act("todo.list"), [])
    assert r.ok and r.output[0]["text"] == "买牛奶"
    r = await runner.execute(act("doc.write", title="SUV 对比", content="| a | b |"), [])
    assert r.ok and Path(r.output["path"]).read_text(encoding="utf-8").startswith("# SUV 对比")
    r = await runner.execute(act("mail.draft", to=["zs@example.com"], subject="会议", body="周二见"), [])
    assert r.ok and "Subject: =?utf-8?" in Path(r.output["draft_path"]).read_text()


async def test_timeout_and_unknown(tmp_path: Path) -> None:
    reg, runner, _ = make(tmp_path)
    reg.register(name="slow", capability="x", risk=RiskLevel.R2, description="", params=Empty,
                 sandboxed_fn="test_tools:slow_tool", timeout_s=1.0)
    r = await runner.execute(act("slow"), [])
    assert not r.ok and "timeout" in (r.error or "")
    assert not (await runner.execute(act("nope"), [])).ok


async def test_credentials_injected_and_redacted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PA_LLM_API_KEY", "should-not-leak")
    reg, runner, vault = make(tmp_path)
    vault.put("svc", {"token": "s3cr3t-token"}, ["svc.use"])
    reg.register(name="leaky", capability="x", risk=RiskLevel.R2, description="", params=Empty,
                 sandboxed_fn="test_tools:leaky_tool", required_scopes=["svc.use"])
    r = await runner.execute(act("leaky"), [])
    assert r.ok and r.output == {"echo": "token is [REDACTED]", "env_has_key": False}


async def test_missing_credential(tmp_path: Path) -> None:
    _, runner, _ = make(tmp_path)
    r = await runner.execute(act("mail.list"), [])
    assert not r.ok and "no credential" in (r.error or "")


def test_registry_guards() -> None:
    reg = ToolRegistry()
    with pytest.raises(ValueError):
        reg.register(name="x", capability="x", risk=RiskLevel.R2, description="", params=Empty, local_fn=lambda a: a)
    with pytest.raises(ValueError):
        reg.register(name="x", capability="x", risk=RiskLevel.R0, description="", params=Empty)


def test_html_to_text() -> None:
    assert web.html_to_text("<p>a&amp;b</p><script>evil()</script> <b>c</b>") == "a&b c"


def test_web_fetch_blocks_redirect_to_unlisted_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "en.wikipedia.org":
            return httpx.Response(302, headers={"location": "https://evil.example/steal"})
        return httpx.Response(200, text="stolen")

    real = httpx.Client
    monkeypatch.setattr(web.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    ctx = ToolContext(data_dir=".", allowed_domains=["wikipedia.org"])
    with pytest.raises(PermissionError):
        web.web_fetch({"url": "https://en.wikipedia.org/wiki/X"}, ctx)


def test_web_fetch_ok_and_search(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search":
            return httpx.Response(200, json={"results": [
                {"title": "T", "url": "https://www.autohome.com.cn/a", "content": "c"}]})
        return httpx.Response(200, text="<h1>Hi</h1>", headers={"content-type": "text/html"})

    real = httpx.Client
    monkeypatch.setattr(web.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(web.httpx, "get", lambda url, **kw: real(transport=httpx.MockTransport(handler)).get(url, **kw))
    ctx = ToolContext(data_dir=".", allowed_domains=["wikipedia.org"], searxng_url="http://searx:8080")
    assert web.web_fetch({"url": "https://en.wikipedia.org/x"}, ctx)["content"] == "Hi"
    out = web.web_search({"query": "suv"}, ctx)
    assert out.discovered_domains == ["autohome.com.cn"]
    with pytest.raises(RuntimeError):
        web.web_search({"query": "suv"}, ToolContext(data_dir="."))
