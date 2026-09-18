from datetime import date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.models import User
from app.db.session import get_apw_db, get_att_db, get_db
from app.schemas.attendance import (
    AttendanceDailyResponse,
    AttendanceDetailResponse,
    AttendanceSummaryResponse,
)
from app.services.attendance import (
    get_daily_attendance,
    get_monthly_summary,
    get_personal_detail,
)
from app.services.attendance_export import (
    build_history_xlsx,
    build_summary_xlsx,
)

router = APIRouter(prefix="/attendance", tags=["attendance"])


@router.get("/daily", response_model=AttendanceDailyResponse)
def daily_attendance(
    work_date: date = Query(..., alias="date"),
    att_db: Session = Depends(get_att_db),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> AttendanceDailyResponse:
    return get_daily_attendance(att_db, db, work_date)


@router.get("/summary", response_model=AttendanceSummaryResponse)
def monthly_summary(
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    att_db: Session = Depends(get_att_db),
    apw_db: Session = Depends(get_apw_db),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> AttendanceSummaryResponse:
    return get_monthly_summary(att_db, apw_db, db, year, month)


@router.get("/detail", response_model=AttendanceDetailResponse)
def personal_detail(
    emp_no: str = Query(..., min_length=1),
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    att_db: Session = Depends(get_att_db),
    apw_db: Session = Depends(get_apw_db),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> AttendanceDetailResponse:
    return get_personal_detail(att_db, apw_db, db, emp_no, year, month)


_XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/export/summary")
def export_summary_xlsx(
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    att_db: Session = Depends(get_att_db),
    apw_db: Session = Depends(get_apw_db),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Response:
    data = build_summary_xlsx(att_db, apw_db, db, year, month)
    filename = f"attendance_summary_{year}{month:02d}.xlsx"
    return Response(
        content=data,
        media_type=_XLSX_MEDIA,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/history")
def export_history_xlsx(
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    att_db: Session = Depends(get_att_db),
    apw_db: Session = Depends(get_apw_db),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Response:
    data = build_history_xlsx(att_db, apw_db, db, year, month)
    filename = f"attendance_history_{year}{month:02d}.xlsx"
    return Response(
        content=data,
        media_type=_XLSX_MEDIA,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
