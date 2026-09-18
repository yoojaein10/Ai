"""Post-action hooks for ATT_LEAVE approval docs (PHASE 15)."""

from __future__ import annotations

import logging
from datetime import datetime, time
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import ApprovalDoc, LeaveRequestDetail, LeaveType
from app.services import calendar_service, leave_service, leave_request_service

log = logging.getLogger(__name__)


def _load_detail(db: Session, doc_id: int) -> LeaveRequestDetail | None:
    return (
        db.query(LeaveRequestDetail)
        .filter(LeaveRequestDetail.doc_id == doc_id)
        .first()
    )


def _leave_type(db: Session, leave_type_id: int) -> LeaveType | None:
    return db.query(LeaveType).filter(LeaveType.id == leave_type_id).first()


def _event_bounds(detail: LeaveRequestDetail) -> tuple[datetime, datetime, bool]:
    """Derive (start_at, end_at, all_day) from the leave detail row."""
    if detail.half_type == "AM":
        start_at = datetime.combine(detail.start_date, time(9, 0))
        end_at = datetime.combine(detail.start_date, time(13, 0))
        return start_at, end_at, False
    if detail.half_type == "PM":
        start_at = datetime.combine(detail.start_date, time(13, 0))
        end_at = datetime.combine(detail.start_date, time(18, 0))
        return start_at, end_at, False
    # Full day(s)
    start_at = datetime.combine(detail.start_date, time(0, 0))
    end_at = datetime.combine(detail.end_date, time(23, 59))
    return start_at, end_at, True


# ── Events ────────────────────────────────────────────────


def on_approved(db: Session, doc: ApprovalDoc) -> None:
    detail = _load_detail(db, doc.id)
    if detail is None:
        log.warning("leave_hook.on_approved: no detail for doc %s", doc.id)
        return
    lt = _leave_type(db, detail.leave_type_id)

    # 1) Consume leave (and release scheduled_days in the same tx) for ANNUAL types
    if lt is not None and lt.deduct_from == "ANNUAL":
        try:
            leave_service.consume_leave(
                db,
                emp_id=doc.drafter_id,
                days=Decimal(detail.days),
                ref_doc_id=doc.id,
                reason=f"[결재승인] {doc.title}",
                deduct_scheduled=True,
            )
        except leave_service.LeaveError as exc:
            log.exception("consume_leave failed for doc %s: %s", doc.id, exc)

    # 2) Create calendar event idempotently
    start_at, end_at, all_day = _event_bounds(detail)
    title = doc.title or (lt.name if lt else "휴가")
    try:
        calendar_service.create_event_from_approval(
            db,
            doc_id=doc.id,
            event_type="LEAVE",
            start_at=start_at,
            end_at=end_at,
            owner_id=doc.drafter_id,
            title=title,
            all_day=all_day,
            description=detail.reason,
            visibility="PRIVATE",
        )
    except Exception as exc:
        log.exception("calendar event create failed for doc %s: %s", doc.id, exc)


def on_rejected(db: Session, doc: ApprovalDoc) -> None:
    detail = _load_detail(db, doc.id)
    if detail is None:
        return
    lt = _leave_type(db, detail.leave_type_id)
    if lt is None:
        return
    try:
        leave_request_service.release_scheduled(
            db, doc.drafter_id, lt, Decimal(detail.days)
        )
        db.commit()
    except Exception as exc:
        log.exception("release_scheduled on reject failed doc %s: %s", doc.id, exc)


def on_recalled(db: Session, doc: ApprovalDoc) -> None:
    detail = _load_detail(db, doc.id)
    if detail is None:
        return
    lt = _leave_type(db, detail.leave_type_id)
    if lt is None:
        return
    try:
        leave_request_service.release_scheduled(
            db, doc.drafter_id, lt, Decimal(detail.days)
        )
        db.commit()
    except Exception as exc:
        log.exception("release_scheduled on recall failed doc %s: %s", doc.id, exc)
