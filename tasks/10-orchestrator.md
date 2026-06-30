# Task 10 — Orchestrator Agent

Status: TODO

## 目标
实现 `agents/orchestrator.py`：pipeline 唯一状态推进者。负责任务理解、sub-agent 调度、gate 触发、装配移交。不直接产生业务数据，只编排。

## 输入
`Blackboard`（status=`ingesting` 完成，含 `rfq_package`）

## 输出文件
- `src/rfq_agent/agents/orchestrator.py`
- `src/rfq_agent/agents/base.py`（生命周期基类）
- `src/rfq_agent/prompts/orchestrator.md`（运行时 LLM system prompt）
- `tests/agents/test_orchestrator.py`

## 状态机实现
```
ingesting → planning → executing → gate_check
gate_check → (no gate) → next_or_assemble
gate_check → (gate) → awaiting_review
awaiting_review → (decision) → gate_check | executing
assembling → done | blocked
```
用 `enum` + `match` 实现，每个转移是显式方法。`status` 字段每次转移记 trace。

## 核心方法

### `async def plan(bb: Blackboard) -> QuoteIntent`
- 读 `rfq_package`，调 LLM 生成 `QuoteIntent`。
- LLM prompt（`prompts/orchestrator.md`）输入：spec_doc 摘要 + bom_tree 统计 + ambiguity_flags + commercial_req_raw。
- 输出 JSON → `QuoteIntent`。校验失败重试 1 次。
- 决定 `skip_agents`：如纯备件项目（`project_type=Spare`）可跳过 engineering；具体规则在 prompt 里给。

### `async def execute(bb: Blackboard) -> None`
- **两波执行**（依赖关系强制）：
  - Wave 1：`asyncio.gather(EngineeringAgent.run(bb), ProcurementAgent.run(bb))` —— 两者仅依赖 `rfq_package` + `quote_intent`。
  - Wave 1 完成、report 写入 Blackboard 后，Wave 2：`asyncio.gather(CommercialAgent.run(bb), FinanceAgent.run(bb))` —— Commercial 需 Eng 的 NRE 工程项；Finance 需 Proc 的 should_cost + Eng 的 NRE。
- 任意 sub-agent 抛 `AgentError` → 记 trace，该 report 留 None，继续同波其他（不阻塞），gate 评估阶段会因 `DATA_MISSING` 触发。Wave 1 某 agent 失败时 Wave 2 仍尝试（依赖字段缺失会触发 DATA_MISSING gate，不抛硬错）。
- 写入 bb 的对应 report 字段。

### `async def check_gates(bb: Blackboard) -> list[ReviewGate]`
- 调 `tools/gate_eval.py` 的 `GateEvaluator.evaluate(bb)`，返回触发的 gate 列表。
- 多 gate → `gates/engine.py` 合并为 `ReviewPacket`。
- 无 gate → 推进到 assembling。

### `async def resume(bb, decision: ReviewDecision) -> None`
- 应用 `GateDecision.override` 修正对应 report 字段（如人工抬 margin、指定替代料）。
- 若决策影响某 sub-agent 的输入（如 override 改了 BOM line），重跑该 sub-agent。
- 重新 `check_gates`，可能再触发（避免震荡：同一 gate_id 第二次触发自动放行并标 `human_overridden`）。

### `async def assemble(bb) -> QuoteDraft`
- 调 `agents/assembler.py`（Task 16）。

## LLM 使用边界
- LLM 只用于 `plan()` 生成 QuoteIntent。**execute/check_gates/resume/assemble 全部确定性**。
- Orchestrator 不读 sub-agent report 的具体内容做判读，只看 presence + gate 信号。

## HiL 注入点
`runner.py` 注入 `reviewer_cb: Callable[[ReviewPacket], Awaitable[ReviewDecision]]`。Orchestrator 在 `awaiting_review` 状态 `await reviewer_cb(packet)`。超时由 `gates/engine.py` 包裹（默认 72h，测试可配短）。

## 验收标准
1. case1（简单 PCBA）：无 gate 触发，pipeline 一气呵成到 `done`。
2. case2（智能座舱核心板）：触发 `SINGLE_SOURCE_CRITICAL`（SoC 单源）+ `MARGIN_FLOOR_BREACH`（margin 测试值设低）→ `awaiting_review` → 注入 mock decision → 恢复 → `done`。
3. case3（ADAS 摄像头）：触发 `SPEC_GAP_HIGH` → 人工 override 指定替代物料 → 重跑 procurement → `done`。
4. 同一 gate 二次触发不阻塞（防震荡）。
5. sub-agent 失败时 `DATA_MISSING` gate 正确触发。
6. `mypy --strict` 通过，`pytest tests/agents/test_orchestrator.py` 全绿。

## 约束
- Orchestrator 不得 import sub-agent 的内部实现，只 import 类名调用。
- 不得在 gate 之外"顺便"调 reviewer_cb。
- 不得跨过 status 状态机（如直接 done）。
