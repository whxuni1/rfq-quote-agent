# 01 — Repo 结构与模块职责

Codex 必须按此结构创建文件。模块边界即依赖边界，不许循环依赖。

## 目录树（权威）

```
rfq-quote-agent/
├── AGENTS.md
├── README.md
├── requirements.txt
├── pyproject.toml
├── docs/
│   ├── 00-architecture.md
│   ├── 01-repo-structure.md
│   └── 02-shared-schemas.md
├── tasks/
│   └── 10..40-*.md
├── src/rfq_agent/
│   ├── __init__.py
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── rfq.py              # RFQPackage, SpecDoc, DrawingRef, AmbiguityFlag
│   │   ├── bom.py              # BOMTree, BOMLine, MaterialClass
│   │   ├── intent.py           # QuoteIntent
│   │   ├── reports.py          # EngineeringReport, ProcurementReport, FinanceReport, CommercialReport
│   │   ├── cost.py             # ShouldCostLine, CostRollup, NRELine
│   │   ├── risk.py             # RiskItem, RiskRegister
│   │   ├── gates.py            # ReviewGate, ReviewPacket, ReviewDecision, GateType
│   │   ├── blackboard.py       # Blackboard
│   │   └── quote.py            # QuoteDraft, QuoteLetter, CostBreakdownSheet, AssumptionsDoc
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── pdf_extract.py      # PDF → 文本块 + 表格
│   │   ├── xlsx_bom.py         # Excel → BOMTree（多 sheet、多层级）
│   │   ├── should_cost.py      # 参数化 should-cost（commodity + processing + margin）
│   │   ├── cost_rollup.py      # BOMTree × ShouldCost → CostRollup
│   │   ├── risk_rules.py       # 确定性风险触发器（单源/长周期/auto-grade 缺失等）
│   │   ├── gate_eval.py        # GateEvaluator（纯规则）
│   │   └── render.py           # QuoteDraft → Markdown/HTML 报价包
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── base.py             # LLMClient 抽象（async chat(messages) -> str）
│   │   └── mock.py             # 确定性 mock client（测试用，回放固定响应）
│   ├── prompts/
│   │   ├── orchestrator.md
│   │   ├── engineering.md
│   │   ├── procurement.md
│   │   ├── finance.md
│   │   ├── commercial.md
│   │   └── ingestion.md
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base.py             # BaseAgent：生命周期、trace、LLM 注入
│   │   ├── ingestion.py
│   │   ├── orchestrator.py
│   │   ├── engineering.py
│   │   ├── procurement.py
│   │   ├── finance.py
│   │   ├── commercial.py
│   │   └── assembler.py
│   ├── gates/
│   │   ├── __init__.py
│   │   └── engine.py           # ReviewGateEngine：暂停/恢复/合并/超时
│   └── runner.py               # async def run_rfq(pdf_path, xlsx_path, reviewer_cb) -> QuoteDraft
├── tests/
│   ├── __init__.py
│   ├── unit/
│   │   ├── test_xlsx_bom.py
│   │   ├── test_should_cost.py
│   │   ├── test_cost_rollup.py
│   │   ├── test_risk_rules.py
│   │   ├── test_gate_eval.py
│   │   └── test_render.py
│   ├── agents/
│   │   ├── test_orchestrator.py
│   │   ├── test_engineering.py
│   │   ├── test_procurement.py
│   │   ├── test_finance.py
│   │   └── test_commercial.py
│   ├── eval/
│   │   ├── test_eval_suite.py
│   │   └── golden/              # 3 个 fixture 的金样例 QuoteDraft
│   └── fixtures/
│       ├── case1_simple_pcba/   # 简单 PCBA + 结构件
│       ├── case2_cockpit_core/  # 智能座舱核心板（SoC+屏+DDR+NAND）
│       └── case3_adas_camera/   # ADAS 前视摄像头模组（光学+ISP+Serializer）
└── .github/workflows/ci.yml     # ruff + mypy + pytest
```

## 模块依赖方向（单向，禁止循环）

```
runner → agents → schemas
              ↘
                tools → schemas
              ↗
gates → schemas
agents → llm, prompts, tools, schemas, gates
```

`schemas/` 是最底层，零依赖（仅 pydantic）。`tools/` 依赖 `schemas/`。`agents/` 依赖上述全部。`runner` 是组合根。

## 关键文件职责一句话

| 文件 | 职责 |
|---|---|
| `schemas/*` | 全部跨模块数据结构，frozen Pydantic v2 |
| `tools/pdf_extract.py` | pdfplumber 抽文本+表格，输出 `SpecDoc` |
| `tools/xlsx_bom.py` | openpyxl 解析多 sheet BOM，识别层级（缩进/父件号列），输出 `BOMTree` |
| `tools/should_cost.py` | 参数化：`material_weight × commodity_price + processing_cost × cycle_time + overhead + supplier_margin` |
| `tools/cost_rollup.py` | 自底向上 roll-up BOMTree，分别汇总 NRE 与 piece price |
| `tools/risk_rules.py` | 规则集：单源 SoC、leadtime>26w、AEC-Q100 缺失、spec gap、MOQ 不满足、双源缺失 |
| `tools/gate_eval.py` | 读 Blackboard，返回 `list[ReviewGate]`（纯函数） |
| `agents/ingestion.py` | 调 tools + LLM 理解，输出 `RFQPackage` |
| `agents/orchestrator.py` | 唯一状态推进者；调 sub-agent；触发 gate |
| `agents/assembler.py` | 读 Blackboard → `QuoteDraft`（确定性） |
| `gates/engine.py` | HiL 暂停/恢复/合并/超时；`reviewer_cb` 注入点 |
| `runner.py` | 端到端入口，注入 LLM client 与 reviewer callback |

## 命名约定

- 文件名 `snake_case.py`，类 `PascalCase`，函数 `snake_case`。
- sub-agent 类名：`EngineeringAgent`、`ProcurementAgent`、`FinanceAgent`、`CommercialAgent`。
- schema 字段用业务术语英文：`unit_price`、`lead_time_weeks`、`moq`、`incoterm`、`payment_terms`。
- 枚举值用大写：`MaterialClass.SOC`、`GateType.MARGIN_FLOOR_BREACH`。

## 禁止

- 在 `schemas/` 外定义新的跨模块数据结构。
- 在 `agents/` 内直接 `import openai`/`anthropic`。
- 在 `tools/` 内 import `agents/` 或 `llm/`。
- 在 `runner.py` 之外做组合装配。
