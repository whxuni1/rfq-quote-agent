# 架构

本文件是阅读地图。拓扑与状态机的细则在 `00-architecture.md`，目录与依赖方向在 `01-repo-structure.md`，字段在 `02-shared-schemas.md`。三者冲突时以编号文档为准。`.cursor/` 只约束代理怎么干活，不增加运行时模块。

## 路径

```
RFQ PDF + XLSX
        │
        ▼
 IngestionParser ──► RFQPackage + BOMTree
        │
        ▼
 Orchestrator ── QuoteIntent ── 两波分发 ── HiL gate ── 装配
        │
        ├── Wave 1   EngineeringAgent ∥ ProcurementAgent
        │
        ├── Wave 2   CommercialAgent ∥ FinanceAgent
        │
        ▼
 Blackboard ── GateEvaluator ── QuoteAssembler ── QuoteDraft
```

Ingestion 只跑一次。Orchestrator 读 `RFQPackage` 生成 `QuoteIntent`，再决定是否跳过某个 sub-agent。

Wave 1 只依赖 RFQ 与报价意图。Wave 2 等 Wave 1 的 report 写入 Blackboard：商务需要工程 NRE，财务需要 should-cost 和工程 NRE。同一波用 `asyncio.gather`。不使用多进程。

## Blackboard

一份 RFQ 一份 Blackboard，以 `rfq_id` 标识。它保存 RFQ、报价意图、四份 report、风险登记、gate、人工决策、trace 和 status。Sub-agent 只写自己的 report。status 只由 Orchestrator 改动。除 Blackboard 外，跨模块模型保持 frozen。

status：`ingesting` → `planning` → `executing` → `awaiting_review` 或 `assembling` → `done` 或 `blocked`。

## 人工回路

`GateEvaluator` 用硬编码规则读 Blackboard，不用模型。多个 gate 合成一个 `ReviewPacket`。人工返回 `ReviewDecision` 后重评估；覆盖影响某 agent 的输入时，重跑该 agent 及其下游波次。72 小时无决策则 `blocked`，草稿填 `incomplete_reason`。

Gate 类型：`MARGIN_FLOOR_BREACH`、`SINGLE_SOURCE_CRITICAL`、`SPEC_GAP_HIGH`、`NRE_SCOPE_LARGE`、`WARRANTY_BEYOND_STANDARD`、`TERM_GAP_CRITICAL`、`INGESTION_AMBIGUITY_HIGH`、`DATA_MISSING`。

## 谁计算，谁判读

| 环节 | 承担者 |
|---|---|
| PDF 抽取、Excel BOM、should-cost、成本汇总、毛利与营运资金 | 工具 |
| Gate 是否触发、QuoteDraft 装配 | 规则与装配器 |
| BOM 归类、报价意图、规格与条款缺口判读、报价函措辞 | 模型 |
| 风险 | 规则触发器加模型判读；触发器可独立成立 |

模型调用收口在 `src/rfq_agent/llm/`。Sub-agent 不直接使用供应商 SDK。

## 失败

解析失败返回 `IngestionError`，不进入流水线。模型失败重试 2 次，仍失败则该 report 留空并走 `DATA_MISSING`。工具异常向上抛。Schema 校验失败拒绝写入 Blackboard。

每次 sub-agent 调用留下 `AgentTrace`：输入摘要、模型次数与 token、工具序列、产出哈希，写入 `Blackboard.trace`。人工决策进入 `QuoteDraft.review_trail`。`00-architecture.md` 把 trace 也记在评审轨迹上；字段落点以 `02-shared-schemas.md` 为准。
