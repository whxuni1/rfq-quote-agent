"""Executes approved ActionRequests: in-process for R0 local reads, otherwise in a
scrubbed-environment subprocess with a timeout. Resolves vault credentials, redacts
secrets and truncates output before anything reaches the LLM."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

from personal_agent.schemas.actions import ActionRequest, ToolResult
from personal_agent.tools.base import Tool, ToolContext
from personal_agent.tools.registry import ToolRegistry
from personal_agent.vault import Vault, VaultError, redact, secret_values

MAX_OUTPUT_CHARS = 8000
_PASSTHROUGH_ENV = ("PATH", "LANG", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "SSL_CERT_FILE",
                    "REQUESTS_CA_BUNDLE", "https_proxy", "http_proxy", "no_proxy")


def _truncate(value: Any) -> tuple[Any, bool]:
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= MAX_OUTPUT_CHARS:
        return value, False
    return text[:MAX_OUTPUT_CHARS] + "…[truncated]", True


class ToolRunner:
    def __init__(self, registry: ToolRegistry, vault: Vault | None, *, data_dir: str, searxng_url: str = "") -> None:
        self._registry = registry
        self._vault = vault
        self._data_dir = data_dir
        self._searxng_url = searxng_url

    async def execute(self, req: ActionRequest, allowed_domains: list[str]) -> ToolResult:
        tool = self._registry.get(req.tool)
        if tool is None:
            return ToolResult(action_id=req.action_id, ok=False, error=f"unknown tool {req.tool}")
        args = tool.params.model_validate(req.args).model_dump(mode="json")
        trust = "untrusted" if tool.untrusted_output else "trusted"

        if tool.local_fn is not None:
            try:
                out, trunc = _truncate(tool.local_fn(args))
                return ToolResult(action_id=req.action_id, ok=True, output=out, truncated=trunc, trust=trust)
            except Exception as e:
                return ToolResult(action_id=req.action_id, ok=False, error=f"{type(e).__name__}: {e}")

        creds: dict[str, Any] | None = None
        if tool.spec.required_scopes:
            try:
                creds = self._credentials_for(tool)
            except VaultError as e:
                return ToolResult(action_id=req.action_id, ok=False, error=str(e))
        ctx = ToolContext(
            data_dir=self._data_dir, allowed_domains=allowed_domains,
            searxng_url=self._searxng_url, credentials=creds,
        )
        resp = await self._run_worker(tool, args, ctx)
        secrets = secret_values(creds or {})
        if not resp.get("ok"):
            return ToolResult(action_id=req.action_id, ok=False, error=redact(str(resp.get("error")), secrets))
        out, trunc = _truncate(redact(resp.get("output"), secrets))
        return ToolResult(
            action_id=req.action_id, ok=True, output=out, truncated=trunc, trust=trust,
            discovered_domains=resp.get("discovered_domains", []),
        )

    def _credentials_for(self, tool: Tool) -> dict[str, Any]:
        if self._vault is None:
            raise VaultError("vault not configured")
        handle = self._vault.find(tool.spec.required_scopes[0])
        if handle is None:
            raise VaultError(f"no credential with scope {tool.spec.required_scopes[0]}")
        return self._vault.resolve(handle.handle_id, tool.spec.required_scopes)

    async def _run_worker(self, tool: Tool, args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
        env = {k: os.environ[k] for k in _PASSTHROUGH_ENV if k in os.environ}
        env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
        payload = json.dumps({"fn": tool.sandboxed_fn, "args": args, "ctx": ctx.model_dump(mode="json")})
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-u", "-m", "personal_agent.tools.worker",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=env, cwd=self._data_dir,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(payload.encode()), timeout=tool.spec.timeout_s)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return {"ok": False, "error": f"timeout after {tool.spec.timeout_s}s"}
        if proc.returncode != 0:
            return {"ok": False, "error": f"worker exited {proc.returncode}: {err.decode()[-500:]}"}
        result: dict[str, Any] = json.loads(out.decode())
        return result
