from datetime import datetime
from typing import Literal

from pydantic import BaseModel

EvalType = Literal["PERF", "COMP", "MULTI"]
RaterType = Literal["BOSS", "PEER", "SUBORDINATE"]


class EvalApproverBase(BaseModel):
    evaluatee_id: int
    evaluator_id: int
    eval_type: EvalType
    rater_type: RaterType | None = None


class EvalApproverCreate(EvalApproverBase):
    round_id: int


class EvalApproverBulkCreate(BaseModel):
    round_id: int
    items: list[EvalApproverBase]


class EvalApproverResponse(EvalApproverBase):
    id: int
    round_id: int
    created_at: datetime | None = None

    model_config = {"from_attributes": True}
