# 02 — 共享数据 Schema（字段级规范）

所有模型 Pydantic v2，`frozen=True`。字段名英文 snake_case。币种金额一律 `Decimal`（精度 4 位）。所有枚举显式定义。

## 1. RFQ 输入域

### `RFQPackage`
```python
class RFQPackage(BaseModel):
    model_config = ConfigDict(frozen=True)
    rfq_id: str
    customer: str
    project_name: str
    received_at: datetime
    spec_doc: SpecDoc
    bom_tree: BOMTree
    drawing_refs: list[DrawingRef]
    ambiguity_flags: list[AmbiguityFlag]          # Ingestion 阶段就标出的歧义
    raw_files: list[str]                           # 原始文件路径，仅 trace
```

### `SpecDoc`
```python
class SpecDoc(BaseModel):
    model_config = ConfigDict(frozen=True)
    sections: list[SpecSection]                    # 技术规格章节
    quantity_req: QuantityReq | None
    delivery_req: DeliveryReq | None
    commercial_req_raw: list[str]                  # 原文商业条款片段，待 ComAgent 解析
    quality_req: QualityReq | None                 # PPAP/APQP/ISO/IATF 等级要求
```
`SpecSection(title, text, tables: list[list[list[str]]])`。

### `BOMTree` / `BOMLine`
```python
class MaterialClass(str, Enum):
    SOC="SOC"; MCU="MCU"; MEMORY="MEMORY"; DISPLAY="DISPLAY"; CAMERA="CAMERA"
    SENSOR="SENSOR"; OPTICS="OPTICS"; PCBA="PCBA"; CONNECTOR="CONNECTOR"
    HOUSING="HOUSING"; HARNESS="HARNESS"; THERMAL="THERMAL"; SOFTWARE="SOFTWARE"
    PACKAGING="PACKAGING"; OTHER="OTHER"

class BOMLine(BaseModel):
    model_config = ConfigDict(frozen=True)
    line_no: str
    level: int                                     # 0=成品,1=子组件,2+... 多级
    parent_line_no: str | None
    part_no: str
    part_desc: str
    material_class: MaterialClass
    qty_per: Decimal
    uom: str                                       # EA, SET, M, G...
    source_hint: str | None                        # 客户指定源/厂商
    auto_grade_required: bool                      # AEC-Q100 等要求
    single_source_risk: bool | None                # Ingestion 预判，ProcAgent 复核
    attributes: dict[str, str]                     # 规格键值（如容量/速率/封装）

class BOMTree(BaseModel):
    model_config = ConfigDict(frozen=True)
    root: BOMLine
    nodes: list[BOMLine]                           # 含 root，平铺但带 level/parent
    currency_hint: str | None
    total_lines: int
```

### `DrawingRef` / `AmbiguityFlag`
```python
class DrawingRef(BaseModel):
    ref_id: str; file_name: str; revision: str | None; referenced_in_line_no: str | None

class AmbiguityFlag(BaseModel):
    flag_id: str
    category: Literal["spec_gap","qty_ambiguous","uom_ambiguous","source_conflict","drawing_missing","term_undefined"]
    description: str
    related_line_no: str | None
    severity: Literal["low","medium","high"]
```

## 2. 报价意图

### `QuoteIntent`
```python
class QuoteIntent(BaseModel):
    model_config = ConfigDict(frozen=True)
    project_type: Literal["NPI","NPI+Mass","Mass_only","Retrofit","Spare"]
    annual_volume: Decimal | None
    peak_monthly_volume: Decimal | None
    project_life_years: int | None
    currency: str                                  # ISO 4217
    incoterm_target: str | None
    payment_terms_target: str | None
    nre_scope: list[str]                           # tooling/jigs/validation/software_license
    special_reqs: list[str]                        # 保修/回收/本地化等
    skip_agents: list[Literal["engineering","procurement","finance","commercial"]]
```

## 3. Sub-agent Report 域

### `EngineeringReport`
```python
class EngineeringReport(BaseModel):
    model_config = ConfigDict(frozen=True)
    bom_validated: bool
    auto_grade_gaps: list[AutoGradeGap]            # AEC-Q100 缺口
    spec_gaps: list[SpecGap]                       # 客户规格 vs 能力
    dfm_risks: list[DFMRisk]                       # 可制造性
    vave_opportunities: list[VAVEOpportunity]
    ecn_sensitivity: list[ECNSensitivity]          # 设计变更影响
    nre_engineering: list[NRELine]                 # 工程侧 NRE：模具/治具/验证
    engineering_assumptions: list[str]
```
子结构：`AutoGradeGap(line_no, required, current, risk)`、`SpecGap(spec_item, customer_req, our_capability, gap_severity)`、`DFMRisk(line_no, issue, impact, mitigation)`、`VAVEOpportunity(line_no, suggestion, est_saving_pct)`、`ECNSensitivity(line_no, change_type, cost_impact_pct)`、`NRELine(item, description, cost, currency, one_time: bool)`。

### `ProcurementReport`
```python
class ShouldCostLine(BaseModel):
    model_config = ConfigDict(frozen=True)
    line_no: str
    material_cost: Decimal
    processing_cost: Decimal
    overhead: Decimal
    supplier_margin: Decimal
    unit_price: Decimal                            # 上述之和
    currency: str
    lead_time_weeks: int
    moq: Decimal | None
    supplier_landscape: Literal["single","dual","multi","open"]
    commodity_basis: str                           # 价格基准来源说明
    confidence: Literal["high","medium","low"]

class ProcurementReport(BaseModel):
    model_config = ConfigDict(frozen=True)
    should_cost_lines: list[ShouldCostLine]
    long_lead_items: list[str]                     # line_no, leadtime>26w
    single_source_items: list[str]
    moq_risks: list[MOQRisk]                       # MOQ vs 项目量不匹配
    logistics_cost_estimate: Decimal
    procurement_assumptions: list[str]
```

### `FinanceReport`
```python
class FinanceReport(BaseModel):
    model_config = ConfigDict(frozen=True)
    cost_rollup: CostRollup
    target_margin_pct: Decimal
    proposed_margin_pct: Decimal
    proposed_unit_price: Decimal
    nre_total: Decimal
    total_project_value: Decimal
    payment_milestones: list[PaymentMilestone]
    working_capital_impact: Decimal
    warranty_reserve_pct: Decimal
    fx_assumption: FXAssumption | None
    finance_assumptions: list[str]
    margin_floor_breached: bool                    # 触发 gate 的硬信号
```
`CostRollup(material_total, processing_total, overhead_total, supplier_margin_total, logistics_total, nre_total, piece_price_total, currency)`、`PaymentMilestone(name, pct, trigger)`、`FXAssumption(pair, rate, hedge_horizon)`。

### `CommercialReport`
```python
class CommercialReport(BaseModel):
    model_config = ConfigDict(frozen=True)
    incoterm_proposed: str
    payment_terms_proposed: str
    warranty_terms: WarrantyTerms
    liability_cap_pct: Decimal                      # 占合同额百分比
    ip_terms: IPTerms
    penalty_clauses: list[PenaltyClause]
    quote_validity_days: int
    exclusivity: str | None
    volume_commitment: str | None
    term_gaps: list[TermGap]                       # 客户要求 vs 我方标准条款缺口
    commercial_assumptions: list[str]
```
`WarrantyTerms(months, mileage_km | None, scope)`、`IPTerms(ownership, license_back, background_ip)`、`PenaltyClause(trigger, cap_pct)`、`TermGap(term, customer_req, our_standard, severity)`。

## 4. 风险与 Gate 域

### `RiskItem` / `RiskRegister`
```python
class RiskCategory(str, Enum):
    SPEC_GAP="SPEC_GAP"; SINGLE_SOURCE="SINGLE_SOURCE"; LONG_LEAD="LONG_LEAD"
    AUTO_GRADE="AUTO_GRADE"; MOQ="MOQ"; MARGIN="MARGIN"; TERM_GAP="TERM_GAP"
    DFM="DFM"; FX="FX"; WARRANTY="WARRANTY"; NRE_SCOPE="NRE_SCOPE"

class RiskItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    risk_id: str
    category: RiskCategory
    severity: Literal["low","medium","high","critical"]
    description: str
    related_line_no: str | None
    mitigation: str
    owner_agent: Literal["engineering","procurement","finance","commercial","orchestrator"]

class RiskRegister(BaseModel):
    items: list[RiskItem]
    critical_count: int
    high_count: int
```

### `ReviewGate` / `ReviewPacket` / `ReviewDecision`
```python
class GateType(str, Enum):
    MARGIN_FLOOR_BREACH="MARGIN_FLOOR_BREACH"
    SINGLE_SOURCE_CRITICAL="SINGLE_SOURCE_CRITICAL"
    SPEC_GAP_HIGH="SPEC_GAP_HIGH"
    NRE_SCOPE_LARGE="NRE_SCOPE_LARGE"
    WARRANTY_BEYOND_STANDARD="WARRANTY_BEYOND_STANDARD"
    TERM_GAP_CRITICAL="TERM_GAP_CRITICAL"
    INGESTION_AMBIGUITY_HIGH="INGESTION_AMBIGUITY_HIGH"
    DATA_MISSING="DATA_MISSING"

class ReviewGate(BaseModel):
    model_config = ConfigDict(frozen=True)
    gate_id: str
    gate_type: GateType
    triggered_at: datetime
    context: dict[str, Any]                         # 序列化安全的上下文
    question_to_human: str
    options: list[str]                              # 候选决策
    affected_agents: list[str]

class ReviewPacket(BaseModel):
    model_config = ConfigDict(frozen=True)
    packet_id: str
    rfq_id: str
    gates: list[ReviewGate]                         # 合并的多 gate
    created_at: datetime

class ReviewDecision(BaseModel):
    model_config = ConfigDict(frozen=True)
    packet_id: str
    decisions: list[GateDecision]                   # 与 gates 一一对应
    decided_by: str
    decided_at: datetime
    notes: str | None

class GateDecision(BaseModel):
    gate_id: str
    chosen_option: str
    override: dict[str, Any] | None                 # 人工注入的参数修正
    rationale: str
```

## 5. Blackboard 与 Quote 产出

### `Blackboard`（见 `00-architecture.md` §3，唯一可变模型）
```python
class Blackboard(BaseModel):
    model_config = ConfigDict(frozen=False)         # 例外：唯一可变
    rfq_id: str
    rfq_package: RFQPackage
    quote_intent: QuoteIntent | None = None
    eng_report: EngineeringReport | None = None
    proc_report: ProcurementReport | None = None
    fin_report: FinanceReport | None = None
    com_report: CommercialReport | None = None
    risk_register: RiskRegister | None = None
    review_gates: list[ReviewGate] = []
    decision_log: list[ReviewDecision] = []
    status: Literal["ingesting","planning","executing","awaiting_review","assembling","done","blocked"]
    trace: list[AgentTrace] = []
```

### `QuoteDraft`
```python
class QuoteDraft(BaseModel):
    model_config = ConfigDict(frozen=True)
    rfq_id: str
    quote_letter: QuoteLetter
    cost_breakdown: CostBreakdownSheet
    risk_register: RiskRegister
    assumptions: AssumptionsDoc
    exceptions: list[str]                           # 例外与免责
    review_trail: list[ReviewDecision]
    nre_total: Decimal
    piece_price: Decimal
    total_project_value: Decimal
    currency: str
    quote_validity_days: int
    incomplete_reason: str | None                   # gate 超时/数据缺失时填
    generated_at: datetime

class QuoteLetter(BaseModel):
    model_config = ConfigDict(frozen=True)
    to_customer: str
    project_name: str
    summary: str                                    # LLM 渲染
    pricing_summary: str
    key_terms_summary: str
    validity: str

class CostBreakdownSheet(BaseModel):
    model_config = ConfigDict(frozen=True)
    line_items: list[CostBreakdownLine]             # BOM 行级展开
    nre_items: list[NRELine]
    rollup: CostRollup

class CostBreakdownLine(BaseModel):
    line_no: str; part_desc: str; qty_per: Decimal
    unit_price: Decimal; extended_price: Decimal; currency: str
    cost_basis: str                                  # should-cost / 历史价 / 估算

class AssumptionsDoc(BaseModel):
    model_config = ConfigDict(frozen=True)
    engineering: list[str]
    procurement: list[str]
    finance: list[str]
    commercial: list[str]

class AgentTrace(BaseModel):
    agent: str; started_at: datetime; duration_ms: int
    llm_calls: int; llm_tokens: int
    tool_calls: list[str]
    output_hash: str
```

## 6. 校验规则（Pydantic validator）

- 所有 `Decimal` 量 `ge=0`（金额非负），`qty_per > 0`。
- `BOMLine.level=0` 时 `parent_line_no=None`，`level>0` 时 `parent_line_no` 必须指向存在的 line。
- `CostBreakdownLine.extended_price == qty_per * unit_price`（quantize 4 位）。
- `FinanceReport.proposed_margin_pct` 低于 `target_margin_pct` 时 `margin_floor_breached=True`（强校验，触发 gate）。
- `ReviewPacket.gates` 不允许空列表。
