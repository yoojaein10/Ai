"""Leave request service (PHASE 15).

Bridges the leave domain (PHASE 14) with the approval workflow (PHASE 12).
A leave request is an `insa_approval_doc` of type `ATT_LEAVE`, with a
structured `insa_leave_request_detail` row for the day range.

This service handles:
- `calculate_days`: pure preview used by the form
- `create_draft`: wraps approval_service.create_draft + writes detail row
- `submit`: wraps approval_service.submit_doc + reserves `scheduled_days`
- `cancel`: recall draft / pending doc, release reservation
- `list_my` / `list_team`: read side for employee / dept head
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.db.models import (
    ApprovalDoc,
    ApprovalDocType,
    Department,
    Employee,
    LeaveBalance,
    LeaveRequestDetail,
    LeaveType,
    User,
)
from app.services import approval_service as approval_svc
from app.services import holiday_service as holiday_svc


ZERO = Decimal("0")
HALF = Decimal("0.5")
LEAVE_DOC_TYPE_CODE = "ATT_LEAVE"


# ── Errors ─────────────────────────────────────────────────


class LeaveRequestError(Exception):
    pass


class LeaveRequestInvalid(LeaveRequestError):
    pass


class LeaveRequestNotFound(LeaveRequestError):
    pass


class InsufficientLeaveBalance(LeaveRequestError):
    pass


# ── Helpers ────────────────────────────────────────────────


def _owner_employee(db: Session, user: User) -> Employee:
    if user.employee_id is None:
        raise LeaveRequestInvalid("기안자에 연결된 직원이 없습니다")
    emp = db.query(Employee).filter(Employee.id == user.employee_id).first()
    if emp is None:
        raise LeaveRequestInvalid("직원을 찾을 수 없습니다")
    return emp


def _leave_type(db: Session, leave_type_id: int) -> LeaveType:
    lt = (
        db.query(LeaveType).filter(LeaveType.id == leave_type_id).first()
    )
    if lt is None:
        raise LeaveRequestNotFound(f"leave_type {leave_type_id} not found")
    return lt


def _doc_type_id(db: Session) -> int:
    dt = (
        db.query(ApprovalDocType)
        .filter(ApprovalDocType.code == LEAVE_DOC_TYPE_CODE)
        .first()
    )
    if dt is None:
        raise LeaveRequestInvalid(
            f"approval doc type {LEAVE_DOC_TYPE_CODE} not configured"
        )
    return dt.id


def _remaining(bal: LeaveBalance) -> Decimal:
    granted = (
        Decimal(bal.initial_days)
        + Decimal(bal.carried_over_days)
        + Decimal(bal.additional_days)
    )
    return granted - Decimal(bal.used_days) - Decimal(bal.scheduled_days)


# ── Pure day calculation ───────────────────────────────────


def calculate_days(
    db: Session,
    *,
    leave_type: LeaveType,
    start_date: date,
    end_date: date,
    half_type: Optional[str],
) -> dict[str, Any]:
    """Return {days, business_days, excluded_holidays, unit}.

    Rules:
    - HALF_DAY unit: start must equal end, `half_type` required, days = 0.5
    - DAY unit: days = business_days(start, end) (excludes weekends + holidays)
    - HOUR unit: not yet implemented (days = 0)
    """
    if start_date > end_date:
        raise LeaveRequestInvalid("start_date must be <= end_date")

    unit = leave_type.unit
    excluded: list[date] = []
    bdays = 0
    days = ZERO

    if unit == "HALF_DAY":
        if start_date != end_date:
            raise LeaveRequestInvalid("반차는 같은 날짜만 가능합니다")
        if half_type not in ("AM", "PM"):
            raise LeaveRequestInvalid("반차 시간대(AM/PM)를 선택하세요")
        if holiday_svc.is_weekend(start_date) or holiday_svc.is_holiday(
            db, start_date
        ):
            raise LeaveRequestInvalid("주말·공휴일에는 반차를 신청할 수 없습니다")
        bdays = 1
        days = HALF
    elif unit == "DAY":
        bdays = holiday_svc.business_days(db, start_date, end_date)
        days = Decimal(bdays)
        current = start_date
        while current <= end_date:
            if not holiday_svc.is_weekend(current) and holiday_svc.is_holiday(
                db, current
            ):
                excluded.append(current)
            current += timedelta(days=1)
    else:  # HOUR — not supported in MVP
        raise LeaveRequestInvalid("시간단위 휴가는 미지원입니다")

    return {
        "days": days,
        "business_days": bdays,
        "excluded_holidays": excluded,
        "unit": unit,
    }


# ── Draft / submit / cancel ────────────────────────────────


def _validate_balance(
    db: Session, emp_id: int, leave_type: LeaveType, days: Decimal
) -> None:
    """If the type deducts from ANNUAL, check the current-year balance."""
    if leave_type.deduct_from != "ANNUAL":
        return
    yr = date.today().year
    bal = (
        db.query(LeaveBalance)
        .filter(LeaveBalance.emp_id == emp_id, LeaveBalance.year == yr)
        .first()
    )
    if bal is None:
        raise InsufficientLeaveBalance("연차 잔여가 없습니다")
    rem = _remaining(bal)
    if rem < days:
        raise InsufficientLeaveBalance(
            f"연차 잔여 {rem} < 신청 {days}"
        )


def create_draft(
    db: Session,
    *,
    user: User,
    leave_type_id: int,
    line_template_id: int,
    start_date: date,
    end_date: date,
    half_type: Optional[str],
    title: Optional[str],
    reason: Optional[str],
    delegate_emp_id: Optional[int],
    contact_during_leave: Optional[str],
    evidence_file_url: Optional[str],
) -> tuple[ApprovalDoc, LeaveRequestDetail]:
    emp = _owner_employee(db, user)
    leave_type = _leave_type(db, leave_type_id)
    calc = calculate_days(
        db,
        leave_type=leave_type,
        start_date=start_date,
        end_date=end_date,
        half_type=half_type,
    )
    days = calc["days"]
    if days <= ZERO:
        raise LeaveRequestInvalid("신청 일수가 0입니다")

    _validate_balance(db, emp.id, leave_type, days)

    default_title = title or (
        f"{leave_type.name} {start_date}"
        if start_date == end_date
        else f"{leave_type.name} {start_date}~{end_date}"
    )
    content = {
        "leave_type_id": leave_type_id,
        "leave_type_name": leave_type.name,
        "start_date": str(start_date),
        "end_date": str(end_date),
        "half_type": half_type,
        "days": str(days),
        "reason": reason,
    }
    doc = approval_svc.create_draft(
        db,
        user=user,
        doc_type_id=_doc_type_id(db),
        title=default_title,
        content=content,
        line_template_id=line_template_id,
    )

    detail = LeaveRequestDetail(
        doc_id=doc.id,
        leave_type_id=leave_type_id,
        start_date=start_date,
        end_date=end_date,
        half_type=half_type,
        days=days,
        reason=reason,
        delegate_emp_id=delegate_emp_id,
        contact_during_leave=contact_during_leave,
        evidence_file_url=evidence_file_url,
    )
    db.add(detail)
    db.commit()
    db.refresh(detail)
    return doc, detail


def _reserve_scheduled(
    db: Session, emp_id: int, leave_type: LeaveType, days: Decimal
) -> None:
    """Increment LeaveBalance.scheduled_days for ANNUAL types."""
    if leave_type.deduct_from != "ANNUAL":
        return
    yr = date.today().year
    bal = (
        db.query(LeaveBalance)
        .filter(LeaveBalance.emp_id == emp_id, LeaveBalance.year == yr)
        .with_for_update()
        .first()
    )
    if bal is None:
        raise InsufficientLeaveBalance("연차 잔여가 없습니다")
    if _remaining(bal) < days:
        raise InsufficientLeaveBalance("연차 잔여 부족")
    bal.scheduled_days = Decimal(bal.scheduled_days) + days
    db.flush()


def submit(db: Session, doc_id: int, user: User) -> ApprovalDoc:
    """Submit a DRAFT leave request → PENDING + reserve scheduled_days."""
    detail = (
        db.query(LeaveRequestDetail)
        .filter(LeaveRequestDetail.doc_id == doc_id)
        .first()
    )
    if detail is None:
        raise LeaveRequestNotFound(f"leave request detail for doc {doc_id}")
    leave_type = _leave_type(db, detail.leave_type_id)
    emp = _owner_employee(db, user)

    _validate_balance(db, emp.id, leave_type, Decimal(detail.days))
    doc = approval_svc.submit_doc(db, doc_id, user)
    _reserve_scheduled(db, emp.id, leave_type, Decimal(detail.days))
    db.commit()
    db.refresh(doc)
    return doc


def cancel(db: Session, doc_id: int, user: User) -> ApprovalDoc:
    """Cancel a leave request.

    - DRAFT: delete detail and doc via approval_service (no balance touched)
    - PENDING/IN_PROGRESS: recall via approval_service + release scheduled_days
    - APPROVED/REJECTED: not handled here (separate flow)
    """
    doc = db.query(ApprovalDoc).filter(ApprovalDoc.id == doc_id).first()
    if doc is None:
        raise LeaveRequestNotFound(f"doc {doc_id} not found")

    if doc.status == "DRAFT":
        # Just delete detail + doc
        db.query(LeaveRequestDetail).filter(
            LeaveRequestDetail.doc_id == doc_id
        ).delete()
        db.delete(doc)
        db.commit()
        return doc

    if doc.status in ("PENDING", "IN_PROGRESS"):
        # recall_doc triggers the recall hook which releases scheduled_days.
        doc = approval_svc.recall_doc(db, doc_id, user)
        db.refresh(doc)
        return doc

    raise LeaveRequestInvalid(f"{doc.status} 상태는 취소할 수 없습니다")


def release_scheduled(
    db: Session, emp_id: int, leave_type: LeaveType, days: Decimal
) -> None:
    """Decrement scheduled_days after recall/reject. Floor at 0."""
    if leave_type.deduct_from != "ANNUAL":
        return
    yr = date.today().year
    bal = (
        db.query(LeaveBalance)
        .filter(LeaveBalance.emp_id == emp_id, LeaveBalance.year == yr)
        .with_for_update()
        .first()
    )
    if bal is None:
        return
    new_scheduled = Decimal(bal.scheduled_days) - days
    bal.scheduled_days = new_scheduled if new_scheduled > ZERO else ZERO
    db.flush()


# ── List (read) ────────────────────────────────────────────


def _list_row(
    db: Session, doc: ApprovalDoc, detail: LeaveRequestDetail
) -> dict[str, Any]:
    drafter = db.query(Employee).filter(Employee.id == doc.drafter_id).first()
    dept = (
        db.query(Department).filter(Department.id == drafter.dept_id).first()
        if drafter and drafter.dept_id
        else None
    )
    lt = db.query(LeaveType).filter(LeaveType.id == detail.leave_type_id).first()
    return {
        "doc_id": doc.id,
        "doc_no": doc.doc_no,
        "title": doc.title,
        "status": doc.status,
        "drafter_id": doc.drafter_id,
        "drafter_name": drafter.name_ko if drafter else None,
        "drafter_emp_no": drafter.emp_no if drafter else None,
        "dept_name": dept.name if dept else None,
        "leave_type_id": detail.leave_type_id,
        "leave_type_name": lt.name if lt else None,
        "start_date": detail.start_date,
        "end_date": detail.end_date,
        "half_type": detail.half_type,
        "days": detail.days,
        "reason": detail.reason,
        "drafted_at": doc.drafted_at,
        "completed_at": doc.completed_at,
    }


def list_my(
    db: Session,
    *,
    user: User,
    year: Optional[int] = None,
    status: Optional[str] = None,
) -> list[dict[str, Any]]:
    emp = _owner_employee(db, user)
    q = (
        db.query(ApprovalDoc, LeaveRequestDetail)
        .join(
            LeaveRequestDetail, LeaveRequestDetail.doc_id == ApprovalDoc.id
        )
        .filter(ApprovalDoc.drafter_id == emp.id)
    )
    if year is not None:
        q = q.filter(
            or_(
                and_(
                    LeaveRequestDetail.start_date
                    >= date(year, 1, 1),
                    LeaveRequestDetail.start_date
                    <= date(year, 12, 31),
                )
            )
        )
    if status is not None:
        q = q.filter(ApprovalDoc.status == status)
    q = q.order_by(ApprovalDoc.drafted_at.desc())
    return [_list_row(db, d, det) for d, det in q.all()]


def list_team(
    db: Session,
    *,
    dept_id: int,
    year: Optional[int] = None,
    status: Optional[str] = None,
) -> list[dict[str, Any]]:
    q = (
        db.query(ApprovalDoc, LeaveRequestDetail)
        .join(
            LeaveRequestDetail, LeaveRequestDetail.doc_id == ApprovalDoc.id
        )
        .join(Employee, Employee.id == ApprovalDoc.drafter_id)
        .filter(Employee.dept_id == dept_id)
    )
    if year is not None:
        q = q.filter(
            LeaveRequestDetail.start_date >= date(year, 1, 1),
            LeaveRequestDetail.start_date <= date(year, 12, 31),
        )
    if status is not None:
        q = q.filter(ApprovalDoc.status == status)
    q = q.order_by(ApprovalDoc.drafted_at.desc())
    return [_list_row(db, d, det) for d, det in q.all()]
