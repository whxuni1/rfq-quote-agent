"""PDF 技术规格书 → SpecDoc。只做结构抽取（章节/表格/正则级字段），不做语义理解。

章节切分：字号明显大于正文（≥ 正文字号 × HEADING_SIZE_RATIO）或全大写短行视为标题。
表格：pdfplumber 默认（线框）策略抽取，表格区域内的文字不再重复计入正文。
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pdfplumber
import structlog

from rfq_agent.schemas.rfq import DeliveryReq, QualityReq, QuantityReq, SpecDoc, SpecSection
from rfq_agent.tools import ToolError

HEADING_SIZE_RATIO = 1.15
LINE_TOLERANCE = 3.0  # 同一行 top 坐标容差（pt）
PREAMBLE_TITLE = "(preamble)"

QUANTITY_TITLE = re.compile(r"quantit|volume|用量|数量|产量|需求量", re.IGNORECASE)
DELIVERY_TITLE = re.compile(r"deliver|logistic|shipping|交付|交货|物流", re.IGNORECASE)
COMMERCIAL_TITLE = re.compile(
    r"commercial|terms|payment|warranty|pricing|商务|条款|付款|质保|价格", re.IGNORECASE
)
QUALITY_TITLE = re.compile(r"quality|质量", re.IGNORECASE)

QUALITY_STANDARDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("IATF 16949", re.compile(r"IATF\s*16949", re.IGNORECASE)),
    ("ISO 9001", re.compile(r"ISO\s*9001", re.IGNORECASE)),
    ("ISO 14001", re.compile(r"ISO\s*14001", re.IGNORECASE)),
    ("ISO 26262", re.compile(r"ISO\s*26262", re.IGNORECASE)),
    ("ASPICE", re.compile(r"A-?SPICE", re.IGNORECASE)),
    ("AEC-Q100", re.compile(r"AEC-?Q100", re.IGNORECASE)),
    ("AEC-Q101", re.compile(r"AEC-?Q101", re.IGNORECASE)),
    ("AEC-Q104", re.compile(r"AEC-?Q104", re.IGNORECASE)),
    ("AEC-Q200", re.compile(r"AEC-?Q200", re.IGNORECASE)),
    ("APQP", re.compile(r"\bAPQP\b", re.IGNORECASE)),
    ("PPAP", re.compile(r"\bPPAP\b", re.IGNORECASE)),
)

_ANNUAL_VOLUME = re.compile(
    r"(?:annual\s+volume|volume\s+per\s+year|年用量|年需求量|年产量)\D{0,20}?"
    r"(\d[\d,]*(?:\.\d+)?)\s*(k|m|千|万)?",
    re.IGNORECASE,
)
_PROJECT_LIFE = re.compile(
    r"(?:project\s+life|lifetime|life\s*cycle|生命周期)\D{0,20}?(\d+)\s*(?:years?|yrs?|年)",
    re.IGNORECASE,
)
_SOP = re.compile(
    r"\bSOP\b\W{0,5}(\d{4}[-/.]\d{1,2}(?:[-/.]\d{1,2})?|Q[1-4]\s*\d{4}|\d{4}\s*Q[1-4])",
    re.IGNORECASE,
)
_INCOTERM = re.compile(r"\b(EXW|FCA|FAS|FOB|CFR|CIF|CPT|CIP|DAP|DPU|DDP)\b")
_LOCATION = re.compile(
    r"(?:delivery\s+location|ship\s+to|deliver\s+to|交付地点|交货地点)\s*[:：]?\s*(.+)",
    re.IGNORECASE,
)
_PPAP_LEVEL = re.compile(r"PPAP\s*(?:level|lvl\.?)\s*([1-5])", re.IGNORECASE)
_BULLET = re.compile(r"^\s*(?:[-•*·]|\d+[.)])\s*")
_MULTIPLIER = {
    "k": Decimal(1000),
    "千": Decimal(1000),
    "m": Decimal(1_000_000),
    "万": Decimal(10_000),
}


class PDFExtractError(ToolError):
    """PDF 抽取失败。`page` 为出错页码（1-based），未知为 None。"""

    def __init__(self, message: str, page: int | None = None) -> None:
        super().__init__(f"{message} [page {page}]" if page is not None else message)
        self.page = page


@dataclass
class _Line:
    page: int
    top: float
    text: str
    size: float


@dataclass
class _Table:
    page: int
    top: float
    rows: list[list[str]]


@dataclass
class _Section:
    title: str
    lines: list[str] = field(default_factory=list)
    tables: list[list[list[str]]] = field(default_factory=list)


def extract_spec(pdf_path: str) -> SpecDoc:
    log = structlog.get_logger().bind(tool=__name__, step="extract_spec", file=pdf_path)
    if not Path(pdf_path).is_file():
        raise PDFExtractError(f"文件不存在: {pdf_path}")
    lines, tables = _read_pdf(pdf_path)
    if not lines and not tables:
        raise PDFExtractError(f"PDF 无可抽取文本（扫描件需 OCR，本系统不支持）: {pdf_path}")
    sections = _split_sections(lines, tables)
    spec = SpecDoc(
        sections=[
            SpecSection(title=s.title, text="\n".join(s.lines), tables=s.tables) for s in sections
        ],
        quantity_req=_quantity_req(sections),
        delivery_req=_delivery_req(sections),
        commercial_req_raw=_commercial_req(sections),
        quality_req=_quality_req(sections),
    )
    log.info("spec_extracted", sections=len(spec.sections), tables=len(tables))
    return spec


def section_raw_text(section: SpecSection) -> str:
    """章节正文 + 表格（行内以 " | " 连接），供正则与 LLM 摘要使用。"""
    table_lines = [" | ".join(row) for table in section.tables for row in table]
    return "\n".join([section.text, *table_lines]).strip()


# ---------------------------------------------------------------------------
# 读取
# ---------------------------------------------------------------------------


def _read_pdf(pdf_path: str) -> tuple[list[_Line], list[_Table]]:
    lines: list[_Line] = []
    tables: list[_Table] = []
    try:
        pdf = pdfplumber.open(pdf_path)
    except Exception as exc:  # pdfminer 对坏文件抛多种异常，统一转 ToolError
        raise PDFExtractError(f"无法打开 PDF: {exc}") from exc
    with pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            try:
                found = page.find_tables()
                bboxes = [t.bbox for t in found]
                for table in found:
                    rows = [[_clean(cell) for cell in row] for row in table.extract()]
                    tables.append(_Table(page=page_no, top=float(table.bbox[1]), rows=rows))
                words = page.extract_words(extra_attrs=["size"], use_text_flow=True)
            except Exception as exc:
                raise PDFExtractError(f"页面解析失败: {exc}", page=page_no) from exc
            body_words = [w for w in words if not _in_any_bbox(w, bboxes)]
            lines.extend(_group_lines(page_no, body_words))
    return lines, tables


def _clean(cell: Any) -> str:
    return re.sub(r"\s+", " ", str(cell)).strip() if cell is not None else ""


def _in_any_bbox(word: dict[str, Any], bboxes: Sequence[tuple[float, float, float, float]]) -> bool:
    cx = (float(word["x0"]) + float(word["x1"])) / 2
    cy = (float(word["top"]) + float(word["bottom"])) / 2
    return any(x0 <= cx <= x1 and top <= cy <= bottom for x0, top, x1, bottom in bboxes)


def _group_lines(page_no: int, words: Sequence[dict[str, Any]]) -> list[_Line]:
    ordered = sorted(words, key=lambda w: (round(float(w["top"])), float(w["x0"])))
    lines: list[_Line] = []
    bucket: list[dict[str, Any]] = []
    for word in ordered:
        if bucket and abs(float(word["top"]) - float(bucket[0]["top"])) > LINE_TOLERANCE:
            lines.append(_make_line(page_no, bucket))
            bucket = []
        bucket.append(word)
    if bucket:
        lines.append(_make_line(page_no, bucket))
    return lines


def _make_line(page_no: int, words: list[dict[str, Any]]) -> _Line:
    words = sorted(words, key=lambda w: float(w["x0"]))
    return _Line(
        page=page_no,
        top=float(words[0]["top"]),
        text=" ".join(str(w["text"]) for w in words),
        size=max(float(w["size"]) for w in words),
    )


# ---------------------------------------------------------------------------
# 章节切分
# ---------------------------------------------------------------------------


def _body_size(lines: Sequence[_Line]) -> float:
    weights: Counter[float] = Counter()
    for line in lines:
        weights[round(line.size, 1)] += len(line.text)
    if not weights:
        return 0.0
    # 字符数最多的字号为正文；并列时取较小字号（标题通常更大）
    return max(weights.items(), key=lambda kv: (kv[1], -kv[0]))[0]


def _is_heading(line: _Line, body_size: float) -> bool:
    if body_size and line.size >= body_size * HEADING_SIZE_RATIO:
        return True
    letters = [c for c in line.text if c.isalpha()]
    return (
        len(letters) >= 3
        and len(line.text) <= 80
        and all(c.isupper() for c in letters if c.isascii())
        and all(c.isascii() for c in letters)
    )


def _split_sections(lines: Sequence[_Line], tables: Sequence[_Table]) -> list[_Section]:
    body = _body_size(lines)
    items: list[tuple[int, float, int, _Line | _Table]] = [(ln.page, ln.top, 0, ln) for ln in lines]
    items.extend((t.page, t.top, 1, t) for t in tables)
    items.sort(key=lambda it: (it[0], it[1], it[2]))

    sections: list[_Section] = []
    current = _Section(title=PREAMBLE_TITLE)
    for _, _, _, item in items:
        if isinstance(item, _Table):
            current.tables.append(item.rows)
        elif _is_heading(item, body):
            if current.lines or current.tables or current.title != PREAMBLE_TITLE:
                sections.append(current)
            current = _Section(title=item.text.strip())
        else:
            current.lines.append(item.text)
    if current.lines or current.tables or current.title != PREAMBLE_TITLE:
        sections.append(current)
    return sections


# ---------------------------------------------------------------------------
# 正则级字段抽取（结构抽取，不做语义判断）
# ---------------------------------------------------------------------------


def _raw(section: _Section) -> str:
    table_lines = [" | ".join(row) for table in section.tables for row in table]
    return "\n".join([*section.lines, *table_lines]).strip()


def _matching(sections: Sequence[_Section], pattern: re.Pattern[str]) -> list[_Section]:
    return [s for s in sections if pattern.search(s.title)]


def _to_decimal(number: str, suffix: str | None) -> Decimal | None:
    try:
        value = Decimal(number.replace(",", ""))
    except InvalidOperation:
        return None
    return value * _MULTIPLIER.get((suffix or "").lower(), Decimal(1))


def _quantity_req(sections: Sequence[_Section]) -> QuantityReq | None:
    matched = _matching(sections, QUANTITY_TITLE)
    if not matched:
        return None
    raw = "\n".join(_raw(s) for s in matched)
    volume_match = _ANNUAL_VOLUME.search(raw)
    life_match = _PROJECT_LIFE.search(raw)
    return QuantityReq(
        annual_volume=_to_decimal(*volume_match.groups()) if volume_match else None,
        project_life_years=int(life_match.group(1)) if life_match else None,
        raw_text=raw,
    )


def _delivery_req(sections: Sequence[_Section]) -> DeliveryReq | None:
    matched = _matching(sections, DELIVERY_TITLE)
    if not matched:
        return None
    raw = "\n".join(_raw(s) for s in matched)
    sop = _SOP.search(raw)
    incoterm = _INCOTERM.search(raw)
    location = _LOCATION.search(raw)
    return DeliveryReq(
        sop_date=sop.group(1) if sop else None,
        incoterm=incoterm.group(1) if incoterm else None,
        delivery_location=location.group(1).strip() if location else None,
        raw_text=raw,
    )


def _commercial_req(sections: Sequence[_Section]) -> list[str]:
    clauses: list[str] = []
    for section in _matching(sections, COMMERCIAL_TITLE):
        for line in section.lines:
            text = _BULLET.sub("", line).strip()
            if text:
                clauses.append(text)
    return clauses


def _quality_req(sections: Sequence[_Section]) -> QualityReq | None:
    full_text = "\n".join(f"{s.title}\n{_raw(s)}" for s in sections)
    standards = [name for name, pattern in QUALITY_STANDARDS if pattern.search(full_text)]
    matched = _matching(sections, QUALITY_TITLE)
    if not standards and not matched:
        return None
    ppap = _PPAP_LEVEL.search(full_text)
    return QualityReq(
        standards=standards,
        ppap_level=int(ppap.group(1)) if ppap else None,
        raw_text="\n".join(_raw(s) for s in matched),
    )
