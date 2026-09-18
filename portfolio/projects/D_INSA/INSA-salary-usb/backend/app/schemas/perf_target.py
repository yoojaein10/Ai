from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

TargetStatus = Literal["DRAFT", "SUBMITTED", "APPROVED", "REJECTED"]


class PerfTargetBase(BaseModel):
    kpi_id: int | None = None
    target_value: str | None = None
    is_organization: bool = False
    weight_percent: Decimal | None = None


class PerfTargetCreate(PerfTargetBase):
    emp_id: int
    round_id: int


class PerfTargetUpdate(BaseModel):
    kpi_id: int | None = None
    target_value: str | None = None
    is_organization: bool | None = None
    weight_percent: Decimal | None = None


class PerfTargetReject(BaseModel):
    comment: str | None = None


class PerfTargetResponse(PerfTargetBase):
    id: int
    emp_id: int
    round_id: int
    status: TargetStatus
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}
