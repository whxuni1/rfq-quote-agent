# 00 — 系统架构

## 1. Agent 拓扑

```
                ┌─────────────────┐
                │  IngestionParser│  纯工具+LLM理解混合
                │  PDF/XLSX →结构 │
                └────────┬────────┘
                         │ RFQPackage + BOMTree
                         ▼
                ┌─────────────────┐   人工决策
                │   Orchestrator  │◄─────► ReviewGateEngine
                │  (LLM 编排核心) │      (HiL)
                └──┬───┬───┬───┬──┘
                   │   │   │   │      并行分发（asyncio）
              ┌────┘   │   │   └────┐
              ▼        ▼   ▼        ▼
          EngAgent  Proc FinAgent  ComAgent
              │        │   │        │
              └────────┴───┴────────┘
                         │ 写入
                         ▼
                   ┌──────────┐
                   │Blackboard│  各 agent 产出累积
                   └────┬─────┘
                        │
                        ▼
                ┌─────────────────┐
                │ QuoteAssembler  │  确定性装配
                └────────┬────────┘
                         ▼
                   QuoteDraft
```

## 2. 数据流与控制流

- **Ingestion** 一次完成，产出 `RFQPackage`（含 `BOMTree`、`SpecDoc`、`DrawingRefs`、`AmbiguityFlags`）。
- **Orchestrator** 读 RFQPackage → 生成 `QuoteIntent`（报价意图：项目类型、量纲、币种、交付条件、特殊要求）→ 决定 sub-agent 调用图（默认 4 个全开，特殊项目可跳过某项）。
- **Sub-agent 两波执行**（依赖关系决定，非全并行）：
  - Wave 1：`EngineeringAgent` + `ProcurementAgent` 并行（仅依赖 `RFQPackage` + `QuoteIntent`）
  - Wave 2：`CommercialAgent`（需 Eng 的 NRE 工程项）+ `FinanceAgent`（需 Proc 的 should_cost + Eng 的 NRE）并行
  - 用 `asyncio.gather` 跑每波；Wave 1 完成且 report 写入 Blackboard 后才启动 Wave 2。
- **Review Gates**：Wave 2 完成后，Orchestrator 用 `GateEvaluator` 评估是否触发 HiL gate。触发则**暂停整个 pipeline**，生成 `ReviewPacket` 等待人工；人工返回 `ReviewDecision` 后恢复；若 override 影响某 sub-agent 输入则重跑该 sub-agent（可能触发 Wave 1 或 Wave 2 重跑）。
- **Assembler**：所有 gate 关闭后，Assembler 读 Blackboard 全量 → 渲染 `QuoteDraft`。

## 3. Blackboard 结构

中央共享状态（Pydantic 模型，`rfq_id` 唯一）：
```python
class Blackboard(BaseModel):
    rfq_id: str
    rfq_package: RFQPackage
    quote_intent: QuoteIntent | None
    eng_report: EngineeringReport | None
    proc_report: ProcurementReport | None
    fin_report: FinanceReport | None
    com_report: CommercialReport | None
    review_gates: list[ReviewGate]
    decision_log: list[ReviewDecision]
    status: Literal["ingesting","planning","executing","awaiting_review","assembling","done","blocked"]
```
单实例，sub-agent 只读 `rfq_package` + 自己的输入区，只写自己的 report 区。Orchestrator 是唯一 status 推进者。

## 4. HiL 状态机

```
executing ──sub-agent done──► gate_check
gate_check ──no gate──► next_or_assemble
gate_check ──gate triggered──► awaiting_review
awaiting_review ──ReviewDecision──► gate_check (重评估) 或 executing (重跑受影响agent)
```

- Gate 触发条件见 `tasks/17-human-loop.md`，硬编码在 `GateEvaluator`（确定性规则，非 LLM）。
- 人工决策超时（默认 72h）→ status 转 `blocked`，QuoteDraft 标记 `incomplete_reason`。
- 多 gate 同时触发：合并成一个 `ReviewPacket`，避免多次打断人工。

## 5. 确定性边界（哪些走 LLM，哪些不走）

| 环节 | LLM | 工具/规则 |
|---|---|---|
| RFQ PDF 文本抽取 | ✗（pdf 解析器） | ✓ |
| BOM Excel 解析 | ✗ | ✓ |
| BOM 多层级识别、物料归类 | ✓（理解层） | 辅助规则 |
| 任务理解/QuoteIntent 生成 | ✓ | — |
| Should-cost 单行计算 | ✗ | ✓ 参数化模型 |
| 成本汇总 | ✗ | ✓ |
| 风险识别（spec gap、单源、长周期） | ✓（判读） | 规则触发器 |
| Margin 计算、working capital | ✗ | ✓ |
| 商务条款匹配/缺口 | ✓ | 规则库 |
| Gate 触发判定 | ✗ | ✓ 纯规则 |
| 报价函文案 | ✓（渲染层） | 模板 + LLM 润色 |
| QuoteDraft 结构装配 | ✗ | ✓ |

原则：**任何影响数字的地方禁用 LLM**。LLM 只做理解、拆分、判读、文案。

## 6. 错误处理

- Ingestion 解析失败 → 不进入 pipeline，直接返回 `IngestionError` 给调用方，列出失败页/行。
- Sub-agent LLM 调用失败 → 重试 2 次（指数退避），仍失败则该 agent 产出 `AgentError`，Orchestrator 决定是否触发"数据缺失"gate 让人工补。
- 工具层异常 → 不吞，向上抛，测试必须覆盖。
- schema 校验失败 → 拒绝写入 Blackboard。

## 7. 可观测性

每个 sub-agent 调用产出 `AgentTrace`：输入摘要、LLM 调用次数/token、工具调用序列、产出哈希。Trace 落 `QuoteDraft.review_trail`，便于人工评审与事后复盘。

## 8. 并发模型

`asyncio`。Sub-agent 并行用 `asyncio.gather`。LLM 调用走异步客户端。工具层同步函数包 `asyncio.to_thread`。禁止多进程（确定性 + 可复现）。
