"""Build text PDFs and workbooks from labeled cases.

The PDF font is a system CJK font so Chinese quotes survive extraction.
Dataset QA reads those files back; the product is not invoked here.
"""

from pathlib import Path

from openpyxl import Workbook
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from rfq_eval.schema import DocumentCase

_FONT: str | None = None


def cjk_font_path() -> Path:
    candidates = (
        Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
        Path("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"),
    )
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError(
        "No CJK font found. Install fonts-wqy-microhei or fonts-droid-fallback."
    )


def _font_name() -> str:
    global _FONT
    if _FONT is not None:
        return _FONT
    path = cjk_font_path()
    if path.suffix == ".ttc":
        pdfmetrics.registerFont(TTFont("RFQEvalCJK", str(path), subfontIndex=0))
    else:
        pdfmetrics.registerFont(TTFont("RFQEvalCJK", str(path)))
    _FONT = "RFQEvalCJK"
    return _FONT


def write_pdf(case: DocumentCase, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    style = ParagraphStyle(name="rfq", fontName=_font_name(), fontSize=11, leading=16)
    story: list[Paragraph | Spacer] = []
    for section in case.sections:
        story.append(Paragraph(section.title, style))
        for paragraph in section.paragraphs:
            story.append(Paragraph(_xml(paragraph), style))
        for table in section.tables:
            for row in table:
                story.append(Paragraph(_xml(" | ".join(row)), style))
        story.append(Spacer(1, 8))
    doc = SimpleDocTemplate(str(path), pagesize=A4, title=case.case_id, author="rfq-eval")
    doc.build(story)


def write_xlsx(case: DocumentCase, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    book = Workbook()
    default = book.active
    if default is None:
        raise RuntimeError("workbook has no active sheet")
    book.remove(default)
    for sheet in case.sheets:
        grid = book.create_sheet(sheet.name)
        grid.append(sheet.headers)
        for row in sheet.rows:
            grid.append(row)
    book.save(path)


def _xml(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
