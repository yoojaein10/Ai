from datetime import datetime

from pydantic import BaseModel, Field


class CompEvalBossItem(BaseModel):
    indicator_id: int
    score: int = Field(ge=1, le=5)
    comment: str | None = None


class CompEvalBossBulkCreate(BaseModel):
    evaluatee_id: int
    round_id: int
    items: list[CompEvalBossItem]


class CompEvalBossResponse(BaseModel):
    id: int
    evaluatee_id: int
    evaluator_id: int
    round_id: int
    indicator_id: int
    score: int
    comment: str | None = None
    submitted_at: datetime | None = None

    model_config = {"from_attributes": True}
