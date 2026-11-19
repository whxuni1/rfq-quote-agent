"""Label arithmetic for the evaluation dataset.

These checks validate the ground truth against the documented formulas.
They are not product scores and are not a substitute for the product tools.
"""

from decimal import Decimal

from rfq_eval.schema import CostCase, GateFacts

_Q = Decimal("0.0001")
_CRITICAL_SINGLE_SOURCE = frozenset({"SOC", "DISPLAY", "CAMERA"})


def piece_price(case: CostCase) -> Decimal:
    """Sum leaf extensions quantized to 4dp, then add logistics once."""
    total = Decimal("0")
    for leaf in case.leaves:
        unit = leaf.material_cost + leaf.processing_cost + leaf.overhead + leaf.supplier_margin
        total += (unit * leaf.qty_per_chain).quantize(_Q)
    return (total + case.logistics).quantize(_Q)


def project_value(case: CostCase) -> tuple[Decimal | None, bool]:
    """Return (total, data_missing).

    Missing annual volume falls back to peak monthly × 12.
    Missing both volumes, or missing project life, is data-missing.
    A missing volume is never treated as zero.
    """
    piece = piece_price(case)
    if case.project_life_years is None:
        return None, True
    if case.annual_volume is None and case.peak_monthly_volume is None:
        return None, True
    volume = case.annual_volume
    if volume is None:
        if case.peak_monthly_volume is None:
            return None, True
        volume = case.peak_monthly_volume * Decimal(12)
    total = (case.nre_total + piece * volume * Decimal(case.project_life_years)).quantize(_Q)
    return total, False


def gates_from_facts(facts: GateFacts) -> list[str]:
    """Deterministic reading of the gate table in tasks/17-human-loop.md."""
    found: list[str] = []
    below_floor = (
        facts.proposed_margin_pct is not None and facts.proposed_margin_pct < facts.margin_floor_pct
    )
    if facts.margin_floor_breached or below_floor:
        found.append("MARGIN_FLOOR_BREACH")
    if any(name in _CRITICAL_SINGLE_SOURCE for name in facts.single_source_classes):
        found.append("SINGLE_SOURCE_CRITICAL")
    if facts.spec_gap_high:
        found.append("SPEC_GAP_HIGH")
    if facts.nre_total > facts.nre_threshold:
        found.append("NRE_SCOPE_LARGE")
    if facts.warranty_months > facts.warranty_standard_months:
        found.append("WARRANTY_BEYOND_STANDARD")
    if facts.term_gap_critical:
        found.append("TERM_GAP_CRITICAL")
    if facts.ambiguity_high_unresolved:
        found.append("INGESTION_AMBIGUITY_HIGH")
    if facts.missing_reports:
        found.append("DATA_MISSING")
    return found
