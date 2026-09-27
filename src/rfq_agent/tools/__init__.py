"""确定性纯函数工具层。零网络、零 LLM 依赖；不得 import agents/ 或 llm/。"""


class ToolError(Exception):
    """工具层业务异常基类。"""
