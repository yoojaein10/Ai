"""API routes for PHASE 14 leave management.

Prefix: `/leave` (singular). NOTE: `/leaves` (plural) is legacy APW read-only view.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_roles
from app.db.models import (
    Department,
    Employee,
    LeaveAccrualRule,
    LeaveBalance,
    LeaveTransaction,
    LeaveType,
    User,
)
from app.db.session import get_db
from app.schemas.leave_balance import (
    CarryOverExemptRequest,
    LeaveAdjustRequest,
    LeaveBalanceResponse,
    LeaveBalanceWithEmployee,
)
from app.schemas.leave_rule import (
    LeaveAccrualRuleCreate,
    LeaveAccrualRuleResponse,
    LeaveAccrualRuleUpdate,
)
from app.schemas.leave_transaction import LeaveTransactionResponse
from app.schemas.leave_type import (
    LeaveTypeCreate,
    LeaveTypeResponse,
    LeaveTypeUpdate,
)
from app.services import leave_service as svc

router = APIRouter(prefix="/leave", tags=["leave"])

HR_ROLES = ("SYSTEM_ADMIN", "HR_ADMIN")


def _map_error(exc: Exception) -> HTTPException:
    if isinstance(exc, svc.LeaveNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, svc.InsufficientBalance):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, svc.LeaveInvalid):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail="internal error")


def _balance_with_emp(
    db: Session, bal: LeaveBalance
) -> LeaveBalanceWithEmployee:
    emp = db.get(Employee, bal.emp_id)
    dept = db.get(Department, emp.dept_id) if emp and emp.dept_id else None
    return LeaveBalanceWithEmployee(
        id=bal.id,
        emp_id=bal.emp_id,
        year=bal.year,
        initial_days=bal.initial_days,
        carried_over_days=bal.carried_over_days,
        additional_days=bal.additional_days,
        used_days=bal.used_days,
        scheduled_days=bal.scheduled_days,
        carry_over_exempt=bal.carry_over_exempt,
        updated_at=bal.updated_at,
        emp_no=emp.emp_no if emp else None,
        emp_name=emp.name_ko if emp else None,
        dept_name=dept.name if dept else None,
        hire_date=emp.hire_date.isoformat() if emp and emp.hire_date else None,
        remaining=svc.get_balance_remaining(bal),
    )


# ── Leave types (HR CRUD, employees read-only) ─────────────────


@router.get("/types", response_model=list[LeaveTypeResponse])
def list_leave_types(
    active_only: bool = Query(True),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(LeaveType)
    if active_only:
        q = q.filter(LeaveType.is_active == True)  # noqa: E712
    return q.order_by(LeaveType.sort_order, LeaveType.id).all()


@router.post(
    "/types",
    response_model=LeaveTypeResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_leave_type(
    body: LeaveTypeCreate,
    current_user: User = Depends(require_roles(*HR_ROLES)),
    db: Session = Depends(get_db),
):
    if db.query(LeaveType).filter(LeaveType.code == body.code).first():
        raise HTTPException(status_code=409, detail=f"code {body.code} exists")
    lt = LeaveType(**body.model_dump())
    db.add(lt)
    db.commit()
    db.refresh(lt)
    return lt


@router.put("/types/{type_id}", response_model=LeaveTypeResponse)
def update_leave_type(
    type_id: int,
    body: LeaveTypeUpdate,
    current_user: User = Depends(require_roles(*HR_ROLES)),
    db: Session = Depends(get_db),
):
    lt = db.get(LeaveType, type_id)
    if lt is None:
        raise HTTPException(status_code=404, detail="leave type not found")
    for key, val in body.model_dump(exclude_unset=True).items():
        setattr(lt, key, val)
    db.commit()
    db.refresh(lt)
    return lt


# ── Accrual rules (HR CRUD) ────────────────────────────────────


@router.get("/rules", response_model=list[LeaveAccrualRuleResponse])
def list_rules(
    current_user: User = Depends(require_roles(*HR_ROLES)),
    db: Session = Depends(get_db),
):
    return (
        db.query(LeaveAccrualRule)
        .order_by(LeaveAccrualRule.year.desc())
        .all()
    )


@router.get("/rules/{year}", response_model=LeaveAccrualRuleResponse)
def get_rule(
    year: int,
    current_user: User = Depends(require_roles(*HR_ROLES)),
    db: Session = Depends(get_db),
):
    rule = (
        db.query(LeaveAccrualRule).filter(LeaveAccrualRule.year == year).first()
    )
    if rule is None:
        raise HTTPException(status_code=404, detail=f"no rule for year {year}")
    return rule


@router.post(
    "/rules",
    response_model=LeaveAccrualRuleResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_rule(
    body: LeaveAccrualRuleCreate,
    current_user: User = Depends(require_roles(*HR_ROLES)),
    db: Session = Depends(get_db),
):
    if (
        db.query(LeaveAccrualRule)
        .filter(LeaveAccrualRule.year == body.year)
        .first()
    ):
        raise HTTPException(
            status_code=409, detail=f"rule for year {body.year} exists"
        )
    rule = LeaveAccrualRule(
        **body.model_dump(), updated_by=current_user.id
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.put("/rules/{year}", response_model=LeaveAccrualRuleResponse)
def update_rule(
    year: int,
    body: LeaveAccrualRuleUpdate,
    current_user: User = Depends(require_roles(*HR_ROLES)),
    db: Session = Depends(get_db),
):
    rule = (
        db.query(LeaveAccrualRule).filter(LeaveAccrualRule.year == year).first()
    )
    if rule is None:
        raise HTTPException(status_code=404, detail=f"no rule for year {year}")
    for key, val in body.model_dump(exclude_unset=True).items():
        setattr(rule, key, val)
    rule.updated_by = current_user.id
    db.commit()
    db.refresh(rule)
    return rule


# ── Balance queries ────────────────────────────────────────────


@router.get("/balance/me", response_model=LeaveBalanceWithEmployee)
def my_balance(
    year: Optional[int] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.employee_id is None:
        raise HTTPException(
            status_code=404, detail="current user has no employee record"
        )
    yr = year or date.today().year
    bal = (
        db.query(LeaveBalance)
        .filter(
            LeaveBalance.emp_id == current_user.employee_id,
            LeaveBalance.year == yr,
        )
        .first()
    )
    if bal is None:
        # Auto-create empty balance so FE has something to render
        bal = LeaveBalance(emp_id=current_user.employee_id, year=yr)
        db.add(bal)
        db.commit()
        db.refresh(bal)
    return _balance_with_emp(db, bal)


@router.get("/balance", response_model=list[LeaveBalanceWithEmployee])
def list_balances(
    year: Optional[int] = Query(None),
    dept_id: Optional[int] = Query(None),
    keyword: Optional[str] = Query(None),
    current_user: User = Depends(require_roles(*HR_ROLES)),
    db: Session = Depends(get_db),
):
    yr = year or date.today().year
    q = db.query(LeaveBalance).filter(LeaveBalance.year == yr)
    balances = q.all()

    results: list[LeaveBalanceWithEmployee] = []
    for bal in balances:
        emp = db.get(Employee, bal.emp_id)
        if emp is None:
            continue
        if dept_id is not None and emp.dept_id != dept_id:
            continue
        if keyword:
            kw = keyword.strip().lower()
            if (
                kw not in (emp.name_ko or "").lower()
                and kw not in (emp.emp_no or "").lower()
            ):
                continue
        results.append(_balance_with_emp(db, bal))
    return results


@router.get("/balance/{emp_id}", response_model=LeaveBalanceWithEmployee)
def get_emp_balance(
    emp_id: int,
    year: Optional[int] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Employees can view own or subordinates later; for now: self or HR
    roles = {ur.role.code for ur in current_user.roles}
    is_hr = bool(roles.intersection(HR_ROLES))
    is_self = current_user.employee_id == emp_id
    if not (is_hr or is_self):
        raise HTTPException(status_code=403, detail="forbidden")

    yr = year or date.today().year
    bal = (
        db.query(LeaveBalance)
        .filter(LeaveBalance.emp_id == emp_id, LeaveBalance.year == yr)
        .first()
    )
    if bal is None:
        raise HTTPException(status_code=404, detail="balance not found")
    return _balance_with_emp(db, bal)


# ── Transactions ───────────────────────────────────────────────


@router.get(
    "/transactions/{emp_id}", response_model=list[LeaveTransactionResponse]
)
def list_transactions(
    emp_id: int,
    year: Optional[int] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    roles = {ur.role.code for ur in current_user.roles}
    is_hr = bool(roles.intersection(HR_ROLES))
    is_self = current_user.employee_id == emp_id
    if not (is_hr or is_self):
        raise HTTPException(status_code=403, detail="forbidden")

    q = db.query(LeaveTransaction).filter(LeaveTransaction.emp_id == emp_id)
    if year is not None:
        q = q.filter(LeaveTransaction.year == year)
    return q.order_by(LeaveTransaction.created_at.desc()).all()


# ── Admin actions ──────────────────────────────────────────────


@router.post("/adjust", response_model=LeaveTransactionResponse)
def adjust_balance_route(
    body: LeaveAdjustRequest,
    year: Optional[int] = Query(None),
    current_user: User = Depends(require_roles(*HR_ROLES)),
    db: Session = Depends(get_db),
):
    try:
        return svc.adjust_balance(
            db,
            body.emp_id,
            body.amount,
            body.reason,
            year=year,
            actor_id=current_user.id,
        )
    except svc.LeaveError as exc:
        raise _map_error(exc)


@router.post("/carry-over-exempt", response_model=LeaveBalanceResponse)
def carry_over_exempt_route(
    body: CarryOverExemptRequest,
    current_user: User = Depends(require_roles(*HR_ROLES)),
    db: Session = Depends(get_db),
):
    try:
        bal = svc.set_carry_over_exempt(
            db, body.emp_id, body.year, body.exempt
        )
        return bal
    except svc.LeaveError as exc:
        raise _map_error(exc)


@router.post("/run-monthly")
def run_monthly_route(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    current_user: User = Depends(require_roles(*HR_ROLES)),
    db: Session = Depends(get_db),
):
    today = date.today()
    yr = year or today.year
    mo = month or today.month
    try:
        granted = svc.monthly_accrual(db, yr, mo)
        return {"year": yr, "month": mo, "granted": granted}
    except svc.LeaveError as exc:
        raise _map_error(exc)


@router.post("/run-yearly-reset")
def run_yearly_reset_route(
    year: Optional[int] = Query(None),
    current_user: User = Depends(require_roles(*HR_ROLES)),
    db: Session = Depends(get_db),
):
    yr = year or date.today().year
    try:
        return svc.yearly_reset(db, yr)
    except svc.LeaveError as exc:
        raise _map_error(exc)


@router.post("/grant-initial/{emp_id}", response_model=LeaveBalanceResponse)
def grant_initial_route(
    emp_id: int,
    year: Optional[int] = Query(None),
    current_user: User = Depends(require_roles(*HR_ROLES)),
    db: Session = Depends(get_db),
):
    yr = year or date.today().year
    try:
        return svc.create_initial_balance(
            db, emp_id, yr, actor_id=current_user.id
        )
    except svc.LeaveError as exc:
        raise _map_error(exc)
