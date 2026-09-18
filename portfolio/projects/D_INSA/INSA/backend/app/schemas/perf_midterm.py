from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class PerfMidtermBase(BaseModel):
    progress_rate: Decimal | None = None
    description: str | None = None
    expected_rate: Decimal | None = None


class PerfMidtermUpsert(PerfMidtermBase):
    target_id: int


class PerfMidtermResponse(PerfMidtermBase):
    id: int
    target_id: int
    submitted_at: datetime | None = None

    model_config = {"from_attributes": True}
