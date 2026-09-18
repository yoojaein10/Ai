from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import Employee, EvalApprover, EvalRound, PerfTarget, User
from app.schemas.perf_target import PerfTargetCreate, PerfTargetUpdate
from app.services import notification as notif_svc

VALID_TRANSITIONS = {
    "DRAFT": {"SUBMITTED"},
    "SUBMITTED": {"APPROVED", "REJECTED"},
    "REJECTED": {"DRAFT", "SUBMITTED"},
    "APPROVED": set(),
}


def list_targets(
    db: Session,
    emp_id: int | None = None,
    round_id: int | None = None,
) -> list[PerfTarget]:
    query = db.query(PerfTarget)
    if emp_id is not None:
        query = query.filter(PerfTarget.emp_id == emp_id)
    if round_id is not None:
        query = query.filter(PerfTarget.round_id == round_id)
    return query.order_by(PerfTarget.id.asc()).all()


def get_target(db: Session, target_id: int) -> PerfTarget | None:
    return db.query(PerfTarget).filter(PerfTarget.id == target_id).first()


def _sum_weight_excluding(db: Session, emp_id: int, round_id: int, exclude_id: int | None) -> Decimal:
    query = db.query(func.coalesce(func.sum(PerfTarget.weight_percent), 0)).filter(
        PerfTarget.emp_id == emp_id,
        PerfTarget.round_id == round_id,
    )
    if exclude_id is not None:
        query = query.filter(PerfTarget.id != exclude_id)
    return Decimal(str(query.scalar() or 0))


def _validate_weight(db: Session, emp_id: int, round_id: int, weight: Decimal | None, exclude_id: int | None = None) -> None:
    if weight is None:
        return
    other = _sum_weight_excluding(db, emp_id, round_id, exclude_id)
    if other + Decimal(str(weight)) > Decimal("100"):
        raise ValueError(
            f"weight_percent sum exceeds 100 for emp_id={emp_id} round_id={round_id} (existing={other}, adding={weight})"
        )


def create_target(db: Session, data: PerfTargetCreate) -> PerfTarget:
    if db.query(EvalRound).filter(EvalRound.id == data.round_id).first() is None:
        raise ValueError(f"EvalRound {data.round_id} not found")
    if db.query(Employee).filter(Employee.id == data.emp_id).first() is None:
        raise ValueError(f"Employee {data.emp_id} not found")

    _validate_weight(db, data.emp_id, data.round_id, data.weight_percent)

    target = PerfTarget(
        emp_id=data.emp_id,
        round_id=data.round_id,
        kpi_id=data.kpi_id,
        target_value=data.target_value,
        is_organization=data.is_organization,
        weight_percent=data.weight_percent,
        status="DRAFT",
    )
    db.add(target)
    db.commit()
    db.refresh(target)
    return target


def update_target(db: Session, target_id: int, data: PerfTargetUpdate) -> PerfTarget:
    target = db.query(PerfTarget).filter(PerfTarget.id == target_id).first()
    if target is None:
        raise ValueError(f"PerfTarget {target_id} not found")
    if target.status not in ("DRAFT", "REJECTED"):
        raise ValueError(f"Cannot update target in status {target.status}")

    if data.weight_percent is not None:
        _validate_weight(db, target.emp_id, target.round_id, data.weight_percent, exclude_id=target.id)
        target.weight_percent = data.weight_percent
    if data.kpi_id is not None:
        target.kpi_id = data.kpi_id
    if data.target_value is not None:
        target.target_value = data.target_value
    if data.is_organization is not None:
        target.is_organization = data.is_organization

    db.commit()
    db.refresh(target)
    return target


def _transition(target: PerfTarget, next_status: str) -> None:
    allowed = VALID_TRANSITIONS.get(target.status, set())
    if next_status not in allowed:
        raise ValueError(f"Invalid transition: {target.status} -> {next_status}")
    target.status = next_status


def submit_target(db: Session, target_id: int) -> PerfTarget:
    target = db.query(PerfTarget).filter(PerfTarget.id == target_id).first()
    if target is None:
        raise ValueError(f"PerfTarget {target_id} not found")
    _transition(target, "SUBMITTED")
    db.flush()

    evaluator_emp_ids = [
        row[0]
        for row in db.query(EvalApprover.evaluator_id)
        .filter(
            EvalApprover.round_id == target.round_id,
            EvalApprover.evaluatee_id == target.emp_id,
            EvalApprover.eval_type == "PERF",
        )
        .all()
    ]
    if evaluator_emp_ids:
        evaluator_user_ids = [
            row[0]
            for row in db.query(User.id)
            .filter(User.employee_id.in_(evaluator_emp_ids), User.is_active.is_(True))
            .all()
        ]
        evaluatee_name = (
            db.query(Employee.name_ko).filter(Employee.id == target.emp_id).scalar()
            or f"사번 {target.emp_id}"
        )
        notif_svc.create_many(
            db,
            user_ids=evaluator_user_ids,
            type="PERF_TARGET_SUBMITTED",
            title=f"{evaluatee_name} 님의 성과목표 승인 요청",
            message=None,
            link=f"/eval/perf/targets?round_id={target.round_id}&emp_id={target.emp_id}",
        )

    db.commit()
    db.refresh(target)
    return target


def approve_target(db: Session, target_id: int, evaluator_emp_id: int) -> PerfTarget:
    target = db.query(PerfTarget).filter(PerfTarget.id == target_id).first()
    if target is None:
        raise ValueError(f"PerfTarget {target_id} not found")
    _ensure_evaluator_mapped(db, target, evaluator_emp_id)
    _transition(target, "APPROVED")
    db.commit()
    db.refresh(target)
    return target


def reject_target(db: Session, target_id: int, evaluator_emp_id: int) -> PerfTarget:
    target = db.query(PerfTarget).filter(PerfTarget.id == target_id).first()
    if target is None:
        raise ValueError(f"PerfTarget {target_id} not found")
    _ensure_evaluator_mapped(db, target, evaluator_emp_id)
    _transition(target, "REJECTED")
    db.commit()
    db.refresh(target)
    return target


def _ensure_evaluator_mapped(db: Session, target: PerfTarget, evaluator_emp_id: int) -> None:
    mapped = (
        db.query(EvalApprover)
        .filter(
            EvalApprover.round_id == target.round_id,
            EvalApprover.evaluatee_id == target.emp_id,
            EvalApprover.evaluator_id == evaluator_emp_id,
            EvalApprover.eval_type == "PERF",
        )
        .first()
    )
    if mapped is None:
        raise PermissionError(
            f"Evaluator {evaluator_emp_id} is not mapped for target {target.id}"
        )


def is_authorized_to_view(db: Session, target: PerfTarget, current_user_emp_id: int | None, role_codes: set[str]) -> bool:
    if {"SYSTEM_ADMIN", "HR_ADMIN"}.intersection(role_codes):
        return True
    if current_user_emp_id is None:
        return False
    if target.emp_id == current_user_emp_id:
        return True
    mapped = (
        db.query(EvalApprover)
        .filter(
            EvalApprover.round_id == target.round_id,
            EvalApprover.evaluatee_id == target.emp_id,
            EvalApprover.evaluator_id == current_user_emp_id,
            EvalApprover.eval_type == "PERF",
        )
        .first()
    )
    return mapped is not None
