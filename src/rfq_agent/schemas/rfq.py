"""RFQ 输入域：RFQPackage / SpecDoc / DrawingRef / AmbiguityFlag（docs/02 §1）。

注：`QuantityReq` / `DeliveryReq` / `QualityReq` 在 docs/02 中只给了类型名，
字段为本任务（Task 15）补充的最小集合，均保留 `raw_text` 以便下游 LLM 复读原文。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from rfq_agent.schemas.bom import BOMTree

AmbiguityCategory = Literal[
    "spec_gap",
    "qty_ambiguous",
    "uom_ambiguous",
    "source_conflict",
    "drawing_missing",
    "term_undefined",
]


class SpecSection(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str
    text: str
    tables: list[list[list[str]]]


class QuantityReq(BaseModel):
    model_config = ConfigDict(frozen=True)

    annual_volume: Decimal | None = Field(default=None, ge=0)
    project_life_years: int | None = Field(default=None, ge=0)
    raw_text: str


class DeliveryReq(BaseModel):
    model_config = ConfigDict(frozen=True)

    sop_date: str | None = None  # 原文日期串，不做解析
    incoterm: str | None = None
    delivery_location: str | None = None
    raw_text: str


class QualityReq(BaseModel):
    model_config = ConfigDict(frozen=True)

    standards: list[str]  # IATF 16949 / ISO 9001 / AEC-Q100 ...
    ppap_level: int | None = Field(default=None, ge=1, le=5)
    raw_text: str


class SpecDoc(BaseModel):
    model_config = ConfigDict(frozen=True)

    sections: list[SpecSection]  # 技术规格章节
    quantity_req: QuantityReq | None
    delivery_req: DeliveryReq | None
    commercial_req_raw: list[str]  # 原文商业条款片段，待 ComAgent 解析
    quality_req: QualityReq | None  # PPAP/APQP/ISO/IATF 等级要求


class DrawingRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    ref_id: str
    file_name: str
    revision: str | None
    referenced_in_line_no: str | None


class AmbiguityFlag(BaseModel):
    model_config = ConfigDict(frozen=True)

    flag_id: str
    category: AmbiguityCategory
    description: str
    related_line_no: str | None
    severity: Literal["low", "medium", "high"]


class RFQPackage(BaseModel):
    model_config = ConfigDict(frozen=True)

    rfq_id: str
    customer: str
    project_name: str
    received_at: datetime
    spec_doc: SpecDoc
    bom_tree: BOMTree
    drawing_refs: list[DrawingRef]
    ambiguity_flags: list[AmbiguityFlag]  # Ingestion 阶段就标出的歧义
    raw_files: list[str]  # 原始文件路径，仅 trace
