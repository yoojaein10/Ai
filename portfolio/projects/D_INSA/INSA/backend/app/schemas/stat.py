from typing import Optional

from pydantic import BaseModel


# ── Workforce ─────────────────────────────────────────────


class WorkforceDeptRow(BaseModel):
    dept_id: Optional[int] = None
    dept_name: str
    count: int
    male: int
    female: int


class WorkforceRankRow(BaseModel):
    rank: str
    count: int


class WorkforceAgeGroupRow(BaseModel):
    group: str
    count: int


class WorkforceTenureRow(BaseModel):
    group: str
    count: int


class WorkforceTrendRow(BaseModel):
    year: int
    month: int
    hired: int
    resigned: int


class WorkforceStatResponse(BaseModel):
    total: int
    male: int
    female: int
    unknown_gender: int
    by_dept: list[WorkforceDeptRow]
    by_rank: list[WorkforceRankRow]
    by_age_group: list[WorkforceAgeGroupRow]
    by_tenure: list[WorkforceTenureRow]
    trend_12m: list[WorkforceTrendRow]


# ── Attendance ────────────────────────────────────────────


class AttendanceStatMonthRow(BaseModel):
    month: int
    total_work_days: int
    avg_work_hours: float
    total_leave_days: float
    emp_count: int


class AttendanceStatDeptRow(BaseModel):
    dept_name: str
    emp_count: int
    total_leave_days: float
    avg_leave_per_emp: float


class AttendanceStatTopRow(BaseModel):
    emp_no: Optional[str] = None
    name: str
    dept_name: Optional[str] = None
    value: float


class AttendanceStatResponse(BaseModel):
    year: int
    by_month: list[AttendanceStatMonthRow]
    by_dept: list[AttendanceStatDeptRow]
    top_work_hours: list[AttendanceStatTopRow]
    top_leave_users: list[AttendanceStatTopRow]


# ── Education ─────────────────────────────────────────────


class EducationStatCategoryRow(BaseModel):
    category: str
    count: int
    total_hours: float
    completed: int


class EducationStatDeptRow(BaseModel):
    dept_name: str
    emp_count: int
    record_count: int
    total_hours: float
    avg_hours_per_emp: float


class EducationStatMonthRow(BaseModel):
    month: int
    count: int


class EducationStatIncompleteRow(BaseModel):
    emp_no: str
    name: str
    dept_name: Optional[str] = None
    total_hours: float


class EducationStatResponse(BaseModel):
    year: int
    total_records: int
    total_hours: float
    completed: int
    completion_rate: float
    by_category: list[EducationStatCategoryRow]
    by_dept: list[EducationStatDeptRow]
    by_month: list[EducationStatMonthRow]
    incomplete_employees: list[EducationStatIncompleteRow]
