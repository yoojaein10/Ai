from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class CalculateRequest(BaseModel):
    round_id: int


class CalculateResponse(BaseModel):
    round_id: int
    upserted: int


class GradeAdjustRequest(BaseModel):
    new_grade: str = Field(min_length=1, max_length=5)
    adjusted_reason: str = Field(min_length=1)


class ComprehensiveResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    emp_id: int
    round_id: int
    perf_score: Decimal | None = None
    comp_score: Decimal | None = None
    multi_score: Decimal | None = None
    total_score: Decimal | None = None
    original_grade: str | None = None
    final_grade: str | None = None
    is_adjusted: bool
    adjusted_by: int | None = None
    adjusted_reason: str | None = None
    calculated_at: datetime
    adjusted_at: datetime | None = None
