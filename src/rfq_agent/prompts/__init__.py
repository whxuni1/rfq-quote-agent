"""运行时 LLM system prompt 资产。"""

from functools import cache
from importlib.resources import files


@cache
def load_prompt(name: str) -> str:
    """按名称读取 `prompts/<name>.md`。"""
    return files(__name__).joinpath(f"{name}.md").read_text(encoding="utf-8")
