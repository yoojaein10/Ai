from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Scope = Literal["COMPANY", "DEPT", "PERSONAL"]


class CalendarBase(BaseModel):
    name: str = Field(..., max_length=100)
    color_hex: str = Field(default="#1677ff", max_length=9)
    scope: Scope = "COMPANY"
    scope_ref: Optional[int] = None
    is_default: bool = False


class CalendarCreate(CalendarBase):
    pass


class CalendarUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=100)
    color_hex: Optional[str] = Field(default=None, max_length=9)
    scope: Optional[Scope] = None
    scope_ref: Optional[int] = None
    is_default: Optional[bool] = None


class CalendarResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    color_hex: str
    scope: Scope
    scope_ref: Optional[int] = None
    is_default: bool
    created_by: Optional[int] = None
    created_at: Optional[datetime] = None
