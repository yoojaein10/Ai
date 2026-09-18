"""Post-action hooks for TRAVEL_ORDER / TRAVEL_REPORT approval docs (PHASE 16).

- TRAVEL_ORDER on_approved → create a single calendar event for the trip,
  with the drafter as owner and all companions as participants. Idempotent by
  (source_type='APPROVAL_DOC', source_ref=doc_id) so resubmission/re-approval
  updates the event in place.
- TRAVEL_ORDER on_rejected / on_recalled → remove the event if any exists.
- TRAVEL_REPORT on_approved → stamp `reported_at` on the linked report row.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import (
    ApprovalDoc,
    ApprovalDocType,
    TravelCompanion,
    TravelOrderDetail,
    TravelReport,
)
from app.services import calendar_service

log = logging.getLogger(__name__)


def _doc_type_code(db: Session, doc: ApprovalDoc) -> str | None:
    dt = (
        db.query(ApprovalDocType)
        .filter(ApprovalDocType.id == doc.doc_type_id)
        .first()
    )
    return dt.code if dt else None


def _load_order_detail(db: Session, doc_id: int) -> TravelOrderDetail | None:
    return (
        db.query(TravelOrderDetail)
        .filter(TravelOrderDetail.doc_id == doc_id)
        .first()
    )


def _companion_emp_ids(db: Session, travel_id: int) -> list[int]:
    rows = (
        db.query(TravelCompanion)
        .filter(TravelCompanion.travel_id == travel_id)
        .all()
    )
    return [r.emp_id for r in rows]


# ── TRAVEL_ORDER hooks ─────────────────────────────────────


def _create_travel_event(db: Session, doc: ApprovalDoc) -> None:
    detail = _load_order_detail(db, doc.id)
    if detail is None:
        log.warning("travel_hook.on_approved: no detail for doc %s", doc.id)
        return

    companion_ids = _companion_emp_ids(db, detail.id)
    title = doc.title or f"{detail.destination} 출장"
    description = detail.purpose
    try:
        calendar_service.create_event_from_approval(
            db,
            doc_id=doc.id,
            event_type="TRAVEL",
            start_at=detail.start_at,
            end_at=detail.end_at,
            owner_id=doc.drafter_id,
            title=title,
            all_day=False,
            description=description,
            location=detail.destination,
            visibility="PUBLIC",
            participant_emp_ids=companion_ids,
        )
    except Exception as exc:
        log.exception(
            "calendar event create failed for travel doc %s: %s", doc.id, exc
        )


def _delete_travel_event(db: Session, doc: ApprovalDoc) -> None:
    try:
        calendar_service.delete_events_from_approval(db, doc.id)
    except Exception as exc:
        log.exception(
            "calendar event delete failed for travel doc %s: %s", doc.id, exc
        )


# ── TRAVEL_REPORT hooks ────────────────────────────────────


def _stamp_report_approved(db: Session, doc: ApprovalDoc) -> None:
    report = (
        db.query(TravelReport).filter(TravelReport.doc_id == doc.id).first()
    )
    if report is None:
        log.warning("travel_hook report: no report for doc %s", doc.id)
        return
    report.reported_at = datetime.utcnow()
    db.commit()


# ── Dispatch entry points ──────────────────────────────────


def on_approved(db: Session, doc: ApprovalDoc) -> None:
    code = _doc_type_code(db, doc)
    if code == "TRAVEL_ORDER":
        _create_travel_event(db, doc)
    elif code == "TRAVEL_REPORT":
        _stamp_report_approved(db, doc)


def on_rejected(db: Session, doc: ApprovalDoc) -> None:
    code = _doc_type_code(db, doc)
    if code == "TRAVEL_ORDER":
        _delete_travel_event(db, doc)


def on_recalled(db: Session, doc: ApprovalDoc) -> None:
    code = _doc_type_code(db, doc)
    if code == "TRAVEL_ORDER":
        _delete_travel_event(db, doc)
