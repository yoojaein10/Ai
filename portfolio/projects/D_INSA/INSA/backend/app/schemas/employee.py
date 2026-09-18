from datetime import date, datetime

from pydantic import BaseModel


class EmployeeBase(BaseModel):
    emp_no: str
    name_ko: str
    name_cn: str | None = None
    name_en: str | None = None
    gender: str | None = None
    birth_date: date | None = None
    hire_date: date
    hire_type: str | None = None
    workplace: str | None = None
    work_location: str | None = None
    dept_id: int | None = None
    job_rank: str | None = None
    job_position: str | None = None
    job_title: str | None = None
    emp_status: str = "재직"
    emp_type: str = "정규직"
    resign_date: date | None = None


class EmployeeCreate(EmployeeBase):
    pass


class EmployeeUpdate(BaseModel):
    name_ko: str | None = None
    name_cn: str | None = None
    name_en: str | None = None
    gender: str | None = None
    birth_date: date | None = None
    hire_type: str | None = None
    workplace: str | None = None
    work_location: str | None = None
    job_title: str | None = None
    emp_type: str | None = None


class EmployeeResponse(EmployeeBase):
    id: int
    department_name: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class EmployeeListResponse(BaseModel):
    items: list[EmployeeResponse]
    total: int
    page: int
    page_size: int
