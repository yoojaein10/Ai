from datetime import datetime

from pydantic import BaseModel, Field


class MultiIndicatorBase(BaseModel):
    round_id: int
    name: str
    description: str | None = None
    max_score: int = Field(default=5, ge=1, le=10)


class MultiIndicatorCreate(MultiIndicatorBase):
    pass


class MultiIndicatorResponse(MultiIndicatorBase):
    id: int
    created_at: datetime | None = None

    model_config = {"from_attributes": True}
