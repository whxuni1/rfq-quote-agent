"""Default tool catalogue."""

from __future__ import annotations

from personal_agent.schemas.actions import RiskLevel
from personal_agent.tools.builtin.local import DocWriteParams, MailDraftParams, TodoAddParams, TodoListParams
from personal_agent.tools.builtin.mail import MailListParams, MailSendParams
from personal_agent.tools.builtin.web import WebFetchParams, WebSearchParams
from personal_agent.tools.registry import ToolRegistry

_M = "personal_agent.tools.builtin"


def register_builtin_tools(reg: ToolRegistry) -> None:
    reg.register(
        name="web.search", capability="web.read", risk=RiskLevel.R1, network=True, untrusted_output=True,
        description="用自托管 SearXNG 搜索网页，返回标题/URL/摘要", params=WebSearchParams,
        sandboxed_fn=f"{_M}.web:web_search",
    )
    reg.register(
        name="web.fetch", capability="web.read", risk=RiskLevel.R1, network=True, untrusted_output=True,
        description="读取一个网页的正文文本（域名须在白名单或搜索结果中）", params=WebFetchParams,
        sandboxed_fn=f"{_M}.web:web_fetch",
    )
    reg.register(
        name="todo.add", capability="todo.write", risk=RiskLevel.R2,
        description="添加一条待办", params=TodoAddParams, sandboxed_fn=f"{_M}.local:todo_add",
    )
    reg.register(
        name="todo.list", capability="todo.read", risk=RiskLevel.R0,
        description="列出待办", params=TodoListParams, sandboxed_fn=f"{_M}.local:todo_list",
    )
    reg.register(
        name="doc.write", capability="doc.write", risk=RiskLevel.R2,
        description="把 markdown 文档保存到本地（报告、对比表等交付物）", params=DocWriteParams,
        sandboxed_fn=f"{_M}.local:doc_write",
    )
    reg.register(
        name="mail.draft", capability="mail.draft", risk=RiskLevel.R2,
        description="保存一封邮件草稿到本地（不发送）", params=MailDraftParams,
        sandboxed_fn=f"{_M}.local:mail_draft",
    )
    reg.register(
        name="mail.list", capability="mail.read", risk=RiskLevel.R1, network=True, untrusted_output=True,
        description="列出邮箱最近邮件的发件人/主题/日期", params=MailListParams,
        sandboxed_fn=f"{_M}.mail:mail_list", required_scopes=["mail.read"],
    )
    reg.register(
        name="mail.send", capability="mail.send", risk=RiskLevel.R3, network=True,
        description="发送邮件（必须经用户审批）", params=MailSendParams,
        sandboxed_fn=f"{_M}.mail:mail_send", required_scopes=["mail.send"],
    )
