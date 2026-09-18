from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class PerfResultBase(BaseModel):
    score: Decimal | None = None
    grade: str | None = None
    comment: str | None = None


class PerfResultCreate(PerfResultBase):
    emp_id: int
    round_id: int


class PerfResultResponse(PerfResultBase):
    id: int
    emp_id: int
    round_id: int
    evaluator_id: int
    created_at: datetime | None = None

    model_config = {"from_attributes": True}
