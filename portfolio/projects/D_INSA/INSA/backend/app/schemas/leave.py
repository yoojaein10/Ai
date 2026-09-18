from datetime import date
from typing import Optional

from pydantic import BaseModel


class LeaveRow(BaseModel):
    emp_no: Optional[str] = None
    name: str
    dept_name: Optional[str] = None
    matched: bool
    leave_date: date
    weekday: str
    leave_type: str
    half: bool
    remark: Optional[str] = None


class LeaveSummary(BaseModel):
    annual: float  # 연차 (종일만)
    half: int  # 반차 건수
    gong: float  # 공가
    special: float  # 특가(경조 제외)
    bereavement: float  # 경조휴가
    family_care: float  # 가족돌봄
    etc: float  # 나머지 휴가성


class LeaveListResponse(BaseModel):
    year: int
    month: int
    total: int
    summary: LeaveSummary
    rows: list[LeaveRow]
