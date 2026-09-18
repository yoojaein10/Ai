from datetime import date
from typing import Optional

from pydantic import BaseModel


class AttendanceDailyRow(BaseModel):
    emp_no: str
    name: str
    dept_name: Optional[str] = None
    matched: bool
    check_in: Optional[str] = None
    check_out: Optional[str] = None
    work_minutes: Optional[int] = None
    tag_count: int


class AttendanceDailyResponse(BaseModel):
    work_date: date
    total: int
    matched_count: int
    rows: list[AttendanceDailyRow]


class AttendanceSummaryRow(BaseModel):
    emp_no: str
    name: str
    dept_name: Optional[str] = None
    matched: bool
    work_days: int
    work_hours: float
    leave_days: float
    gong_days: float
    trip_days: int


class AttendanceSummaryResponse(BaseModel):
    year: int
    month: int
    total: int
    matched_count: int
    rows: list[AttendanceSummaryRow]


class AttendanceDetailDay(BaseModel):
    work_date: date
    weekday: str
    is_weekend: bool
    check_in: Optional[str] = None
    check_out: Optional[str] = None
    work_minutes: Optional[int] = None
    tag_count: int
    leave_type: Optional[str] = None
    leave_half: bool = False
    leave_remark: Optional[str] = None
    trip: bool = False
    trip_places: list[str] = []


class AttendanceDetailResponse(BaseModel):
    emp_no: str
    name: str
    dept_name: Optional[str] = None
    year: int
    month: int
    work_days: int
    work_hours: float
    leave_days: float
    gong_days: float
    trip_days: int
    days: list[AttendanceDetailDay]
