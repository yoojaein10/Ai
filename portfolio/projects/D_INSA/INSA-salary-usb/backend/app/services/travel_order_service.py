"""Travel order service (PHASE 16).

Wraps approval workflow for TRAVEL_ORDER documents:
- create_draft: wraps approval_service.create_draft + writes detail + companions
- submit: wraps approval_service.submit_doc
- cancel: delete DRAFT, recall PENDING/IN_PROGRESS
- list_my / list_team / get_detail: read side
- find_by_case_no: lookup by 감정평가 건번호

No leave balance coupling — travel is treated as work extension.
Calendar events are created by the approval hook (travel_hook.on_approved).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.db.models import (
    ApprovalDoc,
    ApprovalDocType,
    Department,
    Employee,
    TravelCompanion,
    TravelOrderDetail,
    TravelReport,
    User,
)
from app.services import approval_service as approval_svc


TRAVEL_ORDER_DOC_TYPE = "TRAVEL_ORDER"


# ── Errors ─────────────────────────────────────────────────


class TravelOrderError(Exception):
    pass


class TravelOrderInvalid(TravelOrderError):
    pass


class TravelOrderNotFound(TravelOrderError):
    pass


# ── Helpers ────────────────────────────────────────────────


def _owner_employee(db: Session, user: User) -> Employee:
    if user.employee_id is None:
        raise TravelOrderInvalid("기안자에 연결된 직원이 없습니다")
    emp = db.query(Employee).filter(Employee.id == user.employee_id).first()
    if emp is None:
        raise TravelOrderInvalid("직원을 찾을 수 없습니다")
    return emp


def _doc_type_id(db: Session) -> int:
    dt = (
        db.query(ApprovalDocType)
        .filter(ApprovalDocType.code == TRAVEL_ORDER_DOC_TYPE)
        .first()
    )
    if dt is None:
        raise TravelOrderInvalid(
            f"approval doc type {TRAVEL_ORDER_DOC_TYPE} not configured"
        )
    return dt.id


def _validate_range(start_at: datetime, end_at: datetime) -> None:
    if end_at < start_at:
        raise TravelOrderInvalid("종료일시가 시작일시보다 앞설 수 없습니다")


def _companion_rows(db: Session, travel_id: int) -> list[TravelCompanion]:
    return (
        db.query(TravelCompanion)
        .filter(TravelCompanion.travel_id == travel_id)
        .all()
    )


def _companion_emp_ids(db: Session, travel_id: int) -> list[int]:
    rows = _companion_rows(db, travel_id)
    return [r.emp_id for r in rows]


def _set_companions(
    db: Session,
    *,
    travel_id: int,
    drafter_emp_id: int,
    emp_ids: list[int],
) -> None:
    """Replace the companion set for a travel order. Drafter is excluded."""
    db.query(TravelCompanion).filter(
        TravelCompanion.travel_id == travel_id
    ).delete()
    db.flush()
    seen: set[int] = {drafter_emp_id}
    for emp_id in emp_ids:
        if emp_id in seen:
            continue
        seen.add(emp_id)
        db.add(TravelCompanion(travel_id=travel_id, emp_id=emp_id))
    db.flush()


# ── Draft / submit / cancel ────────────────────────────────


def create_draft(
    db: Session,
    *,
    user: User,
    line_template_id: int,
    title: Optional[str],
    travel_type: str,
    purpose: str,
    destination: str,
    client_company: Optional[str],
    start_at: datetime,
    end_at: datetime,
    transportation: Optional[str],
    estimated_cost: Optional[Any],
    project_code: Optional[str],
    appraisal_case_no: Optional[str],
    remarks: Optional[str],
    companion_emp_ids: list[int],
) -> tuple[ApprovalDoc, TravelOrderDetail]:
    emp = _owner_employee(db, user)
    _validate_range(start_at, end_at)

    default_title = title or (
        f"{destination} 출장 ({start_at.date()}~{end_at.date()})"
    )
    content = {
        "travel_type": travel_type,
        "purpose": purpose,
        "destination": destination,
        "client_company": client_company,
        "start_at": start_at.isoformat(),
        "end_at": end_at.isoformat(),
        "estimated_cost": str(estimated_cost) if estimated_cost is not None else None,
        "appraisal_case_no": appraisal_case_no,
        "companion_emp_ids": companion_emp_ids,
    }
    doc = approval_svc.create_draft(
        db,
        user=user,
        doc_type_id=_doc_type_id(db),
        title=default_title,
        content=content,
        line_template_id=line_template_id,
    )

    detail = TravelOrderDetail(
        doc_id=doc.id,
        travel_type=travel_type,
        purpose=purpose,
        destination=destination,
        client_company=client_company,
        start_at=start_at,
        end_at=end_at,
        transportation=transportation,
        estimated_cost=estimated_cost,
        project_code=project_code,
        appraisal_case_no=appraisal_case_no,
        remarks=remarks,
    )
    db.add(detail)
    db.flush()
    _set_companions(
        db,
        travel_id=detail.id,
        drafter_emp_id=emp.id,
        emp_ids=companion_emp_ids,
    )
    db.commit()
    db.refresh(detail)
    return doc, detail


def submit(db: Session, doc_id: int, user: User) -> ApprovalDoc:
    detail = (
        db.query(TravelOrderDetail)
        .filter(TravelOrderDetail.doc_id == doc_id)
        .first()
    )
    if detail is None:
        raise TravelOrderNotFound(f"travel order detail for doc {doc_id}")
    doc = approval_svc.submit_doc(db, doc_id, user)
    db.refresh(doc)
    return doc


def cancel(db: Session, doc_id: int, user: User) -> ApprovalDoc:
    doc = db.query(ApprovalDoc).filter(ApprovalDoc.id == doc_id).first()
    if doc is None:
        raise TravelOrderNotFound(f"doc {doc_id} not found")

    if doc.status == "DRAFT":
        detail = (
            db.query(TravelOrderDetail)
            .filter(TravelOrderDetail.doc_id == doc_id)
            .first()
        )
        if detail is not None:
            db.query(TravelCompanion).filter(
                TravelCompanion.travel_id == detail.id
            ).delete()
            db.delete(detail)
        db.delete(doc)
        db.commit()
        return doc

    if doc.status in ("PENDING", "IN_PROGRESS"):
        doc = approval_svc.recall_doc(db, doc_id, user)
        db.refresh(doc)
        return doc

    raise TravelOrderInvalid(f"{doc.status} 상태는 취소할 수 없습니다")


# ── Read ──────────────────────────────────────────────────


def _employee_compact(db: Session, emp_id: int) -> dict[str, Any]:
    emp = db.query(Employee).filter(Employee.id == emp_id).first()
    if emp is None:
        return {"emp_id": emp_id, "emp_no": None, "name_ko": None, "dept_name": None}
    dept = (
        db.query(Department).filter(Department.id == emp.dept_id).first()
        if emp.dept_id
        else None
    )
    return {
        "emp_id": emp.id,
        "emp_no": emp.emp_no,
        "name_ko": emp.name_ko,
        "dept_name": dept.name if dept else None,
    }


def get_detail(db: Session, doc_id: int) -> dict[str, Any]:
    detail = (
        db.query(TravelOrderDetail)
        .filter(TravelOrderDetail.doc_id == doc_id)
        .first()
    )
    if detail is None:
        raise TravelOrderNotFound(f"travel order detail for doc {doc_id}")
    companion_ids = _companion_emp_ids(db, detail.id)
    companions = [_employee_compact(db, emp_id) for emp_id in companion_ids]
    return {
        "id": detail.id,
        "doc_id": detail.doc_id,
        "travel_type": detail.travel_type,
        "purpose": detail.purpose,
        "destination": detail.destination,
        "client_company": detail.client_company,
        "start_at": detail.start_at,
        "end_at": detail.end_at,
        "transportation": detail.transportation,
        "estimated_cost": detail.estimated_cost,
        "project_code": detail.project_code,
        "appraisal_case_no": detail.appraisal_case_no,
        "remarks": detail.remarks,
        "created_at": detail.created_at,
        "companions": companions,
    }


def _list_row(
    db: Session, doc: ApprovalDoc, detail: TravelOrderDetail
) -> dict[str, Any]:
    drafter = db.query(Employee).filter(Employee.id == doc.drafter_id).first()
    dept = (
        db.query(Department).filter(Department.id == drafter.dept_id).first()
        if drafter and drafter.dept_id
        else None
    )
    companion_count = (
        db.query(TravelCompanion)
        .filter(TravelCompanion.travel_id == detail.id)
        .count()
    )
    has_report = (
        db.query(TravelReport)
        .filter(TravelReport.travel_id == detail.id)
        .first()
        is not None
    )
    return {
        "doc_id": doc.id,
        "doc_no": doc.doc_no,
        "title": doc.title,
        "status": doc.status,
        "drafter_id": doc.drafter_id,
        "drafter_name": drafter.name_ko if drafter else None,
        "drafter_emp_no": drafter.emp_no if drafter else None,
        "dept_name": dept.name if dept else None,
        "travel_type": detail.travel_type,
        "destination": detail.destination,
        "purpose": detail.purpose,
        "start_at": detail.start_at,
        "end_at": detail.end_at,
        "appraisal_case_no": detail.appraisal_case_no,
        "estimated_cost": detail.estimated_cost,
        "companion_count": companion_count,
        "drafted_at": doc.drafted_at,
        "completed_at": doc.completed_at,
        "has_report": has_report,
    }


def list_my(
    db: Session,
    *,
    user: User,
    status: Optional[str] = None,
    include_companion: bool = True,
) -> list[dict[str, Any]]:
    """Travel orders where user is the drafter OR a companion."""
    emp = _owner_employee(db, user)

    rows: dict[int, tuple[ApprovalDoc, TravelOrderDetail]] = {}

    drafter_q = (
        db.query(ApprovalDoc, TravelOrderDetail)
        .join(TravelOrderDetail, TravelOrderDetail.doc_id == ApprovalDoc.id)
        .filter(ApprovalDoc.drafter_id == emp.id)
    )
    if status is not None:
        drafter_q = drafter_q.filter(ApprovalDoc.status == status)
    for d, det in drafter_q.all():
        rows[d.id] = (d, det)

    if include_companion:
        comp_q = (
            db.query(ApprovalDoc, TravelOrderDetail)
            .join(
                TravelOrderDetail,
                TravelOrderDetail.doc_id == ApprovalDoc.id,
            )
            .join(
                TravelCompanion,
                TravelCompanion.travel_id == TravelOrderDetail.id,
            )
            .filter(TravelCompanion.emp_id == emp.id)
        )
        if status is not None:
            comp_q = comp_q.filter(ApprovalDoc.status == status)
        for d, det in comp_q.all():
            rows[d.id] = (d, det)

    result = sorted(
        rows.values(),
        key=lambda pair: pair[0].drafted_at or datetime.min,
        reverse=True,
    )
    return [_list_row(db, d, det) for d, det in result]


def list_team(
    db: Session,
    *,
    dept_id: int,
    status: Optional[str] = None,
) -> list[dict[str, Any]]:
    q = (
        db.query(ApprovalDoc, TravelOrderDetail)
        .join(TravelOrderDetail, TravelOrderDetail.doc_id == ApprovalDoc.id)
        .join(Employee, Employee.id == ApprovalDoc.drafter_id)
        .filter(Employee.dept_id == dept_id)
    )
    if status is not None:
        q = q.filter(ApprovalDoc.status == status)
    q = q.order_by(ApprovalDoc.drafted_at.desc())
    return [_list_row(db, d, det) for d, det in q.all()]


def find_by_case_no(
    db: Session, case_no: str
) -> list[dict[str, Any]]:
    q = (
        db.query(ApprovalDoc, TravelOrderDetail)
        .join(TravelOrderDetail, TravelOrderDetail.doc_id == ApprovalDoc.id)
        .filter(TravelOrderDetail.appraisal_case_no == case_no)
        .order_by(ApprovalDoc.drafted_at.desc())
    )
    return [_list_row(db, d, det) for d, det in q.all()]
