"""Runtime settings, read from PA_* environment variables."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import Field

from personal_agent.schemas.common import Frozen

ModelRole = Literal["planner", "router", "memory", "chat"]

DEEPSEEK_BASE_URL = "https://api.deepseek.com"


class Settings(Frozen):
    llm_base_url: str = DEEPSEEK_BASE_URL
    llm_api_key: str = ""
    models: dict[str, str] = Field(
        default_factory=lambda: {
            "planner": "deepseek-v4-pro",
            "router": "deepseek-flash",
            "memory": "deepseek-flash",
            "chat": "deepseek-flash",
        }
    )
    data_dir: Path = Path("~/.personal-agent").expanduser()
    searxng_url: str = ""
    egress_allowlist: list[str] = Field(default_factory=list)
    vault_passphrase: str = ""
    memory_recall_limit: int = 12

    @property
    def db_path(self) -> Path:
        return self.data_dir / "agent.db"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        e = dict(os.environ) if env is None else env
        defaults = cls()
        models = dict(defaults.models)
        for role in ("planner", "router", "memory", "chat"):
            if v := e.get(f"PA_MODEL_{role.upper()}"):
                models[role] = v
        allow = [d.strip().lower() for d in e.get("PA_EGRESS_ALLOWLIST", "").split(",") if d.strip()]
        return cls(
            llm_base_url=e.get("PA_LLM_BASE_URL", DEEPSEEK_BASE_URL),
            llm_api_key=e.get("PA_LLM_API_KEY", e.get("DEEPSEEK_API_KEY", "")),
            models=models,
            data_dir=Path(e.get("PA_DATA_DIR", "~/.personal-agent")).expanduser(),
            searxng_url=e.get("PA_SEARXNG_URL", ""),
            egress_allowlist=allow,
            vault_passphrase=e.get("PA_VAULT_PASSPHRASE", ""),
        )
