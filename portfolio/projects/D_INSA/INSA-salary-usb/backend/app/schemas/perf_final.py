from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class PerfFinalBase(BaseModel):
    achievement_rate: Decimal | None = None
    description: str | None = None
    self_score: Decimal | None = None


class PerfFinalUpsert(PerfFinalBase):
    target_id: int


class PerfFinalResponse(PerfFinalBase):
    id: int
    target_id: int
    submitted_at: datetime | None = None

    model_config = {"from_attributes": True}
