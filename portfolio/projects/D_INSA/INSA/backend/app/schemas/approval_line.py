from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

ApproverType = Literal["USER", "ROLE", "POSITION", "DEPT_HEAD", "DIRECT_MANAGER"]
Scope = Literal["GLOBAL", "DEPT"]


class LineStepBase(BaseModel):
    step_order: int = Field(..., ge=1)
    approver_type: ApproverType
    approver_ref: Optional[str] = Field(default=None, max_length=50)
    is_required: bool = True


class LineStepCreate(LineStepBase):
    pass


class LineStepResponse(LineStepBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    template_id: int


class LineTemplateBase(BaseModel):
    doc_type_id: int
    name: str = Field(..., max_length=100)
    scope: Scope = "GLOBAL"
    scope_ref: Optional[int] = None
    is_default: bool = False


class LineTemplateCreate(LineTemplateBase):
    steps: list[LineStepCreate] = Field(default_factory=list)


class LineTemplateUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=100)
    scope: Optional[Scope] = None
    scope_ref: Optional[int] = None
    is_default: Optional[bool] = None
    steps: Optional[list[LineStepCreate]] = None  # Full replacement when provided


class LineTemplateResponse(LineTemplateBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    steps: list[LineStepResponse] = Field(default_factory=list)
