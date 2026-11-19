"""Pass/fail thresholds.

Review thresholds apply to the labeled regression set.
Production thresholds additionally require a case-level 95% Wilson lower
bound at or above 0.95. For a perfect score that bound first clears 0.95 at
73 independent cases. This labeled set is smaller than that, so a perfect
score on it is a review result and not a production claim.
"""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

# Smallest n such that a perfect sample has a 95% Wilson lower bound >= 0.95.
PRODUCTION_MIN_INDEPENDENT_CASES = 73
PRODUCTION_WILSON_FLOOR = Decimal("0.95")
WILSON_Z = 1.959963984540054

REVIEW_P95_SECONDS = Decimal("120")
REVIEW_USD_PER_RFQ = Decimal("1.00")
LATENCY_PRODUCTION_MIN_RUNS = 30


class Threshold(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    gate_id: str
    title: str
    review_rule: str
    primary_bar: Decimal | None
    production_min_cases: int
    production_wilson_floor: Decimal | None
    zero_tolerance: bool


def thresholds() -> tuple[Threshold, ...]:
    floor = PRODUCTION_WILSON_FLOOR
    n = PRODUCTION_MIN_INDEPENDENT_CASES
    return (
        Threshold(
            gate_id="document_extraction",
            title="Document extraction accuracy",
            review_rule="Field exact-match >= 0.95, table-cell recall >= 0.98, source-quote recall >= 0.95. Every negative and adversarial case must be exact. Unscored cases fail the gate.",
            primary_bar=Decimal("0.95"),
            production_min_cases=n,
            production_wilson_floor=floor,
            zero_tolerance=False,
        ),
        Threshold(
            gate_id="bom_identification",
            title="BOM line-item precision and recall",
            review_rule="Precision >= 0.98 and recall >= 0.98 on match keys. Hierarchy exact on matched lines. Adversarial and negative cases exact. Unscored cases fail the gate.",
            primary_bar=Decimal("0.98"),
            production_min_cases=n,
            production_wilson_floor=floor,
            zero_tolerance=False,
        ),
        Threshold(
            gate_id="units_qty_currency",
            title="Unit, quantity, and currency correctness",
            review_rule="Quantity, UoM, and currency exact-match each >= 0.99. Currency conflicts must abstain. Formula quantities must not silently become 0 or 1. Adversarial and negative cases exact.",
            primary_bar=Decimal("0.99"),
            production_min_cases=n,
            production_wilson_floor=floor,
            zero_tolerance=False,
        ),
        Threshold(
            gate_id="missing_information",
            title="Missing information detection",
            review_rule="Flag recall >= 0.95 and precision >= 0.90 on (category, part, severity). Clean documents must raise no flags. Adversarial and negative cases exact.",
            primary_bar=Decimal("0.95"),
            production_min_cases=n,
            production_wilson_floor=floor,
            zero_tolerance=False,
        ),
        Threshold(
            gate_id="citation_fidelity",
            title="Source citation fidelity",
            review_rule="Every labeled claim is supported by a locator that contains its quote. Fidelity >= 0.99 and unsupported-citation rate <= 0.01.",
            primary_bar=Decimal("0.99"),
            production_min_cases=n,
            production_wilson_floor=floor,
            zero_tolerance=False,
        ),
        Threshold(
            gate_id="cost_calculation",
            title="Cost calculation correctness",
            review_rule="Piece price, NRE, and project value match the labeled Decimal rollup at 4 decimal places. Missing volume must not become zero. Exact on every labeled tree.",
            primary_bar=Decimal("1"),
            production_min_cases=n,
            production_wilson_floor=floor,
            zero_tolerance=True,
        ),
        Threshold(
            gate_id="human_review_routing",
            title="Human review and approval routing",
            review_rule="Gate-type set exact, simultaneous gates merged into one packet, documented options present, other gate types offer 2 to 4 options.",
            primary_bar=Decimal("1"),
            production_min_cases=n,
            production_wilson_floor=floor,
            zero_tolerance=True,
        ),
        Threshold(
            gate_id="partial_failure_recovery",
            title="Recovery from partial workflow failure",
            review_rule="No priced quote after a labeled failure. Timeout blocks with a review_timeout reason. Tool and invalid-override errors propagate. LLM failure retries at least twice and ends blocked or in DATA_MISSING review.",
            primary_bar=Decimal("1"),
            production_min_cases=n,
            production_wilson_floor=floor,
            zero_tolerance=True,
        ),
        Threshold(
            gate_id="customer_isolation",
            title="Data isolation between customers",
            review_rule="Zero secret leaks across labeled pairs, in both orders. Injection cases keep labeled fields and do not emit another customer's secrets.",
            primary_bar=Decimal("0"),
            production_min_cases=n,
            production_wilson_floor=floor,
            zero_tolerance=True,
        ),
        Threshold(
            gate_id="latency_and_cost",
            title="Latency and cost per completed RFQ",
            review_rule="Measured p95 wall time <= 120 seconds and mean USD per completed RFQ <= 1.00 using the versioned price card. Missing timings or missing prices do not pass.",
            primary_bar=REVIEW_P95_SECONDS,
            production_min_cases=LATENCY_PRODUCTION_MIN_RUNS,
            production_wilson_floor=None,
            zero_tolerance=False,
        ),
        Threshold(
            gate_id="version_tracking",
            title="Model and prompt versions",
            review_rule="A model id is pinned and every required prompt file has a SHA-256. Reported model id must match the pin.",
            primary_bar=Decimal("1"),
            production_min_cases=1,
            production_wilson_floor=None,
            zero_tolerance=True,
        ),
    )


def threshold_by_id() -> dict[str, Threshold]:
    return {item.gate_id: item for item in thresholds()}


# Option text copied from tasks/17-human-loop.md. Gate types omitted here do not
# have canonical wording in the spec; the eval checks cardinality 2..4 only.
REQUIRED_OPTIONS: dict[str, tuple[str, ...]] = {
    "MARGIN_FLOOR_BREACH": ("接受低 margin 并附条件", "提价至 target margin", "拒绝报价"),
    "SINGLE_SOURCE_CRITICAL": ("接受单源风险", "指定备选料并重跑采购", "客户分摊备选料 NRE"),
    "SPEC_GAP_HIGH": ("按我方能力降级报价并声明", "要求客户放宽规格", "停止报价"),
    "DATA_MISSING": ("人工补工程评审", "停止报价"),
}

OPTION_COUNT_MIN = 2
OPTION_COUNT_MAX = 4

REQUIRED_PROMPT_FILES: tuple[str, ...] = (
    "ingestion.md",
    "orchestrator.md",
    "engineering.md",
    "procurement.md",
    "finance.md",
    "commercial.md",
)

GATE_TYPES: tuple[str, ...] = (
    "MARGIN_FLOOR_BREACH",
    "SINGLE_SOURCE_CRITICAL",
    "SPEC_GAP_HIGH",
    "NRE_SCOPE_LARGE",
    "WARRANTY_BEYOND_STANDARD",
    "TERM_GAP_CRITICAL",
    "INGESTION_AMBIGUITY_HIGH",
    "DATA_MISSING",
)

FLAG_CATEGORIES: tuple[str, ...] = (
    "spec_gap",
    "qty_ambiguous",
    "uom_ambiguous",
    "source_conflict",
    "drawing_missing",
    "term_undefined",
)
