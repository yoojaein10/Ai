from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ObjectionStatus = Literal["PENDING", "REVIEWED", "ACCEPTED", "REJECTED"]
ReviewDecision = Literal["ACCEPTED", "REJECTED"]


class ObjectionCreate(BaseModel):
    round_id: int
    reason: str = Field(min_length=1)


class ObjectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    emp_id: int
    round_id: int
    reason: str
    status: ObjectionStatus
    created_at: datetime


class ObjectionReviewCreate(BaseModel):
    decision: ReviewDecision
    comment: str | None = None


class ObjectionReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    objection_id: int
    reviewer_id: int
    decision: str
    comment: str | None = None
    reviewed_at: datetime
