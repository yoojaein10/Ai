"""Leave request schemas (PHASE 15)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

HalfType = Literal["AM", "PM"]


class CalculateDaysRequest(BaseModel):
    leave_type_id: int
    start_date: date
    end_date: date
    half_type: Optional[HalfType] = None


class CalculateDaysResponse(BaseModel):
    days: Decimal
    business_days: int
    excluded_holidays: list[date]
    unit: str  # DAY | HALF_DAY | HOUR


class LeaveRequestCreate(BaseModel):
    leave_type_id: int
    line_template_id: int
    title: Optional[str] = Field(default=None, max_length=200)
    start_date: date
    end_date: date
    half_type: Optional[HalfType] = None
    reason: Optional[str] = Field(default=None, max_length=500)
    delegate_emp_id: Optional[int] = None
    contact_during_leave: Optional[str] = Field(default=None, max_length=50)
    evidence_file_url: Optional[str] = Field(default=None, max_length=500)


class LeaveRequestDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    doc_id: int
    leave_type_id: int
    start_date: date
    end_date: date
    half_type: Optional[str] = None
    days: Decimal
    reason: Optional[str] = None
    delegate_emp_id: Optional[int] = None
    contact_during_leave: Optional[str] = None
    evidence_file_url: Optional[str] = None
    created_at: Optional[datetime] = None


class LeaveRequestListRow(BaseModel):
    """Row for /my and /team endpoints — flattened doc + detail."""
    model_config = ConfigDict(from_attributes=True)

    doc_id: int
    doc_no: Optional[str] = None
    title: str
    status: str
    drafter_id: int
    drafter_name: Optional[str] = None
    drafter_emp_no: Optional[str] = None
    dept_name: Optional[str] = None
    leave_type_id: int
    leave_type_name: Optional[str] = None
    start_date: date
    end_date: date
    half_type: Optional[str] = None
    days: Decimal
    reason: Optional[str] = None
    drafted_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
