"""Run the labeled dataset and decide review versus production gates."""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from rfq_eval import __version__
from rfq_eval.adapt import ProductAdapter
from rfq_eval.dataset_io import dataset_sha256
from rfq_eval.dataset_qa import qa_passed, run_dataset_qa
from rfq_eval.documents import write_pdf, write_xlsx
from rfq_eval.judge import model_based_section
from rfq_eval.metrics import (
    DimensionScore,
    failures_from_scores,
    score_bom,
    score_citations,
    score_cost,
    score_extraction,
    score_flags,
    score_gates,
    score_isolation,
    score_recovery,
    score_units,
    suite_satisfied,
)
from rfq_eval.recommend import recommend
from rfq_eval.schema import (
    CostPrediction,
    Decision,
    DocumentCase,
    DocumentPrediction,
    EvalDataset,
    EvaluationReport,
    FailureExample,
    GatePrediction,
    GateResult,
    IsolationPrediction,
    LatencyPrediction,
    RecoveryPrediction,
)
from rfq_eval.stats import p95_nearest_rank, ratio, wilson_interval
from rfq_eval.taxonomy import ErrorCode, taxonomy
from rfq_eval.thresholds import (
    LATENCY_PRODUCTION_MIN_RUNS,
    PRODUCTION_MIN_INDEPENDENT_CASES,
    PRODUCTION_WILSON_FLOOR,
    REQUIRED_PROMPT_FILES,
    REVIEW_P95_SECONDS,
    REVIEW_USD_PER_RFQ,
    threshold_by_id,
)
from rfq_eval.versions import version_stamp

_SHANGHAI = timezone(timedelta(hours=8))

_MINIMUMS: dict[str, dict[str, Decimal]] = {
    "document_extraction": {
        "field_exact_match": Decimal("0.95"),
        "quote_recall": Decimal("0.95"),
        "table_cell_recall": Decimal("0.98"),
        "table_cell_precision": Decimal("0.98"),
    },
    "bom_identification": {
        "precision": Decimal("0.98"),
        "recall": Decimal("0.98"),
        "hierarchy_accuracy": Decimal("1"),
    },
    "units_qty_currency": {
        "qty_accuracy": Decimal("0.99"),
        "uom_accuracy": Decimal("0.99"),
        "currency_accuracy": Decimal("0.99"),
    },
    "missing_information": {"recall": Decimal("0.95"), "precision": Decimal("0.90")},
    "citation_fidelity": {"fidelity": Decimal("0.99")},
    "cost_calculation": {"exact_trees": Decimal("1")},
    "human_review_routing": {"scenario_accuracy": Decimal("1")},
    "partial_failure_recovery": {"safe_outcomes": Decimal("1")},
}

_MAXIMUMS: dict[str, dict[str, Decimal]] = {
    "citation_fidelity": {"unsupported_citation_rate": Decimal("0.01")},
    "customer_isolation": {"leak_count": Decimal("0"), "injection_violations": Decimal("0")},
}


def evaluate(dataset: EvalDataset, adapter: ProductAdapter, work_dir: Path) -> tuple[EvaluationReport, list[FailureExample]]:
    work_dir.mkdir(parents=True, exist_ok=True)
    qa = run_dataset_qa(dataset, work_dir / "dataset-qa")
    digest = dataset_sha256(dataset)
    versions = version_stamp(
        dataset.manifest.dataset_version,
        dataset_sha256=digest,
        reported_model_id=adapter.reported_model_id(),
        price_models=sorted(dataset.price_card.models),
    )
    documents: dict[str, DocumentPrediction | None] = {case.case_id: None for case in dataset.documents}
    costs: dict[str, CostPrediction | None] = {case.case_id: None for case in dataset.costs}
    gates: dict[str, GatePrediction | None] = {case.case_id: None for case in dataset.gates}
    recovery: dict[str, RecoveryPrediction | None] = {case.case_id: None for case in dataset.recovery}
    isolation: dict[str, IsolationPrediction | None] = {pair.pair_id: None for pair in dataset.isolation}
    latency: list[LatencyPrediction] = []
    if qa_passed(qa):
        rendered = work_dir / "rendered"
        for case in dataset.documents:
            pdf_path = rendered / f"{case.case_id}.pdf"
            xlsx_path = rendered / f"{case.case_id}.xlsx"
            write_pdf(case, pdf_path)
            write_xlsx(case, xlsx_path)
            documents[case.case_id] = adapter.predict_document(case, pdf_path, xlsx_path)
            timing = adapter.predict_latency(case)
            if timing is not None:
                latency.append(timing)
        for cost_case in dataset.costs:
            costs[cost_case.case_id] = adapter.predict_cost(cost_case)
        for gate_case in dataset.gates:
            gates[gate_case.case_id] = adapter.predict_gates(gate_case)
        for recovery_case in dataset.recovery:
            recovery[recovery_case.case_id] = adapter.predict_recovery(recovery_case)
        by_id: dict[str, DocumentCase] = {case.case_id: case for case in dataset.documents}
        for pair in dataset.isolation:
            isolation[pair.pair_id] = adapter.predict_isolation(pair, by_id[pair.case_a], by_id[pair.case_b])
    scores = [
        score_extraction(dataset.documents, documents),
        score_bom(dataset.documents, documents),
        score_units(dataset.documents, documents),
        score_flags(dataset.documents, documents),
        score_citations(dataset.documents, documents),
        score_cost(dataset.costs, costs),
        score_gates(dataset.gates, gates),
        score_recovery(dataset.recovery, recovery),
        score_isolation(dataset.isolation, isolation, dataset.documents, documents),
    ]
    if not qa_passed(qa):
        scores = [_withhold(score) for score in scores]
    results = [_from_score(score) for score in scores]
    results.append(_latency_gate(latency, dataset=dataset, expected=len(dataset.documents)))
    results.append(_version_gate(versions.model_id, versions.missing_prompt_files, versions.reported_model_id))
    failures = failures_from_scores(
        scores,
        harness_version=__version__,
        dataset_version=dataset.manifest.dataset_version,
        model_id=versions.model_id,
        prompt_hashes=versions.prompt_hashes,
    )
    if not qa_passed(qa):
        failures.append(
            FailureExample(
                failure_id="dataset:DATASET_QA_FAILURE:0",
                case_id="dataset",
                dimension="dataset",
                error_code=ErrorCode.DATASET_QA_FAILURE,
                expected="all dataset QA checks pass",
                actual="one or more dataset QA checks failed; product scores withheld",
                model_id=versions.model_id,
                prompt_hashes=versions.prompt_hashes,
                harness_version=__version__,
                dataset_version=dataset.manifest.dataset_version,
            )
        )
    now = datetime.now(UTC)
    ready = all(item.decision == "production_pass" for item in results)
    report = EvaluationReport(
        run_id=now.strftime("%Y%m%dT%H%M%SZ"),
        generated_at_utc=now,
        generated_at_shanghai=now.astimezone(_SHANGHAI),
        production_ready=ready,
        decision_summary=_summary(ready, results),
        versions=versions,
        dataset_qa=qa,
        gates=results,
        taxonomy=[
            f"{entry.code.value} | {entry.dimension} | {entry.summary} | release_blocker={entry.release_blocker}"
            for entry in taxonomy()
        ],
        recommendations=recommend(results),
        failure_count=len(failures),
        model_based=model_based_section(),
        confidence_limitations=_limitations(dataset, results),
    )
    return report, failures


def _withhold(score: DimensionScore) -> DimensionScore:
    return score.model_copy(update={"unscored_reason": "dataset QA failed; product scores withheld"})


def _from_score(score: DimensionScore) -> GateResult:
    spec = threshold_by_id()[score.gate_id]
    labeled = len(score.cases)
    scored_cases = [case for case in score.cases if case.scored]
    complete = labeled > 0 and len(scored_cases) == labeled and score.unscored_reason is None
    codes = sorted(
        {failure.error_code for case in score.cases for failure in case.failures},
        key=lambda item: item.value,
    )
    limitation = (
        "value is the labeled-case pass rate. Item metrics are in details. "
        "The Wilson interval treats cases as independent and does not apply to lines or cells inside a case. "
        + spec.review_rule
    )
    if not complete:
        if ErrorCode.CAPABILITY_ABSENT not in codes:
            codes.append(ErrorCode.CAPABILITY_ABSENT)
        reason = score.unscored_reason or "One or more labeled cases returned no prediction."
        return GateResult(
            gate_id=score.gate_id,
            title=spec.title,
            status="not_measured",
            decision="fail",
            value=None,
            review_rule=spec.review_rule,
            sample_size_labeled=score.item_total,
            sample_size_scored=0 if not scored_cases else score.item_correct,
            independent_cases_labeled=labeled,
            independent_cases_scored=len(scored_cases),
            wilson_low=None,
            wilson_high=None,
            limitation=f"{reason} No gate value is reported. {limitation}",
            error_codes=codes,
            suite_met=False,
            details={**score.details, "gate_value": "withheld"},
        )
    passes = sum(1 for case in score.cases if case.passed)
    low, high = wilson_interval(passes, labeled)
    suite = suite_satisfied(
        score,
        minimums=_MINIMUMS.get(score.gate_id, {}),
        maximums=_MAXIMUMS.get(score.gate_id, {}),
        zero_tolerance=spec.zero_tolerance,
    )
    production = labeled >= PRODUCTION_MIN_INDEPENDENT_CASES and low >= PRODUCTION_WILSON_FLOOR and passes == labeled
    decision = _decision(suite, production=production)
    if decision == "review_pass" and ErrorCode.SAMPLE_TOO_SMALL not in codes:
        codes.append(ErrorCode.SAMPLE_TOO_SMALL)
    return GateResult(
        gate_id=score.gate_id,
        title=spec.title,
        status="measured",
        decision=decision,
        value=ratio(passes, labeled),
        review_rule=spec.review_rule,
        sample_size_labeled=score.item_total,
        sample_size_scored=score.item_total,
        independent_cases_labeled=labeled,
        independent_cases_scored=labeled,
        wilson_low=low,
        wilson_high=high,
        limitation=limitation
        + f" A perfect score reaches a 95% Wilson lower bound of 0.95 at {PRODUCTION_MIN_INDEPENDENT_CASES} cases; this gate has {labeled}.",
        error_codes=codes,
        suite_met=suite,
        details=score.details,
    )


def _latency_gate(samples: list[LatencyPrediction], *, dataset: EvalDataset, expected: int) -> GateResult:
    spec = threshold_by_id()["latency_and_cost"]
    completed = [sample for sample in samples if sample.completed]
    if len(completed) != expected or expected == 0:
        return GateResult(
            gate_id=spec.gate_id,
            title=spec.title,
            status="not_measured",
            decision="fail",
            value=None,
            review_rule=spec.review_rule,
            sample_size_labeled=expected,
            sample_size_scored=len(completed),
            independent_cases_labeled=expected,
            independent_cases_scored=len(completed),
            limitation=(
                "No completed RFQ timing was recorded for every labeled document. "
                "Probe time is not RFQ latency, and a missing price is not zero USD."
            ),
            error_codes=[ErrorCode.LATENCY_UNMEASURED, ErrorCode.RFQ_COST_UNMEASURED],
            suite_met=False,
            details={"p95_seconds": "withheld", "mean_usd": "withheld", "gate_value": "withheld"},
        )
    elapsed = p95_nearest_rank([sample.elapsed_seconds for sample in completed])
    costs: list[Decimal] = []
    priced = True
    for sample in completed:
        card = dataset.price_card.models.get(sample.model_id or "")
        input_price = None if card is None else card.get("input_per_million")
        output_price = None if card is None else card.get("output_per_million")
        if (
            sample.input_tokens is None
            or sample.output_tokens is None
            or input_price is None
            or output_price is None
        ):
            priced = False
            break
        costs.append(
            (Decimal(sample.input_tokens) * input_price + Decimal(sample.output_tokens) * output_price)
            / Decimal(1_000_000)
        )
    if not priced:
        return GateResult(
            gate_id=spec.gate_id,
            title=spec.title,
            status="not_measured",
            decision="fail",
            value=None,
            review_rule=spec.review_rule,
            sample_size_labeled=expected,
            sample_size_scored=len(completed),
            independent_cases_labeled=expected,
            independent_cases_scored=len(completed),
            limitation=(
                f"p95 wall time was observed at {elapsed} seconds but USD per RFQ is withheld "
                "because tokens or a versioned price card entry is missing."
            ),
            error_codes=[ErrorCode.RFQ_COST_UNMEASURED],
            suite_met=False,
            details={"diagnostic_p95_seconds": format(elapsed, "f"), "mean_usd": "withheld", "gate_value": "withheld"},
        )
    mean_usd = sum(costs, start=Decimal("0")) / Decimal(len(costs))
    suite = elapsed <= REVIEW_P95_SECONDS and mean_usd <= REVIEW_USD_PER_RFQ
    codes: list[ErrorCode] = []
    if elapsed > REVIEW_P95_SECONDS:
        codes.append(ErrorCode.LATENCY_SLO_BREACH)
    if mean_usd > REVIEW_USD_PER_RFQ:
        codes.append(ErrorCode.RFQ_COST_SLO_BREACH)
    if suite and len(completed) < LATENCY_PRODUCTION_MIN_RUNS:
        codes.append(ErrorCode.SAMPLE_TOO_SMALL)
    decision = _decision(suite, production=len(completed) >= LATENCY_PRODUCTION_MIN_RUNS)
    return GateResult(
        gate_id=spec.gate_id,
        title=spec.title,
        status="measured",
        decision=decision,
        value=elapsed,
        review_rule=spec.review_rule,
        sample_size_labeled=expected,
        sample_size_scored=len(completed),
        independent_cases_labeled=expected,
        independent_cases_scored=len(completed),
        limitation="value is p95 wall time in seconds. mean_usd uses the versioned price card only.",
        error_codes=codes,
        suite_met=suite,
        details={"p95_seconds": format(elapsed, "f"), "mean_usd": format(mean_usd, "f")},
    )


def _version_gate(
    model_id: str | None,
    missing_prompts: list[str],
    reported_model_id: str | None,
) -> GateResult:
    spec = threshold_by_id()["version_tracking"]
    required = len(REQUIRED_PROMPT_FILES)
    present = required - len(missing_prompts)
    codes: list[ErrorCode] = []
    if model_id is None or missing_prompts:
        codes.append(ErrorCode.VERSION_UNTRACKED)
    if model_id is not None and reported_model_id is not None and model_id != reported_model_id:
        codes.append(ErrorCode.VERSION_MISMATCH)
    passed = not codes
    return GateResult(
        gate_id=spec.gate_id,
        title=spec.title,
        status="measured",
        decision="production_pass" if passed else "fail",
        value=ratio(present, required),
        review_rule=spec.review_rule,
        sample_size_labeled=required,
        sample_size_scored=required,
        independent_cases_labeled=1,
        independent_cases_scored=1,
        limitation=(
            "value is the fraction of required prompt files present on disk. "
            "A missing model id still fails the gate. This is a repository observation, not a model accuracy."
        ),
        error_codes=codes,
        suite_met=passed,
        details={
            "model_id": model_id or "absent",
            "missing_prompts": ",".join(missing_prompts) if missing_prompts else "none",
            "reported_model_id": reported_model_id or "absent",
            "prompts_present": f"{present}/{required}",
        },
    )


def _decision(suite: bool, *, production: bool) -> Decision:
    if not suite:
        return "fail"
    if production:
        return "production_pass"
    return "review_pass"


def _summary(ready: bool, gates: list[GateResult]) -> str:
    failed = [gate.gate_id for gate in gates if gate.decision != "production_pass"]
    if ready:
        return "Every production gate passed on this run."
    return (
        "The product is not production-ready. "
        f"{len(failed)} gates are short of production_pass: {', '.join(failed)}."
    )


def _limitations(dataset: EvalDataset, gates: list[GateResult]) -> list[str]:
    business = [gate for gate in gates if gate.gate_id != "version_tracking"]
    business_scored = sum(gate.independent_cases_scored for gate in business)
    return [
        "Every document is synthetic. The set does not represent production RFQ traffic.",
        "Scanned PDFs and OCR are out of scope. Text extraction here uses generated text PDFs.",
        "Lines and cells inside one RFQ are correlated. The Wilson interval is computed on cases, not on cells.",
        f"A perfect case-level score first clears a 95% Wilson lower bound of 0.95 at {PRODUCTION_MIN_INDEPENDENT_CASES} cases. "
        f"The largest labeled group in this set is {max(len(dataset.documents), len(dataset.costs), len(dataset.gates))} cases.",
        "Review pass means the labeled suite met its bar. It does not authorize a production claim.",
        f"Business gates scored {business_scored} cases. Unscored gates have no accuracy number. "
        "The version gate counts prompt files on disk and is not an RFQ accuracy.",
        "The price card has no model prices, so USD per RFQ cannot be computed.",
        "Option wording is fixed only for the four gate types whose text is written in the human-loop task. The other four are checked for 2 to 4 options.",
        f"Review latency bar is {REVIEW_P95_SECONDS} seconds p95 and {REVIEW_USD_PER_RFQ} USD mean. Neither was measured.",
    ]
