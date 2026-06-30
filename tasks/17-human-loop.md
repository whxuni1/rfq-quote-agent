# Task 17 — Human-in-Loop Review Gate Engine

Status: TODO

## 目标
实现 `gates/engine.py` + `tools/gate_eval.py`：确定性 gate 触发、合并、暂停/恢复、超时、防震荡。**全规则化，零 LLM**。

## 输出文件
- `src/rfq_agent/gates/engine.py`
- `src/rfq_agent/tools/gate_eval.py`
- `tests/unit/test_gate_eval.py`
- `tests/agents/test_gate_flow.py`

## Gate 触发规则（`tools/gate_eval.py`）

`GateEvaluator.evaluate(bb: Blackboard) -> list[ReviewGate]`，纯函数。读 Blackboard 现状返回所有触发 gate。

| GateType | 触发条件 | 默认 severity |
|---|---|---|
| `MARGIN_FLOOR_BREACH` | `FinanceReport.margin_floor_breached=True` 或 `proposed_margin_pct < margin_floor_pct` | critical |
| `SINGLE_SOURCE_CRITICAL` | 任一 `material_class ∈ {SOC, DISPLAY, CAMERA}` 且 `supplier_landscape=single` | high |
| `SPEC_GAP_HIGH` | `EngineeringReport.spec_gaps` 中任一 `gap_severity=high` | high |
| `NRE_SCOPE_LARGE` | `nre_total > nre_threshold`（默认 500k） | medium |
| `WARRANTY_BEYOND_STANDARD` | `CommercialReport.warranty_terms.months > standard`（默认 36）或 mileage > 标准 | high |
| `TERM_GAP_CRITICAL` | `CommercialReport.term_gaps` 中任一 `severity=critical` | critical |
| `INGESTION_AMBIGUITY_HIGH` | `RFQPackage.ambiguity_flags` 中任一 `severity=high` 且未在后续解决 | high |
| `DATA_MISSING` | 任一 sub-agent report 为 None 或关键字段缺失 | high |

每个 gate 的 `context` 必须序列化安全（JSON-able），含触发依据的具体字段值。

## Gate Engine（`gates/engine.py`）

### 合并
```python
def build_packet(gates: list[ReviewGate], rfq_id: str) -> ReviewPacket
```
- 一次 `evaluate` 返回的所有 gate 合并为单个 `ReviewPacket`，避免多次打断人工。
- 空 gate 列表 → 返回 None（不创建空 packet）。

### 暂停/恢复
- Orchestrator 在 `gate_check` 状态调 `build_packet`；非 None → status 转 `awaiting_review`，`await reviewer_cb(packet)`。
- `reviewer_cb` 返回 `ReviewDecision` → Orchestrator 调 `apply_decision(bb, decision)`。
- `apply_decision`：对每个 `GateDecision`：
  - `chosen_option` 决定动作（accept / reject / override / escalate）
  - `override` 字典应用到对应 report（如 `{proposed_margin_pct: 0.12}`）
  - 标记 gate 为 `human_overridden`（写 decision_log）
- 恢复后 Orchestrator 重跑 `check_gates`。

### 防震荡
- 同一 `gate_id` 第二次触发 → 自动放行（不创建新 gate），trace 标 `auto_overridden_after_human`。
- 防止人工决策与规则冲突导致无限循环。

### 超时
- `reviewer_cb` 由 runner 包裹 `asyncio.wait_for`，超时（默认 72h，可配）→ status 转 `blocked`，`QuoteDraft.incomplete_reason="review_timeout: <packet_id>"`。
- 测试用超短超时（如 0.1s）验证。

## Gate 选项模板
每类 gate 提供标准候选选项：
- `MARGIN_FLOOR_BREACH`: ["接受低 margin 并附条件", "提价至 target margin", "拒绝报价"]
- `SINGLE_SOURCE_CRITICAL`: ["接受单源风险", "指定备选料并重跑采购", "客户分摊备选料 NRE"]
- `SPEC_GAP_HIGH`: ["按我方能力降级报价并声明", "要求客户放宽规格", "停止报价"]
- ...（每类 2-4 选项）

## 验收标准
1. case2：触发 `SINGLE_SOURCE_CRITICAL` + `MARGIN_FLOOR_BREACH`，合并为 1 个 packet，人工选 override margin → 重跑后 gate 不再触发。
2. case3：触发 `SPEC_GAP_HIGH`，人工选"指定替代物料"→ override 改 BOM line → 重跑 procurement → gate 关闭。
3. 防震荡测试：人为构造持续触发的 margin gate → 第二次自动放行。
4. 超时测试：mock reviewer_cb sleep > timeout → status 转 blocked。
5. `DATA_MISSING`：置 eng_report=None → 触发，options 含["人工补工程评审","停止报价"]。
6. `test_gate_eval.py` 覆盖 8 类 gate 触发/不触发。
7. `mypy --strict` 通过。

## 约束
- Gate 触发判定 100% 规则化，禁用 LLM。
- Gate 不得修改 sub-agent 产出，只读 + 标记。
- `apply_decision` 的 override 必须类型校验（Pydantic），非法 override 报错而非静默应用。
- 一次 packet 必须含至少 1 个 gate，不允许空 packet。
