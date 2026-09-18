"""API routes for travel orders and reports (PHASE 16).

Prefixes:
- `/travel/orders` — 출장명령부
- `/travel/orders/{id}/report` — 복명서 (1:1 with order)
- `/travel/orders/by-case/{case_no}` — 감정평가 건번호 조회
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.models import Employee, User
from app.db.session import get_db
from app.schemas.travel_order import (
    TravelOrderCreate,
    TravelOrderDetailResponse,
    TravelOrderListRow,
    TravelReportCreate,
    TravelReportResponse,
)
from app.services import travel_order_service as order_svc
from app.services import travel_report_service as report_svc

router = APIRouter(prefix="/travel", tags=["travel"])


def _map_order_error(exc: Exception) -> HTTPException:
    if isinstance(exc, order_svc.TravelOrderNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, order_svc.TravelOrderInvalid):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail="internal error")


def _map_report_error(exc: Exception) -> HTTPException:
    if isinstance(exc, report_svc.TravelReportNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, report_svc.TravelReportInvalid):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail="internal error")


# ── Travel orders ─────────────────────────────────────────


@router.post("/orders", status_code=status.HTTP_201_CREATED)
def create_order_route(
    body: TravelOrderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        doc, detail = order_svc.create_draft(
            db,
            user=current_user,
            line_template_id=body.line_template_id,
            title=body.title,
            travel_type=body.travel_type,
            purpose=body.purpose,
            destination=body.destination,
            client_company=body.client_company,
            start_at=body.start_at,
            end_at=body.end_at,
            transportation=body.transportation,
            estimated_cost=body.estimated_cost,
            project_code=body.project_code,
            appraisal_case_no=body.appraisal_case_no,
            remarks=body.remarks,
            companion_emp_ids=body.companion_emp_ids,
        )
        return {"doc_id": doc.id, "detail_id": detail.id, "status": doc.status}
    except order_svc.TravelOrderError as exc:
        raise _map_order_error(exc)


@router.post("/orders/{doc_id}/submit")
def submit_order_route(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        doc = order_svc.submit(db, doc_id, current_user)
        return {"doc_id": doc.id, "status": doc.status}
    except order_svc.TravelOrderError as exc:
        raise _map_order_error(exc)


@router.post("/orders/{doc_id}/cancel")
def cancel_order_route(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        doc = order_svc.cancel(db, doc_id, current_user)
        return {"doc_id": doc.id, "status": doc.status}
    except order_svc.TravelOrderError as exc:
        raise _map_order_error(exc)


@router.get("/orders/my", response_model=list[TravelOrderListRow])
def list_my_orders_route(
    status_filter: Optional[str] = Query(None, alias="status"),
    include_companion: bool = Query(True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return order_svc.list_my(
            db,
            user=current_user,
            status=status_filter,
            include_companion=include_companion,
        )
    except order_svc.TravelOrderError as exc:
        raise _map_order_error(exc)


@router.get("/orders/team", response_model=list[TravelOrderListRow])
def list_team_orders_route(
    status_filter: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    roles = {ur.role.code for ur in current_user.roles}
    is_hr = bool(roles.intersection({"SYSTEM_ADMIN", "HR_ADMIN"}))

    if is_hr:
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
                order_svc.list_team(db, dept_id=did, status=status_filter)
            )
        return rows

    if current_user.employee_id is None:
        raise HTTPException(status_code=403, detail="직원 정보가 없는 사용자입니다")
    emp = db.get(Employee, current_user.employee_id)
    if emp is None or emp.dept_id is None:
        raise HTTPException(status_code=403, detail="부서가 없는 사용자입니다")
    return order_svc.list_team(db, dept_id=emp.dept_id, status=status_filter)


@router.get("/orders/by-case/{case_no}", response_model=list[TravelOrderListRow])
def list_by_case_route(
    case_no: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    try:
        return order_svc.find_by_case_no(db, case_no)
    except order_svc.TravelOrderError as exc:
        raise _map_order_error(exc)


@router.get("/orders/{doc_id}", response_model=TravelOrderDetailResponse)
def get_order_detail_route(
    doc_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    try:
        return order_svc.get_detail(db, doc_id)
    except order_svc.TravelOrderError as exc:
        raise _map_order_error(exc)


# ── Travel reports (복명서) ───────────────────────────────


@router.post(
    "/orders/{doc_id}/report", status_code=status.HTTP_201_CREATED
)
def create_report_route(
    doc_id: int,
    body: TravelReportCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        report_doc, report = report_svc.create_draft(
            db,
            user=current_user,
            travel_order_doc_id=doc_id,
            line_template_id=body.line_template_id,
            title=body.title,
            report_content=body.report_content,
            actual_cost=body.actual_cost,
            receipts_url=body.receipts_url,
        )
        return {
            "report_doc_id": report_doc.id,
            "report_id": report.id,
            "status": report_doc.status,
        }
    except report_svc.TravelReportError as exc:
        raise _map_report_error(exc)


@router.post("/reports/{doc_id}/submit")
def submit_report_route(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        doc = report_svc.submit(db, doc_id, current_user)
        return {"doc_id": doc.id, "status": doc.status}
    except report_svc.TravelReportError as exc:
        raise _map_report_error(exc)


@router.post("/reports/{doc_id}/cancel")
def cancel_report_route(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        doc = report_svc.cancel(db, doc_id, current_user)
        return {"doc_id": doc.id, "status": doc.status}
    except report_svc.TravelReportError as exc:
        raise _map_report_error(exc)


@router.get(
    "/orders/{doc_id}/report", response_model=Optional[TravelReportResponse]
)
def get_report_route(
    doc_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    try:
        report = report_svc.get_by_travel_order(db, doc_id)
        return report
    except report_svc.TravelReportError as exc:
        raise _map_report_error(exc)
