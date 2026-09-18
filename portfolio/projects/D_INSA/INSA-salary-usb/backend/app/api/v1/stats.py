from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.models import User
from app.db.session import get_apw_db, get_att_db, get_db
from app.schemas.stat import (
    AttendanceStatResponse,
    EducationStatResponse,
    WorkforceStatResponse,
)
from app.services import stat as svc

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/workforce", response_model=WorkforceStatResponse)
def workforce_stat(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> WorkforceStatResponse:
    return svc.get_workforce(db)


@router.get("/attendance", response_model=AttendanceStatResponse)
def attendance_stat(
    year: int = Query(..., ge=2000, le=2100),
    db: Session = Depends(get_db),
    att_db: Session = Depends(get_att_db),
    apw_db: Session = Depends(get_apw_db),
    _: User = Depends(get_current_user),
) -> AttendanceStatResponse:
    return svc.get_attendance(att_db, apw_db, db, year)


@router.get("/education", response_model=EducationStatResponse)
def education_stat(
    year: int = Query(..., ge=2000, le=2100),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> EducationStatResponse:
    return svc.get_education(db, year)
