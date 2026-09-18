"""API routes for leave requests (PHASE 15).

Prefix: `/leave-request`. Separate from `/leave` (PHASE 14 balances & rules).
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.models import Employee, User
from app.db.session import get_db
from app.schemas.leave_request import (
    CalculateDaysRequest,
    CalculateDaysResponse,
    LeaveRequestCreate,
    LeaveRequestListRow,
)
from app.services import leave_request_service as svc

router = APIRouter(prefix="/leave-request", tags=["leave-request"])


def _map_error(exc: Exception) -> HTTPException:
    if isinstance(exc, svc.LeaveRequestNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, svc.InsufficientLeaveBalance):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, svc.LeaveRequestInvalid):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail="internal error")


# ── Preview ────────────────────────────────────────────────


@router.post("/calculate-days", response_model=CalculateDaysResponse)
def calculate_days_route(
    body: CalculateDaysRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    try:
        lt = svc._leave_type(db, body.leave_type_id)
        result = svc.calculate_days(
            db,
            leave_type=lt,
            start_date=body.start_date,
            end_date=body.end_date,
            half_type=body.half_type,
        )
        return result
    except svc.LeaveRequestError as exc:
        raise _map_error(exc)


# ── Draft / submit / cancel ────────────────────────────────


@router.post("", status_code=status.HTTP_201_CREATED)
def create_draft_route(
    body: LeaveRequestCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        doc, detail = svc.create_draft(
            db,
            user=current_user,
            leave_type_id=body.leave_type_id,
            line_template_id=body.line_template_id,
            start_date=body.start_date,
            end_date=body.end_date,
            half_type=body.half_type,
            title=body.title,
            reason=body.reason,
            delegate_emp_id=body.delegate_emp_id,
            contact_during_leave=body.contact_during_leave,
            evidence_file_url=body.evidence_file_url,
        )
        return {"doc_id": doc.id, "detail_id": detail.id, "status": doc.status}
    except svc.LeaveRequestError as exc:
        raise _map_error(exc)


@router.post("/{doc_id}/submit")
def submit_route(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        doc = svc.submit(db, doc_id, current_user)
        return {"doc_id": doc.id, "status": doc.status}
    except svc.LeaveRequestError as exc:
        raise _map_error(exc)


@router.post("/{doc_id}/cancel")
def cancel_route(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        doc = svc.cancel(db, doc_id, current_user)
        return {"doc_id": doc.id, "status": doc.status}
    except svc.LeaveRequestError as exc:
        raise _map_error(exc)


# ── Lists ──────────────────────────────────────────────────


@router.get("/my", response_model=list[LeaveRequestListRow])
def list_my_route(
    year: Optional[int] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return svc.list_my(db, user=current_user, year=year, status=status_filter)
    except svc.LeaveRequestError as exc:
        raise _map_error(exc)


@router.get("/team", response_model=list[LeaveRequestListRow])
def list_team_route(
    year: Optional[int] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Team view for dept heads: requests from their department.

    HR_ADMIN / SYSTEM_ADMIN see every department; everyone else sees only
    their own dept (the one the drafter's Employee is in).
    """
    roles = {ur.role.code for ur in current_user.roles}
    is_hr = bool(roles.intersection({"SYSTEM_ADMIN", "HR_ADMIN"}))

    if is_hr:
        # HR sees all — iterate dept-wise is overkill; reuse list_my per-dept
        # keeps the contract simple: pass None (interpreted as no filter).
        dept_id = None
    else:
        if current_user.employee_id is None:
            raise HTTPException(
                status_code=403, detail="직원 정보가 없는 사용자입니다"
            )
        emp = db.get(Employee, current_user.employee_id)
        if emp is None or emp.dept_id is None:
            raise HTTPException(
                status_code=403, detail="부서가 없는 사용자입니다"
            )
        dept_id = emp.dept_id

    if dept_id is None:
        # HR: aggregate across all depts
        from sqlalchemy import distinct

        dept_ids = [
            row[0]
            for row in db.query(distinct(Employee.dept_id))
            .filter(Employee.dept_id.isnot(None))
            .all()
        ]
        rows: list[dict] = []
        for did in dept_ids:
            rows.extend(
                svc.list_team(db, dept_id=did, year=year, status=status_filter)
            )
        return rows

    return svc.list_team(db, dept_id=dept_id, year=year, status=status_filter)
