"""Five reliability actions, each tied to a gate on this run."""

from rfq_eval.schema import GateResult, Recommendation

_PRIORITY = (
    "customer_isolation",
    "partial_failure_recovery",
    "cost_calculation",
    "citation_fidelity",
    "human_review_routing",
    "document_extraction",
    "bom_identification",
    "units_qty_currency",
    "missing_information",
    "latency_and_cost",
    "version_tracking",
)

_TITLES = {
    "customer_isolation": "Prove customer isolation before any multi-customer run",
    "partial_failure_recovery": "Fail closed when the workflow is only partly complete",
    "cost_calculation": "Keep every price on the deterministic Decimal rollup",
    "citation_fidelity": "Cite the source span for every extracted claim",
    "human_review_routing": "Route review gates through one merged packet",
    "document_extraction": "Measure field and table extraction against the labeled PDFs",
    "bom_identification": "Score BOM precision, recall, and parent links",
    "units_qty_currency": "Abstain on conflicting units, quantities, and currencies",
    "missing_information": "Raise the labeled ambiguity flags and no others",
    "latency_and_cost": "Record latency and USD only from versioned completed runs",
    "version_tracking": "Pin the model id and hash every prompt file",
}

_ACTIONS = {
    "customer_isolation": "Give each rfq_id its own blackboard and run directory, ignore instructions embedded in customer files, and block release until every labeled pair and injection case is clean.",
    "partial_failure_recovery": "On timeout, tool failure, invalid override, missing report, or exhausted model retries, emit no piece price. Timeout must block with a review_timeout reason.",
    "cost_calculation": "Roll up leaf extensions with Decimal, add logistics once, and leave project value empty when volume or life is missing. Do not let a model write those numbers.",
    "citation_fidelity": "Return a locator that contains the quote for every business field. Drop claims that do not resolve. The same gap blocks extraction, BOM identity, and unit checks.",
    "human_review_routing": "Evaluate the eight documented gates in one pass, merge them into one packet, and keep the option text that the human-loop task already fixed.",
    "document_extraction": "Run the labeled PDFs through the extractor and compare fields, quotes, and table cells. Do not fill unscored cases with a default accuracy.",
    "bom_identification": "Parse every labeled workbook, including rejection cases, obsolete sheets, and the fullwidth part number.",
    "units_qty_currency": "Preserve written units, honor the declared decimal convention, and abstain when EUR and USD disagree.",
    "missing_information": "Emit spec, drawing, unit, quantity, source, and undefined-term flags only where the label requires them.",
    "latency_and_cost": "Stamp token counts and the pinned model id on each completed RFQ, then apply a price card. Do not substitute the harness probe time or a guessed unit price.",
    "version_tracking": "Store SHA-256 hashes of the six prompt files and the model id on every run so a regression can be attributed.",
}


def _evidence(gate: GateResult) -> str:
    shown = "withheld" if gate.value is None else format(gate.value, "f")
    items = (
        "withheld"
        if gate.status != "measured"
        else f"{gate.sample_size_scored}/{gate.sample_size_labeled}"
    )
    return (
        f"{gate.gate_id} decision={gate.decision} status={gate.status} value={shown} "
        f"scored_cases={gate.independent_cases_scored}/{gate.independent_cases_labeled} "
        f"scored_items={items}."
    )


def recommend(gates: list[GateResult]) -> list[Recommendation]:
    by_id = {gate.gate_id: gate for gate in gates}
    chosen = [gate_id for gate_id in _PRIORITY if by_id[gate_id].decision != "production_pass"]
    if len(chosen) < 5:
        for gate_id in _PRIORITY:
            if gate_id not in chosen:
                chosen.append(gate_id)
            if len(chosen) == 5:
                break
    chosen = chosen[:5]
    rows: list[Recommendation] = []
    for rank, gate_id in enumerate(chosen, start=1):
        gate = by_id[gate_id]
        action = _ACTIONS[gate_id]
        if gate_id == "citation_fidelity":
            siblings = ", ".join(
                f"{name}={by_id[name].status}"
                for name in ("document_extraction", "bom_identification", "units_qty_currency")
            )
            action = f"{action} Observed alongside this run: {siblings}."
        rows.append(
            Recommendation(
                rank=rank,
                title=_TITLES[gate_id],
                evidence=_evidence(gate),
                action=action,
            )
        )
    return rows
