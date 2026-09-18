from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Category = Literal["HR", "ATTENDANCE", "TRAVEL", "CONTRACT", "OTHER"]


class ApprovalDocTypeBase(BaseModel):
    code: str = Field(..., max_length=30)
    name: str = Field(..., max_length=100)
    category: Category
    description: Optional[str] = Field(default=None, max_length=500)
    is_active: bool = True


class ApprovalDocTypeCreate(ApprovalDocTypeBase):
    pass


class ApprovalDocTypeUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=100)
    category: Optional[Category] = None
    description: Optional[str] = Field(default=None, max_length=500)
    is_active: Optional[bool] = None


class ApprovalDocTypeResponse(ApprovalDocTypeBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
