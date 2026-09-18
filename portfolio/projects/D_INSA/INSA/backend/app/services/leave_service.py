"""Leave management service (PHASE 14).

Core domain operations for 연차 (annual leave):
- Fiscal-year initial grant based on tenure (<1yr monthly / >=1yr base + bonus)
- Monthly accrual for <1yr employees (idempotent per year-month)
- Yearly reset: expire or carry-over, then grant new year initial
- Consume / release for approval docs (PHASE 15 integration)
- Manual adjustment for HR
- Pure calculation helper `calculate_initial_days` (unit-testable)

Transactions: every balance mutation writes an `insa_leave_transaction` row with
`balance_after` snapshot so the ledger can be reconstructed.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import (
    Employee,
    LeaveAccrualRule,
    LeaveBalance,
    LeaveTransaction,
    SchedulerLock,
)


# ── Errors ──────────────────────────────────────────────────


class LeaveError(Exception):
    """Base for leave domain errors."""


class LeaveNotFound(LeaveError):
    pass


class LeaveInvalid(LeaveError):
    pass


class InsufficientBalance(LeaveError):
    pass


ZERO = Decimal("0")


# ── Pure calculation helpers ───────────────────────────────────


def completed_years(hire_date: date, at_date: date) -> int:
    """Completed years of service at `at_date`. Handles leap-day hires."""
    years = at_date.year - hire_date.year
    if (at_date.month, at_date.day) < (hire_date.month, hire_date.day):
        years -= 1
    return max(0, years)


def calculate_initial_days(
    hire_date: date, year: int, rule: LeaveAccrualRule
) -> Decimal:
    """Days granted at fiscal-year start based on tenure at Jan 1 of `year`.

    - hire_date > year_start: 0 (not yet employed at reset)
    - <1yr tenure: 0 (employee is in monthly-accrual mode for this year)
    - >=1yr: base_days + bonus (from `tenure_bonus_start_years`, every
      `tenure_bonus_interval` years +1 day), capped at `max_days`.
    """
    year_start = date(year, 1, 1)
    if hire_date > year_start:
        return ZERO
    tenure = completed_years(hire_date, year_start)
    if tenure < 1:
        return ZERO
    bonus = 0
    if tenure >= rule.tenure_bonus_start_years:
        bonus = (
            (tenure - rule.tenure_bonus_start_years) // rule.tenure_bonus_interval
            + 1
        )
    total = rule.base_days + bonus
    if total > rule.max_days:
        total = rule.max_days
    return Decimal(total)


# ── Internal helpers ───────────────────────────────────────────


def _get_rule(db: Session, year: int) -> LeaveAccrualRule:
    rule = (
        db.query(LeaveAccrualRule).filter(LeaveAccrualRule.year == year).first()
    )
    if rule is None:
        raise LeaveNotFound(f"no accrual rule for year {year}")
    return rule


def _get_or_create_balance(
    db: Session, emp_id: int, year: int
) -> LeaveBalance:
    bal = (
        db.query(LeaveBalance)
        .filter(LeaveBalance.emp_id == emp_id, LeaveBalance.year == year)
        .first()
    )
    if bal is None:
        bal = LeaveBalance(emp_id=emp_id, year=year)
        db.add(bal)
        db.flush()
    return bal


def _remaining(bal: LeaveBalance) -> Decimal:
    return (
        Decimal(bal.initial_days)
        + Decimal(bal.carried_over_days)
        + Decimal(bal.additional_days)
        - Decimal(bal.used_days)
    )


def _record_transaction(
    db: Session,
    *,
    emp_id: int,
    year: int,
    transaction_type: str,
    amount: Decimal,
    balance_after: Decimal,
    reason: Optional[str] = None,
    ref_doc_id: Optional[int] = None,
    created_by: Optional[int] = None,
) -> LeaveTransaction:
    tx = LeaveTransaction(
        emp_id=emp_id,
        year=year,
        transaction_type=transaction_type,
        amount=amount,
        reason=reason,
        ref_doc_id=ref_doc_id,
        balance_after=balance_after,
        created_by=created_by,
    )
    db.add(tx)
    db.flush()
    return tx


def _already_ran(db: Session, job_name: str, run_date: str) -> bool:
    return (
        db.query(SchedulerLock)
        .filter(
            SchedulerLock.job_name == job_name,
            SchedulerLock.run_date == run_date,
        )
        .first()
        is not None
    )


def _mark_ran(db: Session, job_name: str, run_date: str) -> None:
    db.add(SchedulerLock(job_name=job_name, run_date=run_date))
    db.flush()


# ── Public API ─────────────────────────────────────────────────


def create_initial_balance(
    db: Session,
    emp_id: int,
    year: int,
    *,
    actor_id: Optional[int] = None,
) -> LeaveBalance:
    """Grant year-start balance for a single employee. Idempotent per emp+year."""
    emp = db.get(Employee, emp_id)
    if emp is None:
        raise LeaveNotFound(f"employee {emp_id} not found")
    rule = _get_rule(db, year)
    bal = _get_or_create_balance(db, emp_id, year)

    existing = (
        db.query(LeaveTransaction)
        .filter(
            LeaveTransaction.emp_id == emp_id,
            LeaveTransaction.year == year,
            LeaveTransaction.transaction_type == "INITIAL_GRANT",
        )
        .first()
    )
    if existing is not None:
        return bal

    initial = calculate_initial_days(emp.hire_date, year, rule)
    bal.initial_days = initial
    db.flush()
    _record_transaction(
        db,
        emp_id=emp_id,
        year=year,
        transaction_type="INITIAL_GRANT",
        amount=initial,
        balance_after=_remaining(bal),
        reason=f"{year} 회계연도 시작 부여",
        created_by=actor_id,
    )
    db.commit()
    return bal


def monthly_accrual(db: Session, year: int, month: int) -> int:
    """Grant +1 day to every <1yr employee (capped at `under_1year_max`).

    Idempotent per (year, month) via `insa_scheduler_lock` + per-row reason tag.
    Returns the number of rows granted.
    """
    if not 1 <= month <= 12:
        raise LeaveInvalid("month must be 1-12")

    lock_key = "monthly_accrual"
    run_tag = f"{year:04d}-{month:02d}"
    if _already_ran(db, lock_key, run_tag):
        return 0

    rule = _get_rule(db, year)
    year_start = date(year, 1, 1)
    month_start = date(year, month, 1)
    reason_tag = f"{year}-{month:02d} 월차 부여"

    eligible = (
        db.query(Employee).filter(Employee.hire_date <= month_start).all()
    )

    granted = 0
    for emp in eligible:
        if completed_years(emp.hire_date, year_start) >= 1:
            continue

        existing_count = (
            db.query(func.count(LeaveTransaction.id))
            .filter(
                LeaveTransaction.emp_id == emp.id,
                LeaveTransaction.year == year,
                LeaveTransaction.transaction_type == "MONTHLY_GRANT",
            )
            .scalar()
        ) or 0
        if existing_count >= rule.under_1year_max:
            continue

        duplicate = (
            db.query(LeaveTransaction)
            .filter(
                LeaveTransaction.emp_id == emp.id,
                LeaveTransaction.year == year,
                LeaveTransaction.transaction_type == "MONTHLY_GRANT",
                LeaveTransaction.reason == reason_tag,
            )
            .first()
        )
        if duplicate is not None:
            continue

        bal = _get_or_create_balance(db, emp.id, year)
        amount = Decimal(rule.under_1year_monthly)
        bal.additional_days = Decimal(bal.additional_days) + amount
        db.flush()
        _record_transaction(
            db,
            emp_id=emp.id,
            year=year,
            transaction_type="MONTHLY_GRANT",
            amount=amount,
            balance_after=_remaining(bal),
            reason=reason_tag,
        )
        granted += 1

    _mark_ran(db, lock_key, run_tag)
    db.commit()
    return granted


def yearly_reset(db: Session, year: int) -> dict:
    """On Jan 1 of `year`: handle prev-year leftover (expire/carry-over) then grant initial.

    Carry-over rule: default "사용촉진 → 이월 없음" (expire). Exception: employees
    with `carry_over_exempt=True` on their prev-year balance, OR when the prev-year
    accrual rule has `carry_over_enabled=True`.

    Idempotent via scheduler lock keyed by `{year}-01-01`.
    """
    lock_key = "yearly_reset"
    run_tag = f"{year:04d}-01-01"
    if _already_ran(db, lock_key, run_tag):
        return {"status": "skipped", "expired": 0, "carried": 0, "granted": 0}

    rule = _get_rule(db, year)

    prev_year = year - 1
    prev_rule = (
        db.query(LeaveAccrualRule)
        .filter(LeaveAccrualRule.year == prev_year)
        .first()
    )
    global_carry = bool(prev_rule.carry_over_enabled) if prev_rule else False

    prev_balances = (
        db.query(LeaveBalance).filter(LeaveBalance.year == prev_year).all()
    )

    expired = 0
    carried = 0
    for bal in prev_balances:
        remaining = _remaining(bal)
        if remaining <= ZERO:
            continue
        if bal.carry_over_exempt or global_carry:
            new_bal = _get_or_create_balance(db, bal.emp_id, year)
            new_bal.carried_over_days = (
                Decimal(new_bal.carried_over_days) + remaining
            )
            db.flush()
            _record_transaction(
                db,
                emp_id=bal.emp_id,
                year=year,
                transaction_type="CARRY_OVER",
                amount=remaining,
                balance_after=_remaining(new_bal),
                reason=f"{prev_year} → {year} 이월",
            )
            # Zero out prev-year remaining so re-running can't double-count
            bal.used_days = Decimal(bal.used_days) + remaining
            db.flush()
            carried += 1
        else:
            _record_transaction(
                db,
                emp_id=bal.emp_id,
                year=prev_year,
                transaction_type="EXPIRE",
                amount=-remaining,
                balance_after=ZERO,
                reason=f"{prev_year} 미사용 연차 소멸 (사용촉진)",
            )
            bal.used_days = Decimal(bal.used_days) + remaining
            db.flush()
            expired += 1

    granted = 0
    emps = db.query(Employee).all()
    for emp in emps:
        existing = (
            db.query(LeaveTransaction)
            .filter(
                LeaveTransaction.emp_id == emp.id,
                LeaveTransaction.year == year,
                LeaveTransaction.transaction_type == "INITIAL_GRANT",
            )
            .first()
        )
        if existing is not None:
            continue

        bal = _get_or_create_balance(db, emp.id, year)
        initial = calculate_initial_days(emp.hire_date, year, rule)
        bal.initial_days = initial
        db.flush()
        _record_transaction(
            db,
            emp_id=emp.id,
            year=year,
            transaction_type="INITIAL_GRANT",
            amount=initial,
            balance_after=_remaining(bal),
            reason=f"{year} 회계연도 시작 부여",
        )
        granted += 1

    _mark_ran(db, lock_key, run_tag)
    db.commit()
    return {
        "status": "ok",
        "expired": expired,
        "carried": carried,
        "granted": granted,
    }


def consume_leave(
    db: Session,
    emp_id: int,
    days: Decimal,
    ref_doc_id: Optional[int] = None,
    *,
    year: Optional[int] = None,
    reason: Optional[str] = None,
    actor_id: Optional[int] = None,
    deduct_scheduled: bool = False,
) -> LeaveTransaction:
    """Deduct `days` from balance. Row-locked. Refuses negative balance.

    When `deduct_scheduled=True`, also reduces `scheduled_days` by `days`
    (floored at 0) in the same transaction — used when a leave request that
    previously reserved scheduled days is finally approved.
    """
    amount = Decimal(days)
    if amount <= ZERO:
        raise LeaveInvalid("days must be positive")
    yr = year if year is not None else date.today().year

    bal = (
        db.query(LeaveBalance)
        .filter(LeaveBalance.emp_id == emp_id, LeaveBalance.year == yr)
        .with_for_update()
        .first()
    )
    if bal is None:
        raise LeaveNotFound(f"no balance for emp {emp_id} year {yr}")

    if _remaining(bal) < amount:
        raise InsufficientBalance(
            f"remaining {_remaining(bal)} < requested {amount}"
        )

    bal.used_days = Decimal(bal.used_days) + amount
    if deduct_scheduled:
        new_scheduled = Decimal(bal.scheduled_days) - amount
        bal.scheduled_days = new_scheduled if new_scheduled > ZERO else ZERO
    db.flush()
    tx = _record_transaction(
        db,
        emp_id=emp_id,
        year=yr,
        transaction_type="USE",
        amount=-amount,
        balance_after=_remaining(bal),
        reason=reason or "휴가 사용",
        ref_doc_id=ref_doc_id,
        created_by=actor_id,
    )
    db.commit()
    return tx


def release_leave(
    db: Session,
    ref_doc_id: int,
    *,
    actor_id: Optional[int] = None,
) -> int:
    """Reverse every USE transaction linked to `ref_doc_id`. Idempotent."""
    uses = (
        db.query(LeaveTransaction)
        .filter(
            LeaveTransaction.ref_doc_id == ref_doc_id,
            LeaveTransaction.transaction_type == "USE",
        )
        .all()
    )
    if not uses:
        return 0

    cancelled = 0
    for u in uses:
        dup = (
            db.query(LeaveTransaction)
            .filter(
                LeaveTransaction.ref_doc_id == ref_doc_id,
                LeaveTransaction.transaction_type == "CANCEL",
                LeaveTransaction.emp_id == u.emp_id,
                LeaveTransaction.year == u.year,
            )
            .first()
        )
        if dup is not None:
            continue

        bal = (
            db.query(LeaveBalance)
            .filter(
                LeaveBalance.emp_id == u.emp_id, LeaveBalance.year == u.year
            )
            .with_for_update()
            .first()
        )
        if bal is None:
            continue
        amount = -Decimal(u.amount)  # USE amount is stored negative; flip
        bal.used_days = Decimal(bal.used_days) - amount
        if bal.used_days < ZERO:
            bal.used_days = ZERO
        db.flush()
        _record_transaction(
            db,
            emp_id=u.emp_id,
            year=u.year,
            transaction_type="CANCEL",
            amount=amount,
            balance_after=_remaining(bal),
            reason=f"결재 취소 #{ref_doc_id}",
            ref_doc_id=ref_doc_id,
            created_by=actor_id,
        )
        cancelled += 1

    db.commit()
    return cancelled


def adjust_balance(
    db: Session,
    emp_id: int,
    amount: Decimal,
    reason: str,
    *,
    year: Optional[int] = None,
    actor_id: Optional[int] = None,
) -> LeaveTransaction:
    """HR manual grant (positive) or deduction (negative)."""
    amt = Decimal(amount)
    if amt == ZERO:
        raise LeaveInvalid("amount must be non-zero")
    if not reason or not reason.strip():
        raise LeaveInvalid("reason required")

    yr = year if year is not None else date.today().year
    bal = _get_or_create_balance(db, emp_id, yr)

    if amt > ZERO:
        bal.additional_days = Decimal(bal.additional_days) + amt
    else:
        if _remaining(bal) + amt < ZERO:
            raise InsufficientBalance(
                f"adjustment would yield negative balance"
            )
        bal.used_days = Decimal(bal.used_days) + (-amt)
    db.flush()

    tx = _record_transaction(
        db,
        emp_id=emp_id,
        year=yr,
        transaction_type="ADJUST",
        amount=amt,
        balance_after=_remaining(bal),
        reason=reason.strip(),
        created_by=actor_id,
    )
    db.commit()
    return tx


def set_carry_over_exempt(
    db: Session, emp_id: int, year: int, exempt: bool
) -> LeaveBalance:
    bal = _get_or_create_balance(db, emp_id, year)
    bal.carry_over_exempt = exempt
    db.flush()
    db.commit()
    return bal


def get_balance_remaining(bal: LeaveBalance) -> Decimal:
    """Public wrapper so API layer doesn't import `_remaining`."""
    return _remaining(bal)
