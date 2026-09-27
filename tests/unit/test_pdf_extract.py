from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from rfq_agent.tools.pdf_extract import PDFExtractError, extract_spec, section_raw_text
from tests.fixtures.build_fixtures import MiniPDF

FIXTURES = Path(__file__).parents[1] / "fixtures"


def _pdf(tmp_path: Path, build: object) -> str:
    pdf = MiniPDF()
    build(pdf)  # type: ignore[operator]
    path = tmp_path / "spec.pdf"
    pdf.save(path)
    return str(path)


def test_sections_split_by_font_size(tmp_path: Path) -> None:
    def build(pdf: MiniPDF) -> None:
        pdf.para("Intro line before any heading.")
        pdf.heading("1 Scope")
        pdf.para("Scope body text.")
        pdf.heading("2 Details")
        pdf.para("Detail one.")
        pdf.para("Detail two.")

    spec = extract_spec(_pdf(tmp_path, build))
    assert [s.title for s in spec.sections] == ["(preamble)", "1 Scope", "2 Details"]
    assert spec.sections[2].text == "Detail one.\nDetail two."
    assert spec.quantity_req is None
    assert spec.delivery_req is None
    assert spec.commercial_req_raw == []
    assert spec.quality_req is None


def test_uppercase_line_is_heading(tmp_path: Path) -> None:
    def build(pdf: MiniPDF) -> None:
        pdf.para("GENERAL NOTES")
        pdf.para("Body text here in normal case.")

    spec = extract_spec(_pdf(tmp_path, build))
    assert [s.title for s in spec.sections] == ["GENERAL NOTES"]


def test_tables_attached_and_excluded_from_text(tmp_path: Path) -> None:
    def build(pdf: MiniPDF) -> None:
        pdf.heading("3 Quantity")
        pdf.para("See table.")
        pdf.table(
            [["Item", "Value"], ["Annual volume", "1.5k"], ["Project life", "4 years"]],
            widths=[150, 150],
        )

    spec = extract_spec(_pdf(tmp_path, build))
    section = spec.sections[0]
    assert section.text == "See table."
    assert section.tables == [
        [["Item", "Value"], ["Annual volume", "1.5k"], ["Project life", "4 years"]]
    ]
    assert "Annual volume | 1.5k" in section_raw_text(section)
    assert spec.quantity_req is not None
    assert spec.quantity_req.annual_volume == Decimal("1500")
    assert spec.quantity_req.project_life_years == 4


def test_requirement_fields(tmp_path: Path) -> None:
    def build(pdf: MiniPDF) -> None:
        pdf.heading("Delivery")
        pdf.para("SOP 2027-06, Incoterm DAP.")
        pdf.para("Ship to: Plant 7")
        pdf.heading("Quality")
        pdf.para("IATF 16949, ASPICE L2, PPAP Level 2.")
        pdf.heading("Payment Terms")
        pdf.para("- 30 days net")
        pdf.para("1) No price increase in year 1")

    spec = extract_spec(_pdf(tmp_path, build))
    assert spec.delivery_req is not None
    assert (
        spec.delivery_req.sop_date,
        spec.delivery_req.incoterm,
        spec.delivery_req.delivery_location,
    ) == ("2027-06", "DAP", "Plant 7")
    assert spec.quality_req is not None
    assert spec.quality_req.standards == ["IATF 16949", "ASPICE", "PPAP"]
    assert spec.quality_req.ppap_level == 2
    assert spec.commercial_req_raw == ["30 days net", "No price increase in year 1"]


def test_quantity_section_without_numbers(tmp_path: Path) -> None:
    def build(pdf: MiniPDF) -> None:
        pdf.heading("Volume")
        pdf.para("To be confirmed by customer.")

    spec = extract_spec(_pdf(tmp_path, build))
    assert spec.quantity_req is not None
    assert spec.quantity_req.annual_volume is None
    assert spec.quantity_req.project_life_years is None


def test_fixture_case1_golden() -> None:
    spec = extract_spec(str(FIXTURES / "case1_simple_pcba" / "spec.pdf"))
    assert [s.title for s in spec.sections] == [
        "RFQ TECHNICAL SPECIFICATION",
        "1 Scope",
        "2 Housing",
        "3 Quantity",
        "4 Delivery",
        "5 Packaging",
        "6 Quality Requirements",
        "7 Commercial Terms",
    ]
    assert spec.quantity_req is not None
    assert spec.quantity_req.annual_volume == Decimal("200000")
    assert spec.quantity_req.project_life_years == 5
    assert spec.delivery_req is not None
    assert spec.delivery_req.incoterm == "FCA"
    assert spec.quality_req is not None
    assert spec.quality_req.ppap_level == 3
    assert "Payment terms: 60 days net." in spec.commercial_req_raw


def test_fixture_case2_table_quantity() -> None:
    spec = extract_spec(str(FIXTURES / "case2_cockpit_core" / "spec.pdf"))
    assert spec.quantity_req is not None
    assert spec.quantity_req.annual_volume == Decimal("150000")
    assert spec.quantity_req.project_life_years == 6
    assert spec.delivery_req is not None
    assert spec.delivery_req.sop_date == "Q3 2027"
    assert spec.quality_req is not None
    assert "AEC-Q100" in spec.quality_req.standards


def test_deterministic() -> None:
    path = str(FIXTURES / "case3_adas_camera" / "spec.pdf")
    assert extract_spec(path) == extract_spec(path)


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(PDFExtractError, match="文件不存在"):
        extract_spec(str(tmp_path / "nope.pdf"))


def test_corrupt_file(tmp_path: Path) -> None:
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"this is not a pdf")
    with pytest.raises(PDFExtractError, match="无法打开"):
        extract_spec(str(bad))


def test_pdf_without_text(tmp_path: Path) -> None:
    path = tmp_path / "empty.pdf"
    MiniPDF().save(path)
    with pytest.raises(PDFExtractError, match="无可抽取文本"):
        extract_spec(str(path))


def test_error_page_attribute() -> None:
    err = PDFExtractError("boom", page=3)
    assert err.page == 3
    assert str(err) == "boom [page 3]"
