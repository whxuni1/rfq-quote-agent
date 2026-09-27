"""报价意图：QuoteIntent（docs/02 §2）。"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AgentName = Literal["engineering", "procurement", "finance", "commercial"]


class QuoteIntent(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_type: Literal["NPI", "NPI+Mass", "Mass_only", "Retrofit", "Spare"]
    annual_volume: Decimal | None = Field(ge=0)
    peak_monthly_volume: Decimal | None = Field(ge=0)
    project_life_years: int | None = Field(ge=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")  # ISO 4217
    incoterm_target: str | None
    payment_terms_target: str | None
    nre_scope: list[str]  # tooling/jigs/validation/software_license
    special_reqs: list[str]  # 保修/回收/本地化等
    skip_agents: list[AgentName]
