# Task 13 — Finance Agent

Status: TODO

## 目标
实现 `agents/finance.py`：汇总成本、算 margin、定支付里程碑、评估 working capital 与 warranty reserve，产出 `FinanceReport`。**全部确定性计算，零 LLM**。

## 输入
`RFQPackage` + `QuoteIntent` + `ProcurementReport`（依赖其 should_cost_lines）+ `EngineeringReport`（依赖其 nre_engineering）

## 输出文件
- `src/rfq_agent/agents/finance.py`
- `src/rfq_agent/tools/cost_rollup.py`
- `src/rfq_agent/prompts/finance.md`（仅说明文档，运行时不调 LLM）
- `tests/unit/test_cost_rollup.py`
- `tests/agents/test_finance.py`

## 计算规范（`tools/cost_rollup.py` + agent 内逻辑）

### CostRollup
自底向上遍历 BOMTree，对每个叶子节点取 `ShouldCostLine`：
```
material_total   = Σ leaf.material_cost × qty_per_chain
processing_total = Σ leaf.processing_cost × qty_per_chain
overhead_total   = Σ leaf.overhead × qty_per_chain
supplier_margin_total = Σ leaf.supplier_margin × qty_per_chain
logistics_total  = ProcurementReport.logistics_cost_estimate
nre_total        = Σ EngineeringReport.nre_engineering.cost + CommercialReport.nre（商务NRE后续合并）
piece_price_total = material + processing + overhead + supplier_margin + logistics
```
- `qty_per_chain` = 从 root 到叶子的 qty_per 乘积。
- 中间组装件无 should-cost（非采购件），不重复计算。

### Margin
```
proposed_unit_price = piece_price_total × (1 + target_margin_pct)
proposed_margin_pct = target_margin_pct（默认）
```
- `target_margin_pct` 从 `QuoteIntent` 或配置读取（默认 15%）。
- 若 `proposed_margin_pct < target_margin_pct`（被人工 override 压低）→ `margin_floor_breached=True`，触发 gate。
- 可设 `margin_floor_pct`（默认 8%），低于此值拒绝输出，强制 gate。

### Total Project Value
```
total_project_value = nre_total + piece_price_total × annual_volume × project_life_years
```
量纲缺失时按 `peak_monthly_volume × 12 × project_life_years` 退化；都缺 → gate `DATA_MISSING`。

### Payment Milestones
按 `project_type` 模板：
- NPI+Mass：NRE 30% 预付 / 30% DV / 40% PV；mass 按月结 60 天。
- Mass_only：月结 60 天。
- Spare：款到发货。
模板表常量，可配置。

### Working Capital Impact
```
working_capital_impact = (piece_price_total × peak_monthly_volume × payment_terms_days/30) 
                        - (material_total × peak_monthly_volume × supplier_payment_days/30)
```
- `payment_terms_days` 从 QuoteIntent 或默认 60。
- `supplier_payment_days` 默认 45。
- 负值 = 我方现金流有利，正值 = 垫资。

### Warranty Reserve
```
warranty_reserve_pct = base(0.5%) × severity_multiplier
```
- severity_multiplier 由 risk_register 的 critical/high 数量驱动（规则表）。
- 进入成本（计入 piece_price 的 overhead 项），不单列。

### FX
- 若 `QuoteIntent.currency` 与基准价表币种不同 → `FXAssumption(pair, rate, hedge_horizon)`。
- 汇率从配置读（不联网），hedge horizon = 项目寿命。

## LLM 边界
**Finance Agent 不调 LLM**。`prompts/finance.md` 只是文档说明计算逻辑，便于人工审计。

## 验收标准
1. case2 座舱：piece_price、NRE、total_project_value 与金样例 ±2%（确定性，应严格匹配）。
2. margin floor 测试：人为压 margin 到 5% → `margin_floor_breached=True`。
3. working capital：case1 月结 60 vs 供应商 45 → 正值（垫资）。
4. FX：QuoteIntent.currency=USD 且基准 CNY → 生成 FXAssumption。
5. `test_cost_rollup.py` 覆盖：单层/多层 BOM、qty_per 链乘积、缺 should_cost 叶子报错。
6. `mypy --strict` 通过。

## 约束
- 不得用 LLM 生成任何数字。
- 不得跳过 margin_floor 检查。
- 所有金额 Decimal，精度 4 位，禁用 float。
- `total_project_value` 量纲缺失不得默认 0，必须 gate。
