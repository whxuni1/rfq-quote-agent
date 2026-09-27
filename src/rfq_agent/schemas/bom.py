"""BOM 域：BOMTree / BOMLine / MaterialClass（docs/02 §1）。"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MaterialClass(str, Enum):
    SOC = "SOC"
    MCU = "MCU"
    MEMORY = "MEMORY"
    DISPLAY = "DISPLAY"
    CAMERA = "CAMERA"
    SENSOR = "SENSOR"
    OPTICS = "OPTICS"
    PCBA = "PCBA"
    CONNECTOR = "CONNECTOR"
    HOUSING = "HOUSING"
    HARNESS = "HARNESS"
    THERMAL = "THERMAL"
    SOFTWARE = "SOFTWARE"
    PACKAGING = "PACKAGING"
    OTHER = "OTHER"


class BOMLine(BaseModel):
    model_config = ConfigDict(frozen=True)

    line_no: str
    level: int = Field(ge=0)  # 0=成品,1=子组件,2+... 多级
    parent_line_no: str | None
    part_no: str
    part_desc: str
    material_class: MaterialClass
    qty_per: Decimal = Field(gt=0)
    uom: str  # EA, SET, M, G...
    source_hint: str | None  # 客户指定源/厂商
    auto_grade_required: bool  # AEC-Q100 等要求
    single_source_risk: bool | None  # Ingestion 预判，ProcAgent 复核
    attributes: dict[str, str]  # 规格键值（如容量/速率/封装）

    @model_validator(mode="after")
    def _check_parent(self) -> BOMLine:
        if self.level == 0 and self.parent_line_no is not None:
            raise ValueError(f"line {self.line_no}: level=0 时 parent_line_no 必须为 None")
        if self.level > 0 and self.parent_line_no is None:
            raise ValueError(f"line {self.line_no}: level>0 时 parent_line_no 不能为空")
        return self


class BOMTree(BaseModel):
    model_config = ConfigDict(frozen=True)

    root: BOMLine
    nodes: list[BOMLine]  # 含 root，平铺但带 level/parent
    currency_hint: str | None
    total_lines: int

    @model_validator(mode="after")
    def _check_tree(self) -> BOMTree:
        if self.root.level != 0:
            raise ValueError("root.level 必须为 0")
        by_no: dict[str, BOMLine] = {}
        for node in self.nodes:
            if node.line_no in by_no:
                raise ValueError(f"line_no 重复: {node.line_no}")
            by_no[node.line_no] = node
        if by_no.get(self.root.line_no) != self.root:
            raise ValueError("nodes 必须包含 root")
        if sum(1 for n in self.nodes if n.level == 0) != 1:
            raise ValueError("BOMTree 必须恰有一个 level=0 节点")
        for node in self.nodes:
            if node.parent_line_no is None:
                continue
            parent = by_no.get(node.parent_line_no)
            if parent is None:
                raise ValueError(
                    f"line {node.line_no}: parent_line_no={node.parent_line_no} 不存在"
                )
            if parent.level != node.level - 1:
                raise ValueError(
                    f"line {node.line_no}: level={node.level} 与父件 level={parent.level} 不连续"
                )
        if self.total_lines != len(self.nodes):
            raise ValueError("total_lines 必须等于 len(nodes)")
        return self
