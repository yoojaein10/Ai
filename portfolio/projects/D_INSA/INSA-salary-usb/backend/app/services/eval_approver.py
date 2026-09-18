from sqlalchemy.orm import Session

from app.db.models import EvalApprover, EvalRound, Employee
from app.schemas.eval_approver import EvalApproverBulkCreate


def list_approvers(
    db: Session,
    round_id: int,
    eval_type: str | None = None,
) -> list[EvalApprover]:
    query = db.query(EvalApprover).filter(EvalApprover.round_id == round_id)
    if eval_type is not None:
        query = query.filter(EvalApprover.eval_type == eval_type)
    return query.order_by(EvalApprover.id.asc()).all()


def bulk_upsert_approvers(db: Session, data: EvalApproverBulkCreate) -> list[EvalApprover]:
    round_ = db.query(EvalRound).filter(EvalRound.id == data.round_id).first()
    if round_ is None:
        raise ValueError(f"EvalRound {data.round_id} not found")

    created: list[EvalApprover] = []
    for item in data.items:
        evaluatee = db.query(Employee).filter(Employee.id == item.evaluatee_id).first()
        evaluator = db.query(Employee).filter(Employee.id == item.evaluator_id).first()
        if evaluatee is None or evaluator is None:
            raise ValueError(
                f"Employee not found (evaluatee={item.evaluatee_id}, evaluator={item.evaluator_id})"
            )
        if item.eval_type == "MULTI" and item.rater_type is None:
            raise ValueError("rater_type required when eval_type=MULTI")

        existing = (
            db.query(EvalApprover)
            .filter(
                EvalApprover.round_id == data.round_id,
                EvalApprover.evaluatee_id == item.evaluatee_id,
                EvalApprover.evaluator_id == item.evaluator_id,
                EvalApprover.eval_type == item.eval_type,
                EvalApprover.rater_type == item.rater_type,
            )
            .first()
        )
        if existing is not None:
            created.append(existing)
            continue

        approver = EvalApprover(
            round_id=data.round_id,
            evaluatee_id=item.evaluatee_id,
            evaluator_id=item.evaluator_id,
            eval_type=item.eval_type,
            rater_type=item.rater_type,
        )
        db.add(approver)
        created.append(approver)

    db.commit()
    for a in created:
        db.refresh(a)
    return created


def delete_approver(db: Session, approver_id: int) -> None:
    approver = db.query(EvalApprover).filter(EvalApprover.id == approver_id).first()
    if approver is None:
        raise ValueError(f"EvalApprover {approver_id} not found")
    db.delete(approver)
    db.commit()
