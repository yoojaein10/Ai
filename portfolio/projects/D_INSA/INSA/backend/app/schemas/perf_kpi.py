from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class PerfKpiBase(BaseModel):
    code: str
    name: str
    measure_type: str | None = None
    weight: Decimal | None = None
    perspective: str | None = None


class PerfKpiCreate(PerfKpiBase):
    round_id: int


class PerfKpiUpdate(BaseModel):
    code: str | None = None
    name: str | None = None
    measure_type: str | None = None
    weight: Decimal | None = None
    perspective: str | None = None


class PerfKpiResponse(PerfKpiBase):
    id: int
    round_id: int
    created_at: datetime | None = None

    model_config = {"from_attributes": True}
