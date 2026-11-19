"""Evaluation framework tests.

Product gates are expected to fail closed on this repository. Scorer tests use
an in-memory echo of the labels and never write that echo into the regression report.
"""

from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError
from tests.eval.echo import EchoAdapter

from rfq_eval.adapt import AdapterSchemaError, ProductAdapter, map_bom, map_spec
from rfq_eval.case_library import build_dataset
from rfq_eval.dataset_io import dataset_sha256, load_dataset, materialize
from rfq_eval.dataset_qa import qa_passed, run_dataset_qa
from rfq_eval.label_audit import piece_price, project_value
from rfq_eval.metrics import score_isolation
from rfq_eval.runner import evaluate
from rfq_eval.schema import (
    EvaluationReport,
    GateResult,
    IsolationPrediction,
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
        pytest.skip("dataset is materialized by the eval command")
    assert load_dataset(root / "eval" / "dataset") == build_dataset()
    stored = (root / "eval" / "reports" / "regression_report.json").read_text(encoding="utf-8")
    loaded = EvaluationReport.model_validate_json(stored)
    assert loaded.production_ready is False
    assert loaded.versions.dataset_sha256 == dataset_sha256(build_dataset())
