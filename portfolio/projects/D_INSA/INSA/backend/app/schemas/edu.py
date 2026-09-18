from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict


class EduCourseBase(BaseModel):
    course_code: str
    course_name: str
    category: Optional[str] = None
    training_type: Optional[str] = None
    hours: Optional[Decimal] = None
    provider: Optional[str] = None
    instructor: Optional[str] = None
    description: Optional[str] = None
    is_active: bool = True


class EduCourseCreate(EduCourseBase):
    pass


class EduCourseUpdate(BaseModel):
    course_code: Optional[str] = None
    course_name: Optional[str] = None
    category: Optional[str] = None
    training_type: Optional[str] = None
    hours: Optional[Decimal] = None
    provider: Optional[str] = None
    instructor: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class EduCourseOut(EduCourseBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class EduCourseListResponse(BaseModel):
    total: int
    items: list[EduCourseOut]


class EduRecordBase(BaseModel):
    employee_id: int
    course_id: Optional[int] = None
    course_name_snapshot: str
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    hours: Optional[Decimal] = None
    score: Optional[Decimal] = None
    result: Optional[str] = None
    certificate_no: Optional[str] = None
    remark: Optional[str] = None


class EduRecordCreate(EduRecordBase):
    pass


class EduRecordUpdate(BaseModel):
    course_id: Optional[int] = None
    course_name_snapshot: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    hours: Optional[Decimal] = None
    score: Optional[Decimal] = None
    result: Optional[str] = None
    certificate_no: Optional[str] = None
    remark: Optional[str] = None


class EduRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    employee_id: int
    emp_no: Optional[str] = None
    emp_name: Optional[str] = None
    dept_name: Optional[str] = None
    course_id: Optional[int] = None
    course_code: Optional[str] = None
    course_name_snapshot: str
    category: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    hours: Optional[Decimal] = None
    score: Optional[Decimal] = None
    result: Optional[str] = None
    certificate_no: Optional[str] = None
    remark: Optional[str] = None


class EduRecordListResponse(BaseModel):
    total: int
    items: list[EduRecordOut]


class EduRecordUploadResult(BaseModel):
    created: int
    skipped: int
    errors: list[str]
