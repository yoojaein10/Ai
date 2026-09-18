from datetime import datetime

from pydantic import BaseModel, Field


class CompEvalSelfItem(BaseModel):
    indicator_id: int
    score: int = Field(ge=1, le=5)
    comment: str | None = None


class CompEvalSelfBulkCreate(BaseModel):
    round_id: int
    items: list[CompEvalSelfItem]


class CompEvalSelfResponse(BaseModel):
    id: int
    emp_id: int
    round_id: int
    indicator_id: int
    score: int
    comment: str | None = None
    submitted_at: datetime | None = None

    model_config = {"from_attributes": True}
