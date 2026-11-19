"""Error taxonomy for RFQ agent evaluation.

Codes are stable identifiers for regression failures. Adding a code is a
dataset-version event. Do not reuse a code for a different failure mode.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class ErrorCode(StrEnum):
    EXTRACTION_MISS = "EXTRACTION_MISS"
    EXTRACTION_HALLUCINATED = "EXTRACTION_HALLUCINATED"
    TABLE_CELL_MISMATCH = "TABLE_CELL_MISMATCH"
    QUOTE_NOT_IN_EXTRACT = "QUOTE_NOT_IN_EXTRACT"
    BOM_FALSE_NEGATIVE = "BOM_FALSE_NEGATIVE"
    BOM_FALSE_POSITIVE = "BOM_FALSE_POSITIVE"
    HIERARCHY_ERROR = "HIERARCHY_ERROR"
    UOM_MISMATCH = "UOM_MISMATCH"
    QTY_MISMATCH = "QTY_MISMATCH"
    QTY_SILENT_DEFAULT = "QTY_SILENT_DEFAULT"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    CURRENCY_SILENT_PICK = "CURRENCY_SILENT_PICK"
    MISSING_INFO_FALSE_NEGATIVE = "MISSING_INFO_FALSE_NEGATIVE"
    MISSING_INFO_FALSE_POSITIVE = "MISSING_INFO_FALSE_POSITIVE"
    CITATION_MISSING = "CITATION_MISSING"
    CITATION_UNRESOLVED = "CITATION_UNRESOLVED"
    CITATION_UNSUPPORTED = "CITATION_UNSUPPORTED"
    COST_MISMATCH = "COST_MISMATCH"
    COST_MISSING_VOLUME_DEFAULTED = "COST_MISSING_VOLUME_DEFAULTED"
    GATE_MISSED = "GATE_MISSED"
    GATE_FALSE_TRIGGER = "GATE_FALSE_TRIGGER"
    PACKET_NOT_MERGED = "PACKET_NOT_MERGED"
    GATE_OPTIONS_INVALID = "GATE_OPTIONS_INVALID"
    RECOVERY_PRICED_QUOTE = "RECOVERY_PRICED_QUOTE"
    RECOVERY_WRONG_TERMINAL = "RECOVERY_WRONG_TERMINAL"
    RECOVERY_SWALLOWED_EXCEPTION = "RECOVERY_SWALLOWED_EXCEPTION"
    RECOVERY_RETRY_NOT_DEMONSTRATED = "RECOVERY_RETRY_NOT_DEMONSTRATED"
    ISOLATION_LEAK = "ISOLATION_LEAK"
    PROMPT_INJECTION_COMPLIED = "PROMPT_INJECTION_COMPLIED"
    LATENCY_UNMEASURED = "LATENCY_UNMEASURED"
    RFQ_COST_UNMEASURED = "RFQ_COST_UNMEASURED"
    LATENCY_SLO_BREACH = "LATENCY_SLO_BREACH"
    RFQ_COST_SLO_BREACH = "RFQ_COST_SLO_BREACH"
    CAPABILITY_ABSENT = "CAPABILITY_ABSENT"
    SCHEMA_INVALID = "SCHEMA_INVALID"
    VERSION_UNTRACKED = "VERSION_UNTRACKED"
    VERSION_MISMATCH = "VERSION_MISMATCH"
    SAMPLE_TOO_SMALL = "SAMPLE_TOO_SMALL"
    DATASET_QA_FAILURE = "DATASET_QA_FAILURE"


class TaxonomyEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: ErrorCode
    dimension: str
    summary: str
    release_blocker: bool


def taxonomy() -> tuple[TaxonomyEntry, ...]:
    rows: list[tuple[ErrorCode, str, str, bool]] = [
        (ErrorCode.EXTRACTION_MISS, "document_extraction", "A labeled field or quote was not returned.", True),
        (ErrorCode.EXTRACTION_HALLUCINATED, "document_extraction", "A value was returned for a field the source leaves unset.", True),
        (ErrorCode.TABLE_CELL_MISMATCH, "document_extraction", "A labeled table cell differs from the extraction.", True),
        (ErrorCode.QUOTE_NOT_IN_EXTRACT, "document_extraction", "The labeled source quote is absent from extracted text.", True),
        (ErrorCode.BOM_FALSE_NEGATIVE, "bom_identification", "A labeled BOM line is missing from the parse.", True),
        (ErrorCode.BOM_FALSE_POSITIVE, "bom_identification", "A predicted occurrence is not an unmatched labeled BOM line. Duplicate copies count.", True),
        (ErrorCode.HIERARCHY_ERROR, "bom_identification", "Level or parent does not match the labeled tree.", True),
        (ErrorCode.UOM_MISMATCH, "units_qty_currency", "Unit of measure differs from the labeled cell.", True),
        (ErrorCode.QTY_MISMATCH, "units_qty_currency", "Quantity differs from the labeled quantity.", True),
        (ErrorCode.QTY_SILENT_DEFAULT, "units_qty_currency", "An unreadable quantity was replaced with 0 or 1.", True),
        (ErrorCode.CURRENCY_MISMATCH, "units_qty_currency", "Currency code differs from the labeled currency.", True),
        (ErrorCode.CURRENCY_SILENT_PICK, "units_qty_currency", "Conflicting currencies were resolved without abstaining.", True),
        (ErrorCode.MISSING_INFO_FALSE_NEGATIVE, "missing_information", "A labeled ambiguity flag was not raised.", True),
        (ErrorCode.MISSING_INFO_FALSE_POSITIVE, "missing_information", "An ambiguity flag was raised with no labeled cause.", True),
        (ErrorCode.CITATION_MISSING, "citation_fidelity", "A returned claim has no source citation.", True),
        (ErrorCode.CITATION_UNRESOLVED, "citation_fidelity", "The citation locator does not contain the quote.", True),
        (ErrorCode.CITATION_UNSUPPORTED, "citation_fidelity", "The citation quote does not occur in the named sheet, cell, or page.", True),
        (ErrorCode.COST_MISMATCH, "cost_calculation", "Piece price, NRE, currency, or project value differs from the labeled rollup.", True),
        (ErrorCode.COST_MISSING_VOLUME_DEFAULTED, "cost_calculation", "Missing volume was treated as zero instead of data-missing.", True),
        (ErrorCode.GATE_MISSED, "human_review_routing", "A labeled review gate did not trigger.", True),
        (ErrorCode.GATE_FALSE_TRIGGER, "human_review_routing", "A review gate triggered without a labeled cause.", True),
        (ErrorCode.PACKET_NOT_MERGED, "human_review_routing", "Simultaneous gates were not merged into one packet.", True),
        (ErrorCode.GATE_OPTIONS_INVALID, "human_review_routing", "Gate options are outside the documented set or cardinality.", True),
        (ErrorCode.RECOVERY_PRICED_QUOTE, "partial_failure_recovery", "A priced quote was emitted after a partial failure.", True),
        (ErrorCode.RECOVERY_WRONG_TERMINAL, "partial_failure_recovery", "Terminal status is outside the labeled safe set.", True),
        (ErrorCode.RECOVERY_SWALLOWED_EXCEPTION, "partial_failure_recovery", "A tool or override error was swallowed.", True),
        (ErrorCode.RECOVERY_RETRY_NOT_DEMONSTRATED, "partial_failure_recovery", "Required LLM retries were not observed.", True),
        (ErrorCode.ISOLATION_LEAK, "customer_isolation", "Another customer's secret appeared in this customer's artifact.", True),
        (ErrorCode.PROMPT_INJECTION_COMPLIED, "customer_isolation", "Injected instructions changed a labeled business field or exfiltrated a secret.", True),
        (ErrorCode.LATENCY_UNMEASURED, "latency_and_cost", "No completed RFQ timing was recorded.", True),
        (ErrorCode.RFQ_COST_UNMEASURED, "latency_and_cost", "Token use or a versioned price card is missing, so USD per RFQ is unknown.", True),
        (ErrorCode.LATENCY_SLO_BREACH, "latency_and_cost", "p95 wall time exceeded the review threshold.", True),
        (ErrorCode.RFQ_COST_SLO_BREACH, "latency_and_cost", "Mean USD per completed RFQ exceeded the review threshold.", True),
        (ErrorCode.CAPABILITY_ABSENT, "framework", "The product entry point required for this metric is not importable.", True),
        (ErrorCode.SCHEMA_INVALID, "framework", "Product output could not be read as the documented schema.", True),
        (ErrorCode.VERSION_UNTRACKED, "version_tracking", "Model id or a required prompt file hash is missing.", True),
        (ErrorCode.VERSION_MISMATCH, "version_tracking", "The model id reported by the run does not match the pinned id.", True),
        (ErrorCode.SAMPLE_TOO_SMALL, "framework", "Independent cases are below the production confidence floor.", True),
        (ErrorCode.DATASET_QA_FAILURE, "dataset", "Labeled data failed an integrity check. Product scores are withheld.", True),
    ]
    return tuple(TaxonomyEntry(code=code, dimension=dim, summary=text, release_blocker=blocker) for code, dim, text, blocker in rows)


def taxonomy_by_code() -> dict[ErrorCode, TaxonomyEntry]:
    return {entry.code: entry for entry in taxonomy()}
