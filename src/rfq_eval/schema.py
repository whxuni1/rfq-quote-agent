"""Labeled evaluation dataset and result schema.

Dataset models are the ground truth. Result models reject a numeric value on
any metric that was not measured.
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from rfq_eval.taxonomy import ErrorCode
from rfq_eval.thresholds import FLAG_CATEGORIES, GATE_TYPES

Polarity = Literal["nominal", "negative", "adversarial"]
Decision = Literal["fail", "review_pass", "production_pass"]
MeasureStatus = Literal["not_measured", "measured", "withheld"]
QtyRule = Literal["exact", "abstain", "omit_or_exact"]
FileRole = Literal["spec_pdf", "bom_xlsx"]


def _reject_float(value: object) -> object:
    if isinstance(value, float):
        raise ValueError("float is forbidden in labeled money and quantity fields; use a string")
    return value


class Manifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset_version: str
    synthetic: Literal[True]
    description: str
    production_min_independent_cases: int
    ocr_in_scope: Literal[False]
    scanned_pdf_in_scope: Literal[False]


class SheetSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    headers: list[str]
    rows: list[list[str]]
    role: Literal["bom", "decoy", "conflict_bom"]


class PdfSection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str
    paragraphs: list[str]
    tables: list[list[list[str]]] = Field(default_factory=list)


class ExpectedField(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    value: str | None
    quote: str | None = None
    locator: str | None = None
    file_role: FileRole | None = None

    @model_validator(mode="after")
    def citation_matches_value(self) -> "ExpectedField":
        if self.value is None:
            if self.quote is not None or self.locator is not None:
                raise ValueError("an abstain field has no source quote")
            return self
        if not self.quote or not self.locator or self.file_role is None:
            raise ValueError("a populated field requires quote, locator, and file_role")
        return self


class BOMGold(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    match_key: str
    part_no: str
    description: str
    level: int = Field(ge=0)
    parent_match_key: str | None
    qty_per: Decimal | None
    uom: str | None
    qty_rule: QtyRule = "exact"
    accept_qty: list[Decimal] = Field(default_factory=list)

    @field_validator("qty_per", "accept_qty", mode="before")
    @classmethod
    def no_float(cls, value: object) -> object:
        if isinstance(value, list):
            return [_reject_float(item) for item in value]
        return _reject_float(value)

    @model_validator(mode="after")
    def rules(self) -> "BOMGold":
        if self.level == 0 and self.parent_match_key is not None:
            raise ValueError("root line cannot have a parent")
        if self.level > 0 and self.parent_match_key is None:
            raise ValueError("non-root line requires a parent")
        if self.qty_rule == "exact" and (self.qty_per is None or self.uom is None):
            raise ValueError("exact lines require qty_per and uom")
        if self.qty_rule == "abstain" and self.qty_per is not None:
            raise ValueError("abstain lines have no quantity")
        if self.qty_rule == "omit_or_exact" and not self.accept_qty:
            raise ValueError("omit_or_exact requires accept_qty")
        return self


class ExpectedFlag(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    category: str
    related_part_no: str | None
    severity: Literal["low", "medium", "high"]
    source_quote: str

    @field_validator("category")
    @classmethod
    def known_category(cls, value: str) -> str:
        if value not in FLAG_CATEGORIES:
            raise ValueError(f"unknown flag category {value}")
        return value


class InjectionSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    instruction: str
    forbidden_substrings: list[str]
    fields_that_must_hold: list[str]


class DocumentCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    polarity: Polarity
    synthetic: Literal[True]
    customer_id: str
    customer_name: str
    project_name: str
    notes: str
    sections: list[PdfSection]
    sheets: list[SheetSpec]
    fields: list[ExpectedField]
    bom: list[BOMGold]
    flags: list[ExpectedFlag]
    expect_parse_error: bool = False
    accept_full_rejection: bool = False
    forbidden_part_nos: list[str] = Field(default_factory=list)
    injection: InjectionSpec | None = None
    primary_currency: str | None


class CostLeaf(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    line_no: str
    material_cost: Decimal
    processing_cost: Decimal
    overhead: Decimal
    supplier_margin: Decimal
    qty_per_chain: Decimal

    @field_validator(
        "material_cost",
        "processing_cost",
        "overhead",
        "supplier_margin",
        "qty_per_chain",
        mode="before",
    )
    @classmethod
    def no_float(cls, value: object) -> object:
        return _reject_float(value)


class CostCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    polarity: Polarity
    notes: str
    currency: str
    leaves: list[CostLeaf]
    logistics: Decimal
    nre_total: Decimal
    annual_volume: Decimal | None
    peak_monthly_volume: Decimal | None
    project_life_years: int | None
    piece_price: Decimal
    total_project_value: Decimal | None
    expect_data_missing: bool

    @field_validator(
        "logistics",
        "nre_total",
        "annual_volume",
        "peak_monthly_volume",
        "piece_price",
        "total_project_value",
        mode="before",
    )
    @classmethod
    def no_float(cls, value: object) -> object:
        return _reject_float(value)


class GateFacts(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    margin_floor_breached: bool
    proposed_margin_pct: Decimal | None
    margin_floor_pct: Decimal
    single_source_classes: list[str]
    spec_gap_high: bool
    nre_total: Decimal
    nre_threshold: Decimal
    warranty_months: int
    warranty_standard_months: int
    term_gap_critical: bool
    ambiguity_high_unresolved: bool
    missing_reports: list[str]

    @field_validator("proposed_margin_pct", "margin_floor_pct", "nre_total", "nre_threshold", mode="before")
    @classmethod
    def no_float(cls, value: object) -> object:
        return _reject_float(value)


class GateCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    polarity: Polarity
    notes: str
    facts: GateFacts
    expected_gate_types: list[str]
    expect_single_packet: bool

    @field_validator("expected_gate_types")
    @classmethod
    def known_gates(cls, value: list[str]) -> list[str]:
        unknown = [item for item in value if item not in GATE_TYPES]
        if unknown:
            raise ValueError(f"unknown gate types {unknown}")
        if len(value) != len(set(value)):
            raise ValueError("gate types must be unique")
        return value


class RecoveryCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    polarity: Literal["negative", "adversarial"]
    failure_mode: Literal[
        "review_timeout",
        "tool_exception",
        "llm_exhausted",
        "missing_report",
        "invalid_override",
    ]
    notes: str
    allowed_statuses: list[Literal["blocked", "awaiting_review"]]
    expect_exception: bool
    exception_type_name: str | None = None
    incomplete_reason_prefix: str | None = None
    expect_priced_quote: Literal[False]
    min_retries: int | None = None
    require_gates_if_awaiting: list[str] = Field(default_factory=list)


class IsolationPair(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    pair_id: str
    case_a: str
    case_b: str
    tokens_a_forbidden_in_b: list[str]
    tokens_b_forbidden_in_a: list[str]


class PriceCard(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    currency: Literal["USD"]
    note: str
    models: dict[str, dict[str, Decimal]] = Field(default_factory=dict)


class EvalDataset(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest: Manifest
    documents: list[DocumentCase]
    gates: list[GateCase]
    costs: list[CostCase]
    recovery: list[RecoveryCase]
    isolation: list[IsolationPair]
    price_card: PriceCard


class FieldPrediction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    value: str | None


class CitationPrediction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_path: str
    quote: str
    locator: str
    file_role: FileRole


class BOMLinePrediction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    match_key: str
    part_no: str
    description: str
    level: int
    parent_match_key: str | None
    qty_per: Decimal | None
    uom: str | None

    @field_validator("qty_per", mode="before")
    @classmethod
    def no_float(cls, value: object) -> object:
        return _reject_float(value)


class FlagPrediction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    category: str
    related_part_no: str | None
    severity: str


class DocumentPrediction(BaseModel):
    """None on a component means that component was not run.

    An empty list means the component ran and returned nothing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    fields: list[FieldPrediction] | None
    section_titles: list[str] | None
    section_text: str | None
    table_cells: list[str] | None
    bom_lines: list[BOMLinePrediction] | None
    flags: list[FlagPrediction] | None
    citations: list[CitationPrediction] | None
    parse_error: str | None
    output_text: str | None
    complete_artifact: bool


class CostPrediction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    piece_price: Decimal | None
    nre_total: Decimal | None
    total_project_value: Decimal | None
    currency: str | None
    data_missing: bool

    @field_validator("piece_price", "nre_total", "total_project_value", mode="before")
    @classmethod
    def no_float(cls, value: object) -> object:
        return _reject_float(value)


class GatePrediction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    gate_types: list[str]
    packet_count: int = Field(ge=0)
    options_by_type: dict[str, list[str]]
    questions_nonempty: bool
    context_json_safe: bool


class RecoveryPrediction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["blocked", "awaiting_review"] | None
    incomplete_reason: str | None
    priced_quote_emitted: bool
    raised_exception_type: str | None
    retries: int | None
    gate_types: list[str] = Field(default_factory=list)


class IsolationPrediction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_a: str
    artifact_b: str
    artifact_a_after_b: str
    artifact_b_after_a: str


class LatencyPrediction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    elapsed_seconds: Decimal
    input_tokens: int | None
    output_tokens: int | None
    model_id: str | None
    completed: bool

    @field_validator("elapsed_seconds", mode="before")
    @classmethod
    def no_float(cls, value: object) -> object:
        return _reject_float(value)


class FailureExample(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    failure_id: str
    case_id: str
    dimension: str
    error_code: ErrorCode
    expected: str
    actual: str
    model_id: str | None
    prompt_hashes: dict[str, str]
    harness_version: str
    dataset_version: str


class GateResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    gate_id: str
    title: str
    status: MeasureStatus
    decision: Decision
    value: Decimal | None
    review_rule: str
    sample_size_labeled: int = Field(ge=0)
    sample_size_scored: int = Field(ge=0)
    independent_cases_labeled: int = Field(ge=0)
    independent_cases_scored: int = Field(ge=0)
    wilson_low: Decimal | None = None
    wilson_high: Decimal | None = None
    limitation: str
    error_codes: list[ErrorCode]
    suite_met: bool
    details: dict[str, str]

    @model_validator(mode="after")
    def no_fabricated_value(self) -> "GateResult":
        if self.status != "measured" and self.value is not None:
            raise ValueError("a metric that was not measured cannot carry a value")
        if self.status == "measured" and self.value is None:
            raise ValueError("a measured metric requires a value")
        if self.decision != "fail" and self.status != "measured":
            raise ValueError("only a measured gate can pass review or production")
        if self.decision == "production_pass" and not self.suite_met:
            raise ValueError("production pass requires the review suite")
        if self.wilson_low is not None and self.status != "measured":
            raise ValueError("confidence intervals require a measured sample")
        return self


class DatasetQAItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    check_id: str
    passed: bool
    observed: str
    limitation: str


class VersionStamp(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    harness_version: str
    dataset_version: str
    dataset_sha256: str
    git_sha: str | None
    model_id: str | None
    model_source: Literal["env", "absent"]
    reported_model_id: str | None
    prompt_hashes: dict[str, str]
    missing_prompt_files: list[str]
    price_card_models: list[str]


class ModelBasedSection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["not_run"]
    reason: str
    scores: None = None
    rubrics: list[str]


class Recommendation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rank: int = Field(ge=1, le=5)
    title: str
    evidence: str
    action: str


class EvaluationReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    generated_at_utc: datetime
    generated_at_shanghai: datetime
    production_ready: bool
    decision_summary: str
    versions: VersionStamp
    dataset_qa: list[DatasetQAItem]
    gates: list[GateResult]
    taxonomy: list[str]
    recommendations: list[Recommendation]
    failure_count: int = Field(ge=0)
    model_based: ModelBasedSection
    confidence_limitations: list[str]

    @model_validator(mode="after")
    def ready_matches_gates(self) -> "EvaluationReport":
        all_production = all(gate.decision == "production_pass" for gate in self.gates)
        if self.production_ready != all_production:
            raise ValueError("production_ready must match production_pass on every gate")
        if len(self.recommendations) != 5:
            raise ValueError("the report must contain five recommendations")
        return self
