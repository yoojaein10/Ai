from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_roles
from app.db.models import User
from app.db.session import get_db
from app.schemas.appointment import AppointmentCreate, AppointmentListItem, AppointmentResponse
from app.services.appointment import (
    create_appointment,
    get_all_appointments,
    get_appointments_by_employee,
)

router = APIRouter(prefix="/appointments", tags=["appointments"])


@router.get("", response_model=list[AppointmentListItem])
def list_all_appointments(
    appt_type: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    search: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return get_all_appointments(db, appt_type=appt_type, date_from=date_from, date_to=date_to, search=search)


@router.get("/employee/{employee_id}", response_model=list[AppointmentResponse])
def list_appointments(
    employee_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return get_appointments_by_employee(db, employee_id)


@router.post("", response_model=AppointmentResponse, status_code=status.HTTP_201_CREATED)
def create_new_appointment(
    body: AppointmentCreate,
    current_user: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    try:
        appointment = create_appointment(db, body, created_by=current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    return appointment
