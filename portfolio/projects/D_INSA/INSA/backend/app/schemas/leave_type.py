from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

DeductFrom = Literal["ANNUAL", "SEPARATE"]
LeaveUnit = Literal["DAY", "HALF_DAY", "HOUR"]


class LeaveTypeBase(BaseModel):
    code: str = Field(..., max_length=20)
    name: str = Field(..., max_length=50)
    deduct_from: DeductFrom = "ANNUAL"
    unit: LeaveUnit = "DAY"
    is_paid: bool = True
    requires_evidence: bool = False
    sort_order: int = 0
    is_active: bool = True


class LeaveTypeCreate(LeaveTypeBase):
    pass


class LeaveTypeUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=50)
    deduct_from: Optional[DeductFrom] = None
    unit: Optional[LeaveUnit] = None
    is_paid: Optional[bool] = None
    requires_evidence: Optional[bool] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class LeaveTypeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    deduct_from: DeductFrom
    unit: LeaveUnit
    is_paid: bool
    requires_evidence: bool
    sort_order: int
    is_active: bool
    created_at: Optional[datetime] = None
