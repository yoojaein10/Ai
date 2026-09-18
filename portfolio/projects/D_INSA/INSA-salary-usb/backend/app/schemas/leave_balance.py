from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class LeaveBalanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    emp_id: int
    year: int
    initial_days: Decimal
    carried_over_days: Decimal
    additional_days: Decimal
    used_days: Decimal
    scheduled_days: Decimal
    carry_over_exempt: bool
    updated_at: Optional[datetime] = None


class LeaveBalanceWithEmployee(LeaveBalanceResponse):
    emp_no: Optional[str] = None
    emp_name: Optional[str] = None
    dept_name: Optional[str] = None
    hire_date: Optional[str] = None
    remaining: Decimal = Decimal("0")


class LeaveAdjustRequest(BaseModel):
    emp_id: int
    amount: Decimal = Field(..., description="양수=부여, 음수=차감")
    reason: str = Field(..., max_length=200)


class CarryOverExemptRequest(BaseModel):
    emp_id: int
    year: int
    exempt: bool
