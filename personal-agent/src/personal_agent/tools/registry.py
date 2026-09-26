from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from personal_agent.schemas.actions import RiskLevel, ToolSpec
from personal_agent.tools.base import LocalFn, Tool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(
        self,
        *,
        name: str,
        capability: str,
        risk: RiskLevel,
        description: str,
        params: type[BaseModel],
        sandboxed_fn: str | None = None,
        local_fn: LocalFn | None = None,
        network: bool = False,
        required_scopes: list[str] | None = None,
        untrusted_output: bool = False,
        timeout_s: float = 30.0,
        rate_limit_per_min: int = 30,
    ) -> None:
        if (sandboxed_fn is None) == (local_fn is None):
            raise ValueError(f"{name}: set exactly one of sandboxed_fn / local_fn")
        if local_fn is not None and (risk > RiskLevel.R0 or network):
            raise ValueError(f"{name}: in-process tools must be R0 and offline")
        spec = ToolSpec(
            name=name,
            capability=capability,
            risk=risk,
            description=description,
            params_schema=params.model_json_schema(),
            required_scopes=required_scopes or [],
            network=network,
            timeout_s=timeout_s,
            rate_limit_per_min=rate_limit_per_min,
        )
        self._tools[name] = Tool(
            spec=spec, params=params, sandboxed_fn=sandboxed_fn, local_fn=local_fn,
            untrusted_output=untrusted_output,
        )

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def capabilities(self) -> list[str]:
        return sorted({t.spec.capability for t in self._tools.values()})

    def describe(self, capabilities: list[str] | None = None) -> list[dict[str, Any]]:
        """Tool catalogue for the LLM (optionally filtered to a goal's capabilities)."""
        return [
            {
                "name": t.spec.name,
                "capability": t.spec.capability,
                "risk": f"R{int(t.spec.risk)}",
                "description": t.spec.description,
                "params": t.spec.params_schema.get("properties", {}),
            }
            for t in sorted(self._tools.values(), key=lambda t: t.spec.name)
            if capabilities is None or t.spec.capability in capabilities
        ]
