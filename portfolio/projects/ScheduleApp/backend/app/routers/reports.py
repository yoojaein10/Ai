"""
reports.py — 출장 일간 현황 + 배정현황 API 라우터
"""
import logging
from fastapi import APIRouter, Depends, Query
from typing import Optional
from pydantic import BaseModel, Field, model_validator
from app.database import get_db, get_cursor_ctx
from app.schemas import ApiResponse
from app.services.report_service import get_daily_list
from app.services.assignment_service import get_assignment_employees, get_assignment_data, save_assignment_schedule, delete_assignment_schedule

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"])


_DATE_RE = r"^\d{4}-\d{2}-\d{2}$"

class AssignmentScheduleRequest(BaseModel):
    apwid: int
    gubun: str
    date:       Optional[str] = Field(None, pattern=_DATE_RE)   # 단일 날짜 (하위 호환)
    start_date: Optional[str] = Field(None, pattern=_DATE_RE)   # 기간 시작
    end_date:   Optional[str] = Field(None, pattern=_DATE_RE)   # 기간 종료

    @model_validator(mode="after")
    def _check_dates(self) -> "AssignmentScheduleRequest":
        has_range  = self.start_date and self.end_date
        has_single = bool(self.date)
        if not has_range and not has_single:
            raise ValueError("date 또는 start_date/end_date 중 하나는 필요합니다.")
        return self


@router.get("/daily-list", response_model=ApiResponse)
def daily_list(
    year:  int = Query(..., ge=2020, le=2100, description="조회 연도"),
    month: int = Query(..., ge=1,    le=12,   description="조회 월"),
    cursor=Depends(get_db),
):
    data = get_daily_list(cursor, year=year, month=month)
    return ApiResponse(data=data)


@router.get("/assignment-employees", response_model=ApiResponse)
def assignment_employees(cursor=Depends(get_db)):
    """평가사 목록 + 입사일 (배정현황 페이지용)"""
    data = get_assignment_employees(cursor)
    return ApiResponse(data=data)


@router.get("/assignment-data", response_model=ApiResponse)
def assignment_data(
    year:  int = Query(..., ge=2020, le=2100),
    month: int = Query(..., ge=1,    le=12),
    cursor=Depends(get_db),
):
    """월별 배정 현황 데이터"""
    data = get_assignment_data(cursor, year=year, month=month)
    return ApiResponse(data=data)


class AssignmentScheduleDeleteRequest(BaseModel):
    apwid: int
    date:  str = Field(..., pattern=_DATE_RE)


@router.post("/assignment-schedule", response_model=ApiResponse)
def upsert_assignment_schedule(body: AssignmentScheduleRequest):
    """APW_IW_SCHEDULE UPSERT — 단일 날짜 또는 기간"""
    if body.start_date and body.end_date:
        start, end = body.start_date, body.end_date
    else:
        start = end = body.date  # type: ignore[assignment]
    with get_cursor_ctx() as cursor:
        result = save_assignment_schedule(cursor, body.apwid, start, end, body.gubun)
    return ApiResponse(data=result, message="저장되었습니다.")


@router.delete("/assignment-schedule", response_model=ApiResponse)
def remove_assignment_schedule(body: AssignmentScheduleDeleteRequest):
    """APW_IW_SCHEDULE 단일 행 삭제 — name + date 기준"""
    with get_cursor_ctx() as cursor:
        result = delete_assignment_schedule(cursor, body.apwid, body.date)
    return ApiResponse(data=result, message="삭제되었습니다.")
