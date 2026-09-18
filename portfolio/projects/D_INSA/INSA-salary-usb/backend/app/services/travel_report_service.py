"""Travel report (복명서) service (PHASE 16).

Creates a separate TRAVEL_REPORT approval doc that links back to the
originating TravelOrderDetail. The TRAVEL_ORDER must already be APPROVED
before a report can be drafted.

Flow:
- create_draft: TRAVEL_REPORT approval doc + insa_travel_report row (1:1)
- submit: wraps approval_service.submit_doc
- cancel: delete DRAFT report, recall PENDING/IN_PROGRESS
- on_approved hook stamps reported_at (see doc_hooks/travel_hook.py)
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from app.db.models import (
    ApprovalDoc,
    ApprovalDocType,
    Employee,
    TravelOrderDetail,
    TravelReport,
    User,
)
from app.services import approval_service as approval_svc


TRAVEL_REPORT_DOC_TYPE = "TRAVEL_REPORT"


class TravelReportError(Exception):
    pass


class TravelReportInvalid(TravelReportError):
    pass


class TravelReportNotFound(TravelReportError):
    pass


def _owner_employee(db: Session, user: User) -> Employee:
    if user.employee_id is None:
        raise TravelReportInvalid("기안자에 연결된 직원이 없습니다")
    emp = db.query(Employee).filter(Employee.id == user.employee_id).first()
    if emp is None:
        raise TravelReportInvalid("직원을 찾을 수 없습니다")
    return emp


def _doc_type_id(db: Session) -> int:
    dt = (
        db.query(ApprovalDocType)
        .filter(ApprovalDocType.code == TRAVEL_REPORT_DOC_TYPE)
        .first()
    )
    if dt is None:
        raise TravelReportInvalid(
            f"approval doc type {TRAVEL_REPORT_DOC_TYPE} not configured"
        )
    return dt.id


def _order_detail_from_doc(
    db: Session, travel_order_doc_id: int
) -> TravelOrderDetail:
    detail = (
        db.query(TravelOrderDetail)
        .filter(TravelOrderDetail.doc_id == travel_order_doc_id)
        .first()
    )
    if detail is None:
        raise TravelReportNotFound(
            f"travel order detail for doc {travel_order_doc_id}"
        )
    return detail


def create_draft(
    db: Session,
    *,
    user: User,
    travel_order_doc_id: int,
    line_template_id: int,
    title: Optional[str],
    report_content: str,
    actual_cost: Optional[Any],
    receipts_url: Optional[str],
) -> tuple[ApprovalDoc, TravelReport]:
    emp = _owner_employee(db, user)
    order = (
        db.query(ApprovalDoc)
        .filter(ApprovalDoc.id == travel_order_doc_id)
        .first()
    )
    if order is None:
        raise TravelReportNotFound(
            f"travel order doc {travel_order_doc_id} not found"
        )
    if order.status != "APPROVED":
        raise TravelReportInvalid("승인된 출장명령부에만 복명서를 작성할 수 있습니다")
    if order.drafter_id != emp.id:
        raise TravelReportInvalid("본인이 기안한 출장만 복명서를 작성할 수 있습니다")

    detail = _order_detail_from_doc(db, travel_order_doc_id)

    existing = (
        db.query(TravelReport)
        .filter(TravelReport.travel_id == detail.id)
        .first()
    )
    if existing is not None:
        raise TravelReportInvalid("이미 복명서가 존재합니다")

    default_title = title or f"[복명] {order.title}"
    content = {
        "travel_order_doc_id": travel_order_doc_id,
        "travel_order_doc_no": order.doc_no,
        "destination": detail.destination,
        "report_content": report_content,
        "actual_cost": str(actual_cost) if actual_cost is not None else None,
    }
    report_doc = approval_svc.create_draft(
        db,
        user=user,
        doc_type_id=_doc_type_id(db),
        title=default_title,
        content=content,
        line_template_id=line_template_id,
    )

    report = TravelReport(
        travel_id=detail.id,
        doc_id=report_doc.id,
        report_content=report_content,
        actual_cost=actual_cost,
        receipts_url=receipts_url,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report_doc, report


def submit(db: Session, doc_id: int, user: User) -> ApprovalDoc:
    report = db.query(TravelReport).filter(TravelReport.doc_id == doc_id).first()
    if report is None:
        raise TravelReportNotFound(f"travel report for doc {doc_id}")
    doc = approval_svc.submit_doc(db, doc_id, user)
    db.refresh(doc)
    return doc


def cancel(db: Session, doc_id: int, user: User) -> ApprovalDoc:
    doc = db.query(ApprovalDoc).filter(ApprovalDoc.id == doc_id).first()
    if doc is None:
        raise TravelReportNotFound(f"doc {doc_id} not found")

    if doc.status == "DRAFT":
        db.query(TravelReport).filter(TravelReport.doc_id == doc_id).delete()
        db.delete(doc)
        db.commit()
        return doc

    if doc.status in ("PENDING", "IN_PROGRESS"):
        doc = approval_svc.recall_doc(db, doc_id, user)
        db.refresh(doc)
        return doc

    raise TravelReportInvalid(f"{doc.status} 상태는 취소할 수 없습니다")


def get_by_travel_order(
    db: Session, travel_order_doc_id: int
) -> Optional[TravelReport]:
    detail = _order_detail_from_doc(db, travel_order_doc_id)
    return (
        db.query(TravelReport)
        .filter(TravelReport.travel_id == detail.id)
        .first()
    )
