"""API routes for holiday management (PHASE 15)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_roles
from app.db.models import User
from app.db.session import get_db
from app.schemas.holiday import HolidayCreate, HolidayResponse
from app.services import holiday_service as svc

router = APIRouter(prefix="/holiday", tags=["holiday"])

HR_ROLES = ("SYSTEM_ADMIN", "HR_ADMIN")


@router.get("", response_model=list[HolidayResponse])
def list_holidays(
    year: Optional[int] = Query(None, ge=2000, le=2100),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    return svc.list_holidays(db, year=year)


@router.post(
    "", response_model=HolidayResponse, status_code=status.HTTP_201_CREATED
)
def create_holiday(
    body: HolidayCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(*HR_ROLES)),
):
    try:
        return svc.create_holiday(
            db, on=body.date, name=body.name, is_recurring=body.is_recurring
        )
    except svc.HolidayDuplicate as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.delete("/{holiday_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_holiday(
    holiday_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(*HR_ROLES)),
):
    try:
        svc.delete_holiday(db, holiday_id)
    except svc.HolidayNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
