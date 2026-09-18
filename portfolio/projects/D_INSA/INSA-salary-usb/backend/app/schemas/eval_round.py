from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

RoundStatus = Literal["PLANNED", "IN_PROGRESS", "CLOSED"]


class EvalRoundBase(BaseModel):
    year: int
    name: str
    start_date: date | None = None
    end_date: date | None = None


class EvalRoundCreate(EvalRoundBase):
    status: RoundStatus = "PLANNED"


class EvalRoundUpdate(BaseModel):
    name: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    status: RoundStatus | None = None


class EvalRoundResponse(EvalRoundBase):
    id: int
    status: RoundStatus
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}
