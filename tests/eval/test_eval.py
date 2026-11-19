"""Evaluation framework tests.

Product gates are expected to fail closed on this repository. Scorer tests use
an in-memory echo of the labels and never write that echo into the regression report.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError
from tests.eval.echo import EchoAdapter

from rfq_eval.__main__ import main
from rfq_eval.adapt import AdapterSchemaError, ProductAdapter, map_bom, map_spec
from rfq_eval.case_library import build_dataset
from rfq_eval.dataset_io import dataset_sha256, load_dataset, load_or_materialize, materialize
from rfq_eval.dataset_qa import _price_card, qa_passed, run_dataset_qa
from rfq_eval.label_audit import piece_price, project_value
from rfq_eval.metrics import score_bom, score_citations, score_cost, score_isolation, suite_satisfied
from rfq_eval.runner import _MAXIMUMS, _MINIMUMS, evaluate
from rfq_eval.schema import (
    CitationPrediction,
    DocumentPrediction,
    EvalDataset,
    EvaluationReport,
    GateResult,
    IsolationPrediction,
    PriceCard,
)
from rfq_eval.stats import wilson_interval
from rfq_eval.taxonomy import ErrorCode, taxonomy


def test_wilson_floor_starts_at_73_perfect_cases() -> None:
    assert wilson_interval(72, 72)[0] < Decimal("0.95")
    assert wilson_interval(73, 73)[0] >= Decimal("0.95")
    assert wilson_interval(6, 6)[0] < Decimal("0.62")


def test_known_cost_oracles() -> None:
    dataset = build_dataset()
    by_id = {case.case_id: case for case in dataset.costs}
    single = by_id["cost-single"]
    assert single.piece_price == Decimal("1.5000")
    assert single.total_project_value == Decimal("130.0000")
    assert single.expect_data_missing is False
    chain = by_id["cost-chain"]
    assert chain.piece_price == Decimal("6.0000")
    assert chain.total_project_value == Decimal("6.0000")
    peak = by_id["cost-peak-fallback"]
    assert peak.piece_price == Decimal("6.0000")
    assert peak.total_project_value == Decimal("7200.0000")
    missing = by_id["cost-missing-volume"]
    assert missing.expect_data_missing is True
    assert missing.total_project_value is None
    assert missing.piece_price == Decimal("4.0000")
    trap = by_id["cost-chain-trap"]
    assert trap.piece_price == Decimal("24.0000")
    tiny = by_id["cost-tiny"]
    assert tiny.piece_price == Decimal("0.0003")
    assert tiny.total_project_value == Decimal("0.0030")
    for case in dataset.costs:
        assert case.piece_price == piece_price(case)
        total, flag = project_value(case)
        assert case.total_project_value == total
        assert case.expect_data_missing is flag


def test_gate_controls_match_the_written_rule() -> None:
    dataset = build_dataset()
    by_id = {case.case_id: case.expected_gate_types for case in dataset.gates}
    assert by_id["gate-none"] == []
    assert by_id["gate-margin-flag"] == ["MARGIN_FLOOR_BREACH"]
    assert by_id["gate-margin-below"] == ["MARGIN_FLOOR_BREACH"]
    assert by_id["gate-margin-at-floor"] == []
    assert by_id["gate-connector-single"] == []
    assert by_id["gate-soc-single"] == ["SINGLE_SOURCE_CRITICAL"]
    assert by_id["gate-nre-equal"] == []
    assert by_id["gate-nre-over"] == ["NRE_SCOPE_LARGE"]
    assert by_id["gate-warranty-36"] == []
    assert by_id["gate-warranty-37"] == ["WARRANTY_BEYOND_STANDARD"]
    assert by_id["gate-display-camera"] == ["SINGLE_SOURCE_CRITICAL"]
    assert by_id["gate-combo"] == [
        "MARGIN_FLOOR_BREACH",
        "SINGLE_SOURCE_CRITICAL",
        "WARRANTY_BEYOND_STANDARD",
        "TERM_GAP_CRITICAL",
    ]


def test_dataset_roundtrip_and_qa(tmp_path: Path) -> None:
    built = build_dataset()
    materialize(built, tmp_path)
    loaded = load_dataset(tmp_path)
    assert loaded == built
    qa = run_dataset_qa(loaded, tmp_path / "qa")
    failed = [item.check_id for item in qa if not item.passed]
    assert failed == []
    assert qa_passed(qa)


def test_float_labels_are_rejected() -> None:
    dataset = build_dataset()
    payload = dataset.costs[0].model_dump()
    payload["logistics"] = 1.25
    with pytest.raises(ValidationError):
        type(dataset.costs[0]).model_validate(payload)


def test_unmeasured_gate_cannot_carry_a_value() -> None:
    with pytest.raises(ValidationError):
        GateResult(
            gate_id="document_extraction",
            title="Document extraction accuracy",
            status="not_measured",
            decision="fail",
            value=Decimal("0.95"),
            review_rule="bar",
            sample_size_labeled=1,
            sample_size_scored=0,
            independent_cases_labeled=1,
            independent_cases_scored=0,
            limitation="withheld",
            error_codes=[ErrorCode.CAPABILITY_ABSENT],
            suite_met=False,
            details={},
        )


def test_product_adapter_returns_no_prediction(tmp_path: Path) -> None:
    dataset = build_dataset()
    adapter = ProductAdapter()
    case = dataset.documents[0]
    assert adapter.predict_document(case, tmp_path / "a.pdf", tmp_path / "a.xlsx") is None
    assert adapter.predict_cost(dataset.costs[0]) is None
    assert adapter.predict_gates(dataset.gates[0]) is None
    assert adapter.predict_recovery(dataset.recovery[0]) is None
    assert adapter.predict_latency(case) is None
    assert all(state == "missing" for state in adapter.availability.values())


def test_mappers_read_documented_shapes_and_reject_floats() -> None:
    class Section:
        def __init__(self) -> None:
            self.title = "项目概述"
            self.text = "客户：甲"
            self.tables = [[["参数", "要求"]]]

    class Spec:
        def __init__(self) -> None:
            self.sections = [Section()]

    titles, text, cells = map_spec(Spec())
    assert titles == ["项目概述"]
    assert "客户：甲" in text
    assert cells == ["参数", "要求"]

    class Line:
        def __init__(self, line_no: str, parent: str | None) -> None:
            self.line_no = line_no
            self.parent_line_no = parent
            self.part_no = "P" if parent is None else "C"
            self.part_desc = "part"
            self.level = 0 if parent is None else 1
            self.qty_per = Decimal("2")
            self.uom = "EA"

    class Tree:
        def __init__(self) -> None:
            self.nodes = [Line("1", None), Line("2", "1")]
            self.currency_hint = "CNY"

    lines, currency = map_bom(Tree())
    assert currency == "CNY"
    assert lines[1].parent_match_key == "P"
    assert lines[1].qty_per == Decimal("2")

    class BadLine:
        def __init__(self) -> None:
            self.line_no = "1"
            self.parent_line_no = None
            self.part_no = "P"
            self.part_desc = "part"
            self.level = 0
            self.qty_per = 1.5
            self.uom = "EA"

    class BadTree:
        def __init__(self) -> None:
            self.nodes = [BadLine()]
            self.currency_hint = "CNY"

    with pytest.raises(AdapterSchemaError):
        map_bom(BadTree())


def test_product_run_does_not_invent_scores(tmp_path: Path) -> None:
    report, failures = evaluate(build_dataset(), ProductAdapter(), tmp_path)
    assert report.production_ready is False
    assert report.model_based.status == "not_run"
    assert report.model_based.scores is None
    scored_business = []
    for gate in report.gates:
        if gate.gate_id == "version_tracking":
            assert gate.status == "measured"
            assert gate.value == Decimal("0")
            assert gate.decision == "fail"
            continue
        assert gate.status == "not_measured"
        assert gate.value is None
        assert gate.decision == "fail"
        assert gate.wilson_low is None
        scored_business.append(gate.gate_id)
    assert "document_extraction" in scored_business
    assert "latency_and_cost" in scored_business
    assert failures
    assert all(item.model_id is None for item in failures)
    assert any(item.error_code == ErrorCode.CAPABILITY_ABSENT for item in failures)
    assert {item.code for item in taxonomy()} >= {item.error_code for item in failures}


def test_perfect_labels_are_not_a_production_claim(tmp_path: Path) -> None:
    report, _failures = evaluate(build_dataset(), EchoAdapter(), tmp_path)
    by_id = {gate.gate_id: gate for gate in report.gates}
    assert by_id["document_extraction"].decision == "review_pass"
    assert by_id["document_extraction"].value == Decimal("1.000000")
    assert by_id["bom_identification"].decision == "review_pass"
    assert by_id["units_qty_currency"].decision == "review_pass"
    assert by_id["missing_information"].decision == "review_pass"
    assert by_id["citation_fidelity"].decision == "review_pass"
    assert by_id["cost_calculation"].decision == "review_pass"
    assert by_id["human_review_routing"].decision == "review_pass"
    assert by_id["partial_failure_recovery"].decision == "review_pass"
    assert by_id["customer_isolation"].decision == "review_pass"
    assert by_id["customer_isolation"].details["leak_count"] == "0"
    assert by_id["latency_and_cost"].status == "not_measured"
    assert by_id["latency_and_cost"].value is None
    assert by_id["version_tracking"].decision == "fail"
    assert report.production_ready is False
    assert "not production-ready" in report.decision_summary


def test_one_leak_fails_isolation() -> None:
    dataset = build_dataset()
    pair = dataset.isolation[0]
    leaked = {
        pair.pair_id: IsolationPrediction(
            artifact_a="clean",
            artifact_b=pair.tokens_a_forbidden_in_b[0],
            artifact_a_after_b="clean",
            artifact_b_after_a="clean",
        )
    }
    score = score_isolation([pair], leaked, dataset.documents, {case.case_id: None for case in dataset.documents})
    assert score.details["leak_count"] == "withheld" or any(
        failure.error_code == ErrorCode.ISOLATION_LEAK for case in score.cases for failure in case.failures
    )
    assert any(failure.error_code == ErrorCode.ISOLATION_LEAK for case in score.cases for failure in case.failures)


def test_report_schema_rejects_a_ready_flag_that_disagrees(tmp_path: Path) -> None:
    report, _failures = evaluate(build_dataset(), ProductAdapter(), tmp_path)
    payload = report.model_dump()
    payload["production_ready"] = True
    with pytest.raises(ValidationError):
        EvaluationReport.model_validate(payload)


def test_committed_dataset_matches_generator() -> None:
    root = Path(__file__).resolve().parents[2]
    if not (root / "eval" / "dataset" / "manifest.json").exists():
        pytest.skip("persisted dataset is absent")
    assert load_dataset(root / "eval" / "dataset") == build_dataset()
    stored = (root / "eval" / "reports" / "regression_report.json").read_text(encoding="utf-8")
    loaded = EvaluationReport.model_validate_json(stored)
    assert loaded.production_ready is False
    assert loaded.versions.dataset_sha256 == dataset_sha256(build_dataset())


def _echo_documents(dataset: EvalDataset) -> dict[str, DocumentPrediction]:
    adapter = EchoAdapter()
    return {
        case.case_id: adapter.predict_document(case, Path("a.pdf"), Path("a.xlsx"))
        for case in dataset.documents
    }


def test_persisted_labels_survive_a_default_load(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    materialize(build_dataset(), root)
    document = root / "documents" / "nom-cockpit-core.json"
    payload = json.loads(document.read_text(encoding="utf-8"))
    payload["project_name"] = "Corrected Label"
    document.write_text(json.dumps(payload), encoding="utf-8")
    loaded = load_or_materialize(root)
    cockpit = next(case for case in loaded.documents if case.case_id == "nom-cockpit-core")
    assert cockpit.project_name == "Corrected Label"
    assert json.loads(document.read_text(encoding="utf-8"))["project_name"] == "Corrected Label"


def test_malformed_labels_are_not_regenerated(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    materialize(build_dataset(), root)
    manifest = root / "manifest.json"
    manifest.write_text("{", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_or_materialize(root)
    assert manifest.read_text(encoding="utf-8") == "{"


def test_first_run_materializes_and_regenerate_restores(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    created = load_or_materialize(root)
    assert created == build_dataset()
    document = root / "documents" / "nom-cockpit-core.json"
    payload = json.loads(document.read_text(encoding="utf-8"))
    payload["project_name"] = "Corrected Label"
    document.write_text(json.dumps(payload), encoding="utf-8")
    restored = load_or_materialize(root, regenerate=True)
    assert restored == build_dataset()


def test_cli_does_not_rewrite_labels_when_writing_a_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "dataset"
    materialize(build_dataset(), root)
    document = root / "documents" / "nom-cockpit-core.json"
    payload = json.loads(document.read_text(encoding="utf-8"))
    payload["project_name"] = "Corrected Label"
    document.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr("rfq_eval.dataset_io.dataset_dir", lambda: root)
    code = main(["--out", str(tmp_path / "out")])
    assert code == 0
    assert json.loads(document.read_text(encoding="utf-8"))["project_name"] == "Corrected Label"
    report = EvaluationReport.model_validate_json(
        (tmp_path / "out" / "reports" / "regression_report.json").read_text(encoding="utf-8")
    )
    assert report.versions.dataset_sha256 != dataset_sha256(build_dataset())
    assert report.production_ready is False


def test_hierarchy_must_be_exact_for_review() -> None:
    dataset = build_dataset()
    predictions = _echo_documents(dataset)
    clean = score_bom(dataset.documents, predictions)
    assert _MINIMUMS["bom_identification"]["hierarchy_accuracy"] == Decimal("1")
    assert suite_satisfied(
        clean,
        minimums=_MINIMUMS["bom_identification"],
        maximums={},
        zero_tolerance=False,
    )
    cockpit = predictions["nom-cockpit-core"]
    assert cockpit.bom_lines is not None
    child = next(line for line in cockpit.bom_lines if line.parent_match_key is not None)
    changed = child.model_copy(update={"parent_match_key": "NO-SUCH-PARENT"})
    lines = [changed if line.match_key == child.match_key else line for line in cockpit.bom_lines]
    predictions["nom-cockpit-core"] = cockpit.model_copy(update={"bom_lines": lines})
    score = score_bom(dataset.documents, predictions)
    assert Decimal(score.details["hierarchy_accuracy"]) < Decimal("1")
    assert any(
        failure.error_code == ErrorCode.HIERARCHY_ERROR
        for case in score.cases
        if case.case_id == "nom-cockpit-core"
        for failure in case.failures
    )
    assert not suite_satisfied(
        score,
        minimums=_MINIMUMS["bom_identification"],
        maximums={},
        zero_tolerance=False,
    )


def test_duplicate_bom_lines_fail_precision() -> None:
    dataset = build_dataset()
    predictions = _echo_documents(dataset)
    cockpit = predictions["nom-cockpit-core"]
    assert cockpit.bom_lines is not None
    doubled = list(cockpit.bom_lines) + list(cockpit.bom_lines)
    predictions["nom-cockpit-core"] = cockpit.model_copy(update={"bom_lines": doubled})
    score = score_bom(dataset.documents, predictions)
    assert Decimal(score.details["precision"]) < Decimal("0.98")
    assert any(
        failure.error_code == ErrorCode.BOM_FALSE_POSITIVE
        for case in score.cases
        if case.case_id == "nom-cockpit-core"
        for failure in case.failures
    )
    assert not suite_satisfied(
        score,
        minimums=_MINIMUMS["bom_identification"],
        maximums={},
        zero_tolerance=False,
    )


def test_missing_volume_still_checks_currency() -> None:
    dataset = build_dataset()
    adapter = EchoAdapter()
    predictions = {case.case_id: adapter.predict_cost(case) for case in dataset.costs}
    clean = score_cost(dataset.costs, predictions)
    assert suite_satisfied(
        clean,
        minimums=_MINIMUMS["cost_calculation"],
        maximums={},
        zero_tolerance=True,
    )
    missing = predictions["cost-missing-volume"].model_copy(update={"currency": "USD"})
    predictions["cost-missing-volume"] = missing
    score = score_cost(dataset.costs, predictions)
    assert any(
        failure.error_code == ErrorCode.COST_MISMATCH and failure.actual == "USD"
        for case in score.cases
        if case.case_id == "cost-missing-volume"
        for failure in case.failures
    )
    assert not suite_satisfied(
        score,
        minimums=_MINIMUMS["cost_calculation"],
        maximums={},
        zero_tolerance=True,
    )


def test_fabricated_sheet_locator_is_unsupported() -> None:
    dataset = build_dataset()
    case = next(item for item in dataset.documents if item.case_id == "nom-cockpit-core")
    prediction = EchoAdapter().predict_document(case, Path("a.pdf"), Path("a.xlsx"))
    assert prediction.citations is not None
    citations = [
        *prediction.citations,
        CitationPrediction(
            claim_path="fabricated",
            quote="物料号",
            locator="sheet:NO_SUCH_SHEET!ZZ999",
            file_role="bom_xlsx",
        ),
        CitationPrediction(
            claim_path="header",
            quote="物料号",
            locator="sheet:BOM!B1",
            file_role="bom_xlsx",
        ),
    ]
    score = score_citations([case], {case.case_id: prediction.model_copy(update={"citations": citations})})
    assert Decimal(score.details["unsupported_citation_rate"]) > Decimal("0.01")
    assert any(failure.error_code == ErrorCode.CITATION_UNSUPPORTED for item in score.cases for failure in item.failures)
    assert not any("sheet:BOM!B1" in failure.actual for item in score.cases for failure in item.failures)
    assert not suite_satisfied(
        score,
        minimums=_MINIMUMS["citation_fidelity"],
        maximums=_MAXIMUMS["citation_fidelity"],
        zero_tolerance=False,
    )


def test_price_card_accepts_valid_entries_and_rejects_bad_ones(tmp_path: Path) -> None:
    empty = build_dataset()
    assert _price_card(empty).passed
    assert _price_card(empty).observed == "unpriced"
    valid = empty.model_copy(
        update={
            "price_card": PriceCard(
                currency="USD",
                note="versioned test prices",
                models={"test-model": {"input_per_million": Decimal("1.5"), "output_per_million": Decimal("2")}},
            )
        }
    )
    assert _price_card(valid).passed
    negative = empty.model_copy(
        update={
            "price_card": PriceCard(
                currency="USD",
                note="bad prices",
                models={"test-model": {"input_per_million": Decimal("-1"), "output_per_million": Decimal("2")}},
            )
        }
    )
    assert not _price_card(negative).passed
    with pytest.raises(ValidationError):
        PriceCard.model_validate(
            {"currency": "USD", "note": "float", "models": {"test-model": {"input_per_million": 1.5}}}
        )
    report, _failures = evaluate(valid, ProductAdapter(), tmp_path)
    assert next(item for item in report.dataset_qa if item.check_id == "price_card").passed
    extraction = next(gate for gate in report.gates if gate.gate_id == "document_extraction")
    assert "dataset QA failed" not in extraction.limitation
