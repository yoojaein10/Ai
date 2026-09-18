from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class CompBehaviorBase(BaseModel):
    level: int = Field(ge=1, le=5)
    description: str | None = None


class CompBehaviorCreate(CompBehaviorBase):
    pass


class CompBehaviorResponse(CompBehaviorBase):
    id: int
    indicator_id: int

    model_config = {"from_attributes": True}


class CompIndicatorBase(BaseModel):
    year: int
    code: str
    name: str
    description: str | None = None
    weight: Decimal | None = None


class CompIndicatorCreate(CompIndicatorBase):
    behaviors: list[CompBehaviorCreate] = []


class CompIndicatorResponse(CompIndicatorBase):
    id: int
    created_at: datetime | None = None
    behaviors: list[CompBehaviorResponse] = []

    model_config = {"from_attributes": True}
