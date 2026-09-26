# Personal Agent（对标 Meta Muse）— 设计文档集

Status: v0.1 已实现（代码见 `../src/personal_agent/`）

本目录是**独立子项目 `personal-agent/`** 的设计文档：构建一个与 Meta Muse 同类的"个人 AI Agent"。
它与本仓库主线 RFQ 报价 Agent 共用工程规范（Pydantic v2、LLM 抽象层、HiL gate 思路、eval 驱动），但**不共享运行时代码**，也不受 RFQ 项目"纯文档进文档出"约束（决策见 `00-product-and-scope.md` §6）。

| 文档 | 内容 |
|---|---|
| `00-product-and-scope.md` | Muse 能力拆解、对标矩阵、MVP 范围、非目标 |
| `01-architecture.md` | 运行时拓扑、目标引擎、长任务、LLM 抽象（OpenAI 兼容） |
| `02-schemas.md` | 跨模块 Pydantic 模型 |
| `03-safety-sentinel.md` | Sentinel 守卫、动作风险分级、凭据保险库、审计 |
| `04-memory.md` | 个人记忆：写入、召回、遗忘、用户可见性 |
| `05-roadmap.md` | 里程碑与任务拆分（后续可落成 `tasks/pa-*.md`） |

阅读顺序：00 → 01 → 03 → 04 → 02 → 05。
