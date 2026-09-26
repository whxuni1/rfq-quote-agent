from __future__ import annotations

from functools import cache
from importlib.resources import files


@cache
def load_prompt(name: str) -> str:
    return (files("personal_agent.prompts") / f"{name}.md").read_text(encoding="utf-8")
