"""跨模块数据结构（Pydantic v2，frozen）。"""

from rfq_agent.schemas.bom import BOMLine, BOMTree, MaterialClass
from rfq_agent.schemas.intent import QuoteIntent
from rfq_agent.schemas.rfq import (
    AmbiguityFlag,
    DeliveryReq,
    DrawingRef,
    QualityReq,
    QuantityReq,
    RFQPackage,
    SpecDoc,
    SpecSection,
)

__all__ = [
    "AmbiguityFlag",
    "BOMLine",
    "BOMTree",
    "DeliveryReq",
    "DrawingRef",
    "MaterialClass",
    "QualityReq",
    "QuantityReq",
    "QuoteIntent",
    "RFQPackage",
    "SpecDoc",
    "SpecSection",
]
