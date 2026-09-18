from datetime import datetime

from pydantic import BaseModel, Field


class GradeCriterion(BaseModel):
    grade: str
    min: float
    max: float
    default_ratio: float = 0


class EvalSettingUpsert(BaseModel):
    year: int
    weight_config: dict[str, float] = Field(default_factory=dict)  # e.g., {"perf":40,"comp":30,"multi":30}
    grade_criteria: list[GradeCriterion] = Field(default_factory=list)


class EvalSettingResponse(BaseModel):
    id: int
    year: int
    weight_config: dict[str, float] = Field(default_factory=dict)
    grade_criteria: list[GradeCriterion] = Field(default_factory=list)
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}
