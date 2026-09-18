from datetime import date
from typing import Literal

from pydantic import BaseModel

ScheduleStage = Literal["TARGET", "MID", "FINAL", "COMPREHENSIVE"]


class EvalScheduleBase(BaseModel):
    stage: ScheduleStage
    start_date: date | None = None
    end_date: date | None = None


class EvalScheduleCreate(EvalScheduleBase):
    round_id: int


class EvalScheduleBulkCreate(BaseModel):
    round_id: int
    schedules: list[EvalScheduleBase]


class EvalScheduleResponse(EvalScheduleBase):
    id: int
    round_id: int

    model_config = {"from_attributes": True}
