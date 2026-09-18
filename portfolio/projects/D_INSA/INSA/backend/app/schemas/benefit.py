from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict


# ── Item ──────────────────────────────────────────────────


class BenefitItemBase(BaseModel):
    code: str
    name: str
    category: str
    event_type: Optional[str] = None
    default_amount: Optional[Decimal] = None
    default_leave_days: Optional[Decimal] = None
    description: Optional[str] = None
    is_active: bool = True


class BenefitItemCreate(BenefitItemBase):
    pass


class BenefitItemUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    category: Optional[str] = None
    event_type: Optional[str] = None
    default_amount: Optional[Decimal] = None
    default_leave_days: Optional[Decimal] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class BenefitItemOut(BenefitItemBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class BenefitItemListResponse(BaseModel):
    total: int
    items: list[BenefitItemOut]


# ── Event (경조사) ────────────────────────────────────────


class BenefitEventBase(BaseModel):
    employee_id: int
    item_id: Optional[int] = None
    event_type: str
    target_person: Optional[str] = None
    event_date: date
    amount: Optional[Decimal] = None
    leave_days: Optional[Decimal] = None
    remark: Optional[str] = None


class BenefitEventCreate(BenefitEventBase):
    pass


class BenefitEventUpdate(BaseModel):
    item_id: Optional[int] = None
    event_type: Optional[str] = None
    target_person: Optional[str] = None
    event_date: Optional[date] = None
    amount: Optional[Decimal] = None
    leave_days: Optional[Decimal] = None
    remark: Optional[str] = None


class LinkedSchedule(BaseModel):
    schedule_date: date
    gubun: str
    bigo: Optional[str] = None


class BenefitEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    employee_id: int
    emp_no: Optional[str] = None
    emp_name: Optional[str] = None
    dept_name: Optional[str] = None
    item_id: Optional[int] = None
    item_code: Optional[str] = None
    item_name: Optional[str] = None
    event_type: str
    target_person: Optional[str] = None
    event_date: date
    amount: Optional[Decimal] = None
    leave_days: Optional[Decimal] = None
    remark: Optional[str] = None
    linked_schedules: list[LinkedSchedule] = []


class BenefitEventListResponse(BaseModel):
    total: int
    items: list[BenefitEventOut]


# ── Health (건강검진) ─────────────────────────────────────


class BenefitHealthBase(BaseModel):
    employee_id: int
    check_year: int
    check_date: Optional[date] = None
    provider: Optional[str] = None
    check_type: Optional[str] = None
    result: Optional[str] = None
    recheck_required: bool = False
    recheck_date: Optional[date] = None
    remark: Optional[str] = None


class BenefitHealthCreate(BenefitHealthBase):
    pass


class BenefitHealthUpdate(BaseModel):
    check_year: Optional[int] = None
    check_date: Optional[date] = None
    provider: Optional[str] = None
    check_type: Optional[str] = None
    result: Optional[str] = None
    recheck_required: Optional[bool] = None
    recheck_date: Optional[date] = None
    remark: Optional[str] = None


class BenefitHealthOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    employee_id: int
    emp_no: Optional[str] = None
    emp_name: Optional[str] = None
    dept_name: Optional[str] = None
    check_year: int
    check_date: Optional[date] = None
    provider: Optional[str] = None
    check_type: Optional[str] = None
    result: Optional[str] = None
    recheck_required: bool
    recheck_date: Optional[date] = None
    remark: Optional[str] = None


class BenefitHealthListResponse(BaseModel):
    total: int
    items: list[BenefitHealthOut]


# ── Overview (대시보드) ───────────────────────────────────


class CategorySummary(BaseModel):
    category: str
    count: int
    total_amount: Decimal
    total_leave_days: Decimal


class MonthlySummary(BaseModel):
    month: int  # 1-12
    count: int
    total_amount: Decimal


class HealthSummary(BaseModel):
    total: int
    normal: int
    caution: int
    abnormal: int
    recheck_required: int


class BenefitOverviewResponse(BaseModel):
    year: int
    event_total_count: int
    event_total_amount: Decimal
    event_total_leave_days: Decimal
    by_category: list[CategorySummary]
    by_month: list[MonthlySummary]
    health: HealthSummary


# ── Upload Result ─────────────────────────────────────────


class UploadResult(BaseModel):
    created: int
    skipped: int
    errors: list[str]
