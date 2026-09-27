from __future__ import annotations

import asyncio
import json
import shutil
import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from rfq_agent.agents.ingestion import IngestionAgent, IngestionError
from rfq_agent.llm import LLMError, MockLLMClient
from rfq_agent.schemas.bom import MaterialClass
from rfq_agent.schemas.intent import QuoteIntent
from rfq_agent.schemas.rfq import RFQPackage

FIXTURES = Path(__file__).parents[1] / "fixtures"
CASES = ["case1_simple_pcba", "case2_cockpit_core", "case3_adas_camera"]
FIXED_NOW = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)


def _replay(case: str) -> list[str]:
    raw = json.loads((FIXTURES / case / "llm_ingestion.json").read_text(encoding="utf-8"))
    return [json.dumps(r) for r in raw]


def _run(
    case: str, responses: list[str] | None = None, **kwargs: Any
) -> tuple[RFQPackage, QuoteIntent, MockLLMClient]:
    llm = MockLLMClient(responses if responses is not None else _replay(case))
    agent = IngestionAgent(llm, clock=lambda: FIXED_NOW)
    d = FIXTURES / case
    package, intent = asyncio.run(
        agent.run(str(d / "spec.pdf"), str(d / "bom.xlsx"), case, **kwargs)
    )
    return package, intent, llm


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def guard(*args: object, **kwargs: object) -> None:
        raise AssertionError("ingestion 不得发起网络调用")

    # 只拦截对外连接；asyncio 事件循环内部的 socketpair 不受影响
    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket.socket, "connect_ex", guard)
    monkeypatch.setattr(socket, "create_connection", guard)
    monkeypatch.setattr(socket, "getaddrinfo", guard)


@pytest.mark.parametrize("case", CASES)
def test_fixtures_produce_valid_package(case: str, no_network: None) -> None:
    package, intent, llm = _run(case)
    # schema 往返：序列化后可被严格重建
    assert RFQPackage.model_validate_json(package.model_dump_json()) == package
    assert package.rfq_id == case
    assert package.received_at == FIXED_NOW
    assert package.customer != "UNKNOWN" and package.project_name != "UNKNOWN"
    assert package.raw_files[:2] == [
        str(FIXTURES / case / "spec.pdf"),
        str(FIXTURES / case / "bom.xlsx"),
    ]
    assert [f.flag_id for f in package.ambiguity_flags] == [
        f"AMB-{i:03d}" for i in range(1, len(package.ambiguity_flags) + 1)
    ]
    assert len(llm.calls) == 1
    assert llm.calls[0][0]["role"] == "system"
    assert "Ingestion Analyst" in llm.calls[0][0]["content"]
    assert isinstance(intent, QuoteIntent)


def test_case1_clean_no_flags() -> None:
    package, intent, _ = _run("case1_simple_pcba")
    assert package.customer == "Acme Automotive Co."
    assert package.ambiguity_flags == []
    assert [
        (r.ref_id, r.file_name, r.revision, r.referenced_in_line_no) for r in package.drawing_refs
    ] == [("DWG-1001", "DWG-1001_RevA.pdf", "A", "1")]
    assert any(f.endswith("DWG-1001_RevA.pdf") for f in package.raw_files)
    assert intent.currency == "USD"


def test_case2_multilevel_bom_and_qty_conflict() -> None:
    package, _, _ = _run("case2_cockpit_core")
    tree = package.bom_tree
    assert tree.root.level == 0 and "assembly" in tree.root.part_desc.lower()
    assert max(n.level for n in tree.nodes) >= 2
    level2 = {n.material_class for n in tree.nodes if n.level == 2}
    assert {MaterialClass.SOC, MaterialClass.MEMORY} <= level2
    soc = next(
        n
        for n in tree.nodes
        if n.material_class is MaterialClass.SOC and n.level == 2 and n.part_no == "SA8295P"
    )
    assert soc.single_source_risk is True and soc.auto_grade_required is True
    qty_flags = [f for f in package.ambiguity_flags if f.category == "qty_ambiguous"]
    assert len(qty_flags) == 1 and qty_flags[0].related_line_no == "4"
    # LLM 补充的语义歧义被保留
    assert any(f.category == "term_undefined" for f in package.ambiguity_flags)


def test_case3_spec_gap_and_rule_flags() -> None:
    package, intent, _ = _run("case3_adas_camera")
    by_category = {f.category: f for f in package.ambiguity_flags}
    assert by_category["spec_gap"].severity == "high"
    assert "OPTICS" in by_category["spec_gap"].description
    assert by_category["source_conflict"].related_line_no == "40"
    assert by_category["uom_ambiguous"].related_line_no == "60"
    assert by_category["drawing_missing"].description.startswith("Drawing DWG-3002")
    # LLM 的 spec_gap 与规则重复（同 category + line），只保留规则那条
    assert sum(f.category == "spec_gap" for f in package.ambiguity_flags) == 1
    assert intent.currency == "EUR"


def test_retry_once_on_invalid_output() -> None:
    good = _replay("case1_simple_pcba")[0]
    package, _, llm = _run("case1_simple_pcba", responses=["not json at all", good])
    assert package.ambiguity_flags == []
    assert len(llm.calls) == 2
    retry_msgs = llm.calls[1]
    assert retry_msgs[-2] == {"role": "assistant", "content": "not json at all"}
    assert "schema 校验" in retry_msgs[-1]["content"]


def test_retry_on_schema_violation_then_fail() -> None:
    bad_currency = json.loads(_replay("case1_simple_pcba")[0])
    bad_currency["quote_intent"]["currency"] = "dollars"
    bad = json.dumps(bad_currency)
    with pytest.raises(IngestionError, match="LLM 理解步骤失败") as info:
        _run("case1_simple_pcba", responses=[bad, '{"ambiguity_flags": []}'])
    assert len(info.value.details) == 2
    assert "currency" in info.value.details[0]
    assert "quote_intent" in info.value.details[1]


def test_llm_error_exhausts_retries() -> None:
    with pytest.raises(IngestionError) as info:
        _run("case1_simple_pcba", responses=[])
    assert all("LLM 调用失败" in d for d in info.value.details)


def test_fenced_json_accepted() -> None:
    fenced = "```json\n" + _replay("case1_simple_pcba")[0] + "\n```"
    package, _, _ = _run("case1_simple_pcba", responses=[fenced])
    assert package.rfq_id == "case1_simple_pcba"


def test_tool_error_becomes_ingestion_error(tmp_path: Path) -> None:
    agent = IngestionAgent(MockLLMClient([]))
    with pytest.raises(IngestionError, match="extract_spec") as info:
        asyncio.run(agent.run(str(tmp_path / "x.pdf"), str(tmp_path / "x.xlsx"), "R"))
    assert info.value.details


def test_package_dir_controls_drawing_lookup(tmp_path: Path) -> None:
    # 图纸目录为空 → case1 的 DWG-1001 缺失
    package, _, _ = _run("case1_simple_pcba", package_dir=str(tmp_path))
    assert [f.category for f in package.ambiguity_flags] == ["drawing_missing"]
    assert package.ambiguity_flags[0].related_line_no == "1"


def test_unknown_customer_flagged(tmp_path: Path) -> None:
    from tests.fixtures.build_fixtures import MiniPDF

    pdf = MiniPDF()
    pdf.heading("1 Scope")
    pdf.para("Nothing about who is asking.")
    pdf.save(tmp_path / "spec.pdf")
    shutil.copy(FIXTURES / "case1_simple_pcba" / "bom.xlsx", tmp_path / "bom.xlsx")
    llm = MockLLMClient(_replay("case1_simple_pcba"))
    package, _ = asyncio.run(
        IngestionAgent(llm).run(str(tmp_path / "spec.pdf"), str(tmp_path / "bom.xlsx"), "R")
    )
    assert (package.customer, package.project_name) == ("UNKNOWN", "UNKNOWN")
    assert package.bom_tree.root.part_no == "BCM-ASSY-01"
    undefined = [f for f in package.ambiguity_flags if f.category == "term_undefined"]
    assert len(undefined) == 2
    assert any(f.category == "drawing_missing" for f in package.ambiguity_flags)


def test_deterministic_across_runs() -> None:
    first, intent1, _ = _run("case3_adas_camera")
    second, intent2, _ = _run("case3_adas_camera")
    assert first == second and intent1 == intent2


def test_mock_client_from_file_and_errors(tmp_path: Path) -> None:
    path = tmp_path / "r.json"
    path.write_text('["plain", {"a": 1}]', encoding="utf-8")
    llm = MockLLMClient.from_file(path)
    assert asyncio.run(llm.chat([{"role": "user", "content": "x"}])) == "plain"
    assert asyncio.run(llm.chat([])) == '{"a": 1}'
    with pytest.raises(LLMError):
        asyncio.run(llm.chat([]))
    path.write_text('{"not": "a list"}', encoding="utf-8")
    with pytest.raises(ValueError, match="数组"):
        MockLLMClient.from_file(path)
