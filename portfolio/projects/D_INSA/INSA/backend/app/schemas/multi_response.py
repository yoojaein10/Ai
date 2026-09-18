from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

RaterType = Literal["BOSS", "PEER", "SUBORDINATE"]


class MultiResponseItem(BaseModel):
    indicator_id: int
    score: Decimal = Field(ge=0)
    comment: str | None = None


class MultiResponseSubmit(BaseModel):
    round_id: int
    evaluatee_id: int
    rater_type: RaterType
    items: list[MultiResponseItem]


class MyEvalTarget(BaseModel):
    evaluatee_id: int
    evaluatee_emp_no: str
    evaluatee_name: str
    rater_type: RaterType
    submitted: bool


class MultiSubmissionStatus(BaseModel):
    """관리자 제출률 (이름 미노출)."""

    round_id: int
    expected: int
    submitted: int
    submission_rate: float
    submitted_at_latest: datetime | None = None
