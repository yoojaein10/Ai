"""API routes for change request workflow."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_roles
from app.db.models import ChangeRequest, Employee, User
from app.db.session import get_db
from app.schemas.change_request import (
    ChangeRequestCreate,
    ChangeRequestResponse,
    ChangeRequestReview,
)
from app.services.change_request import (
    FIELD_LABELS,
    approve,
    create_change_request,
    list_all,
    list_mine,
    reject,
)

router = APIRouter(prefix="/change-requests", tags=["change-requests"])


def _to_response(db: Session, req: ChangeRequest) -> ChangeRequestResponse:
    emp = db.query(Employee).filter(Employee.id == req.employee_id).first()
    return ChangeRequestResponse(
        id=req.id,
        employee_id=req.employee_id,
        emp_name=emp.name_ko if emp else None,
        emp_no=emp.emp_no if emp else None,
        field_name=req.field_name,
        field_label=FIELD_LABELS.get(req.field_name),
        old_value=req.old_value,
        new_value=req.new_value,
        reason=req.reason,
        status=req.status,
        requested_by=req.requested_by,
        requested_at=req.requested_at,
        reviewed_by=req.reviewed_by,
        reviewed_at=req.reviewed_at,
        review_comment=req.review_comment,
    )


@router.post("", response_model=ChangeRequestResponse, status_code=status.HTTP_201_CREATED)
def create_request(
    body: ChangeRequestCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        req = create_change_request(db, current_user, body)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return _to_response(db, req)


@router.get("/mine", response_model=list[ChangeRequestResponse])
def my_requests(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return [_to_response(db, r) for r in list_mine(db, current_user)]


@router.get("", response_model=list[ChangeRequestResponse])
def all_requests(
    status_filter: str | None = None,
    _: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    return [_to_response(db, r) for r in list_all(db, status_filter)]


@router.post("/{req_id}/approve", response_model=ChangeRequestResponse)
def approve_request(
    req_id: int,
    body: ChangeRequestReview,
    current_user: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    try:
        req = approve(db, req_id, current_user, body.comment)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return _to_response(db, req)


@router.post("/{req_id}/reject", response_model=ChangeRequestResponse)
def reject_request(
    req_id: int,
    body: ChangeRequestReview,
    current_user: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    try:
        req = reject(db, req_id, current_user, body.comment)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return _to_response(db, req)
