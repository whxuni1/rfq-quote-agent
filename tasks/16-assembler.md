# Task 16 — Quote Assembler

Status: TODO

## 目标
实现 `agents/assembler.py`：读 Blackboard 全量产出，确定性装配为 `QuoteDraft`。**零 LLM 用于结构装配**；仅在 `QuoteLetter.summary` 文案处可选 LLM 润色（mock 可关）。

## 输入
`Blackboard`（status=`assembling`，所有 report 齐备 + gates 全关闭）

## 输出文件
- `src/rfq_agent/agents/assembler.py`
- `src/rfq_agent/tools/render.py`
- `tests/agents/test_assembler.py`

## 装配步骤

### 1. 风险汇总
- 从 4 个 report 各自的风险信号 + `tools/risk_rules.py` 产出的 RiskItem 合并为 `RiskRegister`。
- 去重（同 line_no + 同 category）。
- 统计 critical_count / high_count。

### 2. 成本明细表
- 遍历 BOMTree，对每行产出 `CostBreakdownLine`：
  - 叶子行：`unit_price` 来自 `ShouldCostLine.unit_price`
  - 中间组件行：`unit_price` = 子节点 roll-up（不重复计入采购价）
  - `extended_price = qty_per × unit_price`（按链路）
- NRE 项来自 `EngineeringReport.nre_engineering` + `CommercialReport` 的商务 NRE。
- `rollup` 来自 `FinanceReport.cost_rollup`。

### 3. 假设条件汇总
- 合并 4 个 report 的 `*_assumptions` 字段 → `AssumptionsDoc`。

### 4. 例外清单
- 从 `AmbiguityFlag`（未在 gate 解决的）+ `TermGap`（未接受客户要求的）+ margin 被压低 + 单源未缓解 → 生成例外声明字符串列表。

### 5. 评审轨迹
- `review_trail` = `Blackboard.decision_log` 全量。

### 6. QuoteLetter
- `pricing_summary`：确定性模板字符串（含 piece_price / NRE / total_project_value / currency / validity）。
- `key_terms_summary`：从 `CommercialReport` 取 Incoterms / payment / warranty / liability / IP 渲染。
- `summary`：可选 LLM 润色（输入 = pricing_summary + key_terms_summary + risk_register 摘要），输出 ≤200 字。mock client 可直接返回模板字符串。
- 任何 LLM 失败 → 退化用模板字符串，不阻塞。

### 7. 不完整标记
- 若任一 report 为 None（sub-agent 失败且未恢复）→ `incomplete_reason` 填具体缺失项，status 转 `blocked` 而非 `done`。

## 渲染（`tools/render.py`）
- `render_quote(quote: QuoteDraft, fmt: Literal["markdown","html"]) -> str`
- Markdown：报价函 + 成本明细表 + 风险表 + 假设 + 例外 + 评审轨迹。
- HTML：同结构，带基本样式，可打印。
- 不依赖外部模板引擎（用 Python f-string + 字符串拼接，避免 Jinja 依赖）。

## 验收标准
1. case1：`QuoteDraft` 字段全填充，`incomplete_reason=None`，渲染 Markdown 含成本表 + 假设 + 例外（空例外也要有"无"标注）。
2. case2：评审轨迹含至少 1 条 `ReviewDecision`，例外清单含单源 SoC 未缓解声明。
3. case3：`incomplete_reason` 测试场景——人为置 `proc_report=None` → 标 blocked。
4. 成本明细表中间组件不重复计入：root extended_price == piece_price_total（容差 0.01）。
5. `test_assembler.py` 覆盖：风险去重、NRE 合并、LLM 失败退化、渲染两种格式。
6. `mypy --strict` 通过。

## 约束
- 不得在 assembler 内调 sub-agent。
- 不得修改 Blackboard（只读）。
- LLM 仅用于 summary 文案，且必须可降级。
- 所有数字来自 Blackboard，不得在 assembler 内重新计算成本。
