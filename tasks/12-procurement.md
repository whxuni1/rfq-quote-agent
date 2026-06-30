# Task 12 — Procurement Agent

Status: TODO

## 目标
实现 `agents/procurement.py`：对 BOM 每行做 should-cost，评估供应商landscape、leadtime、MOQ，产出 `ProcurementReport`。**所有成本数字走确定性工具，LLM 仅做物料分类复核与风险描述**。

## 输入
`RFQPackage` + `QuoteIntent`

## 输出文件
- `src/rfq_agent/agents/procurement.py`
- `src/rfq_agent/tools/should_cost.py`
- `src/rfq_agent/tools/risk_rules.py`（采购侧规则触发器）
- `src/rfq_agent/prompts/procurement.md`
- `tests/unit/test_should_cost.py`
- `tests/unit/test_risk_rules.py`
- `tests/agents/test_procurement.py`

## should_cost 参数化模型（`tools/should_cost.py`）

每行 `ShouldCostLine` 由 5 项构成：
```
unit_price = material_cost + processing_cost + overhead + supplier_margin
```

### `material_cost`
- 按 `material_class` 查内置基准价表（`COMMODITY_PRICE_TABLE`，常量，含 SoC/$/颗、DDR/$/GB、Display/$/inch、PCB/$/dm²、Connector/$/pin 等）。
- 物料属性修正：容量/速率/尺寸 → 系数（如 DDR 容量翻倍 ×1.8，速率等级 ×1.1）。
- 基准价表是**内部知识库**（纯文档进文档出约束下，硬编码常量 + 可选 CSV 加载），非外部 API。

### `processing_cost`
- PCBA：按焊点数 × 单点贴片成本 + 钢网 + AOI。
- 结构件：注塑周期 × 机器费率 / 模穴数 + 后处理。
- 线束：按长度 × 单位长加工费 + 端子压接。
- 规则表常量。

### `overhead`
- 工厂管理费率 = `processing_cost × 0.15`（可配置）。

### `supplier_margin`
- 默认 8%，关键件（SoC/Display/Camera）12%，长尾件 5%。规则表。

### `lead_time_weeks`
- 按 material_class + 是否单源查表。SoC 28-40w、Display 18-26w、PCB 8-12w、结构件 10-16w（含开模）。
- 单源且高需求 → 取上限。

### `moq` / `supplier_landscape` / `confidence`
- MOQ 按物料类别查表（SoC 1000、电阻 10000、PCB 500...）。
- landscape：source_hint 含厂商名且无备选 → `single`；2 个 → `dual`；>2 → `multi`；空 → `open`。
- confidence：基准价匹配高、需大量属性外推 → low。

## LLM 使用（`prompts/procurement.md`）
- 仅用于：复核 Ingestion 的 `material_class` 分类（如误把 SoC 归 MCU）、撰写 `long_lead_items`/`single_source_items` 的风险描述文案。
- **不参与任何数字计算**。
- 输出 JSON：`{reclassifications: [...], risk_descriptions: [...]}`。

## 风险规则触发器（`tools/risk_rules.py`）
本任务实现采购侧规则，输出 `RiskItem` 列表（供 Orchestrator 汇总到 `risk_register`）：
- `SINGLE_SOURCE`：material_class ∈ {SOC, DISPLAY, CAMERA} 且 landscape=single → critical
- `LONG_LEAD`：lead_time_weeks > 26 → high
- `MOQ`：moq > peak_monthly_volume × 2 → medium
- `AUTO_GRADE`：auto_grade_required 且供应商未认证 → high
（gate 触发由 `gate_eval.py` 在 Task 17 实现，这里只产 RiskItem）

## 验收标准
1. case2 座舱：SoC 行 `single_source_risk=True`、leadtime 28-40w、material_cost 来自基准价表 ×属性系数。整 BOM roll-up 后 piece_price 与金样例 ±5%。
2. case3 摄像头：sensor + ISP + 镜头 三件 should-cost，镜头按光学件规则（口径/焦距系数）。
3. case1 简单 PCBA：无单源、无长周期，confidence 全 high。
4. `test_should_cost.py` 覆盖：每个 material_class、属性系数、margin 档位、边界（qty=0 报错）。
5. `test_risk_rules.py` 覆盖：4 类规则触发/不触发。
6. LLM 用 mock，单测确定性。`mypy --strict` 通过。

## 约束
- 不得调外部询价 API。
- 不得让 LLM 输出任何金额、leadtime、MOQ 数字。
- 基准价表必须可配置（常量 + 可选 CSV override 路径），便于人工调参。
- should_cost 是估算，`confidence=low` 的行必须在 `procurement_assumptions` 里说明依据薄弱。
