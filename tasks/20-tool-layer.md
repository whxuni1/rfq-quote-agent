# Task 20 — Tool Layer（纯函数工具集）

Status: TODO

## 目标
实现所有确定性工具，零外部网络、零 LLM 依赖。Sub-agent 通过这些工具完成数字计算与文档解析。

## 输出文件
（与各 sub-agent task 重叠的 tool 文件统一在此任务一次性实现并测试）
- `src/rfq_agent/tools/pdf_extract.py`（若 Task 15 未单独建）
- `src/rfq_agent/tools/xlsx_bom.py`
- `src/rfq_agent/tools/should_cost.py`
- `src/rfq_agent/tools/cost_rollup.py`
- `src/rfq_agent/tools/risk_rules.py`
- `src/rfq_agent/tools/gate_eval.py`
- `src/rfq_agent/tools/render.py`
- `src/rfq_agent/data/commodity_prices.yaml`（基准价表）
- `src/rfq_agent/data/processing_rates.yaml`（加工费率表）
- `src/rfq_agent/data/standard_terms.yaml`（商务标准条款）
- `tests/unit/test_*.py`（每个工具一个测试文件）

## 实现规范

### 依赖
- `pdfplumber`（PDF 文本+表格抽取）
- `openpyxl`（Excel 读写）
- `pydantic` v2
- `pyyaml`（配置加载）
- `structlog`（日志）
- 禁止：requests/httpx/openai/anthropic 在 tools 层 import

### 配置加载约定
所有 YAML 配置在模块 import 时惰性加载（`functools.lru_cache`），支持环境变量 `RFQ_AGENT_DATA_DIR` override 路径。基准价表结构：
```yaml
# commodity_prices.yaml
SOC:
  base_price: 45.00          # USD per unit, 中档
  unit: EA
  attribute_multipliers:
    process_node: {7nm: 1.3, 14nm: 1.0, 28nm: 0.7}
    cores: {4: 0.9, 8: 1.2, 16: 1.6}
MEMORY:
  base_price: 0.35            # USD per GB (DDR5)
  unit: GB
  attribute_multipliers:
    type: {DDR4: 0.7, DDR5: 1.0, LPDDR5: 1.2}
    speed_mbps: {4800: 1.0, 6400: 1.15, 8400: 1.3}
# ... 其余类别
```

### 工具签名（权威）
```python
# pdf_extract.py
def extract_spec(pdf_path: str) -> SpecDoc: ...

# xlsx_bom.py
def parse_bom(xlsx_path: str, rfq_id: str) -> BOMTree: ...

# should_cost.py
def should_cost_line(bom_line: BOMLine, config: ShouldCostConfig) -> ShouldCostLine: ...
def should_cost_bom(tree: BOMTree, config: ShouldCostConfig) -> list[ShouldCostLine]: ...

# cost_rollup.py
def rollup(tree: BOMTree, should_cost_lines: list[ShouldCostLine]) -> CostRollup: ...

# risk_rules.py
def evaluate_procurement_risks(proc_report: ProcurementReport, intent: QuoteIntent) -> list[RiskItem]: ...
def evaluate_engineering_risks(eng_report: EngineeringReport) -> list[RiskItem]: ...
def evaluate_commercial_risks(com_report: CommercialReport) -> list[RiskItem]: ...

# gate_eval.py
def evaluate(bb: Blackboard) -> list[ReviewGate]: ...

# render.py
def render_quote(quote: QuoteDraft, fmt: Literal["markdown","html"]) -> str: ...
```

### 确定性要求
- 同输入同输出（`lru_cache` 不影响纯度）。
- 所有金额 `Decimal`，禁用 `float`。`Decimal` 运算显式 `getcontext().prec = 28`，结果 quantize 4 位。
- 时间相关：`datetime.now()` 只在 trace 记录用，不影响业务字段。测试用 `freezegun` 或注入 `clock` 回调。

### 日志
- 每个 tool 入口 `structlog.get_logger().bind(tool=__name__, rfq_id=...)`。
- 关键中间值 debug 级记录，便于人工审计。

## 测试要求
- 每个 tool 至少 5 个用例：正常 / 边界 / 异常 / 配置 override / 确定性（同输入两次相等）。
- `test_should_cost.py`：每个 material_class 一个用例 + 属性系数组合。
- `test_cost_rollup.py`：3 层 BOM 链路 qty 乘积 + 中间件不重复。
- `test_gate_eval.py`：8 类 gate 各触发一次 + 不触发场景。
- 工具层覆盖率 ≥ 95%。

## 验收标准
1. 所有工具 import 不触发网络/LLM。
2. `pytest tests/unit/` 全绿，覆盖率达标。
3. `mypy --strict` 通过。
4. 配置 YAML schema 自校验（加载时 Pydantic 校验，坏配置直接报错）。
5. `commodity_prices.yaml` 至少覆盖 12 个 material_class。

## 约束
- 工具不得 import `agents/` 或 `llm/`。
- 工具不得抛未捕获异常（业务异常用自定义 `ToolError` 子类）。
- 渲染工具不得依赖 Jinja/mako（字符串拼接）。
