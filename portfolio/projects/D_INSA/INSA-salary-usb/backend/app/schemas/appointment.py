from datetime import date, datetime

from pydantic import BaseModel


class AppointmentCreate(BaseModel):
    employee_id: int
    appt_type: str  # 신규, 전보, 승진, 직위변경, 퇴직
    appt_date: date
    new_dept_id: int | None = None
    new_rank: str | None = None
    new_position: str | None = None
    new_title: str | None = None
    description: str | None = None


class AppointmentResponse(BaseModel):
    id: int
    employee_id: int
    appt_type: str
    appt_date: date
    old_dept_id: int | None = None
    new_dept_id: int | None = None
    old_rank: str | None = None
    new_rank: str | None = None
    old_position: str | None = None
    new_position: str | None = None
    old_title: str | None = None
    new_title: str | None = None
    description: str | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class AppointmentListItem(BaseModel):
    id: int
    employee_id: int
    emp_no: str | None = None
    emp_name: str | None = None
    appt_type: str
    appt_date: date
    old_dept_name: str | None = None
    new_dept_name: str | None = None
    old_rank: str | None = None
    new_rank: str | None = None
    old_position: str | None = None
    new_position: str | None = None
    description: str | None = None
    created_at: datetime | None = None
