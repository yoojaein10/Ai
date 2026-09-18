"""Travel order / report schemas (PHASE 16)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

TravelType = Literal["DOMESTIC", "OVERSEAS"]


class TravelOrderCreate(BaseModel):
    line_template_id: int
    title: Optional[str] = Field(default=None, max_length=200)
    travel_type: TravelType = "DOMESTIC"
    purpose: str = Field(..., max_length=500)
    destination: str = Field(..., max_length=200)
    client_company: Optional[str] = Field(default=None, max_length=200)
    start_at: datetime
    end_at: datetime
    transportation: Optional[str] = Field(default=None, max_length=100)
    estimated_cost: Optional[Decimal] = None
    project_code: Optional[str] = Field(default=None, max_length=50)
    appraisal_case_no: Optional[str] = Field(default=None, max_length=100)
    remarks: Optional[str] = Field(default=None, max_length=500)
    companion_emp_ids: list[int] = Field(default_factory=list)


class CompanionInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    emp_id: int
    emp_no: Optional[str] = None
    name_ko: Optional[str] = None
    dept_name: Optional[str] = None


class TravelOrderDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    doc_id: int
    travel_type: str
    purpose: str
    destination: str
    client_company: Optional[str] = None
    start_at: datetime
    end_at: datetime
    transportation: Optional[str] = None
    estimated_cost: Optional[Decimal] = None
    project_code: Optional[str] = None
    appraisal_case_no: Optional[str] = None
    remarks: Optional[str] = None
    created_at: Optional[datetime] = None
    companions: list[CompanionInfo] = Field(default_factory=list)


class TravelOrderListRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    doc_id: int
    doc_no: Optional[str] = None
    title: str
    status: str
    drafter_id: int
    drafter_name: Optional[str] = None
    drafter_emp_no: Optional[str] = None
    dept_name: Optional[str] = None
    travel_type: str
    destination: str
    purpose: str
    start_at: datetime
    end_at: datetime
    appraisal_case_no: Optional[str] = None
    estimated_cost: Optional[Decimal] = None
    companion_count: int = 0
    drafted_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    has_report: bool = False


# ── Travel report (복명서) ────────────────────────────────


class TravelReportCreate(BaseModel):
    line_template_id: int
    title: Optional[str] = Field(default=None, max_length=200)
    report_content: str = Field(..., min_length=1)
    actual_cost: Optional[Decimal] = None
    receipts_url: Optional[str] = Field(default=None, max_length=500)


class TravelReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    travel_id: int
    doc_id: Optional[int] = None
    report_content: str
    actual_cost: Optional[Decimal] = None
    receipts_url: Optional[str] = None
    reported_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
