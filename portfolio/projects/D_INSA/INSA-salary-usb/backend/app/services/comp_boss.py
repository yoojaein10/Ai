from sqlalchemy.orm import Session

from app.db.models import CompEvalBoss, CompIndicator, EvalApprover, EvalRound
from app.schemas.comp_boss import CompEvalBossBulkCreate


def _ensure_evaluator_mapped(
    db: Session, evaluatee_id: int, evaluator_id: int, round_id: int
) -> None:
    mapped = (
        db.query(EvalApprover)
        .filter(
            EvalApprover.round_id == round_id,
            EvalApprover.evaluatee_id == evaluatee_id,
            EvalApprover.evaluator_id == evaluator_id,
            EvalApprover.eval_type == "COMP",
        )
        .first()
    )
    if mapped is None:
        raise PermissionError(
            f"Evaluator {evaluator_id} not mapped for evaluatee {evaluatee_id} (round={round_id})"
        )


def list_boss(
    db: Session,
    evaluatee_id: int | None = None,
    evaluator_id: int | None = None,
    round_id: int | None = None,
) -> list[CompEvalBoss]:
    query = db.query(CompEvalBoss)
    if evaluatee_id is not None:
        query = query.filter(CompEvalBoss.evaluatee_id == evaluatee_id)
    if evaluator_id is not None:
        query = query.filter(CompEvalBoss.evaluator_id == evaluator_id)
    if round_id is not None:
        query = query.filter(CompEvalBoss.round_id == round_id)
    return query.order_by(CompEvalBoss.id.asc()).all()


def upsert_boss_bulk(
    db: Session, evaluator_id: int, data: CompEvalBossBulkCreate
) -> list[CompEvalBoss]:
    if db.query(EvalRound).filter(EvalRound.id == data.round_id).first() is None:
        raise ValueError(f"EvalRound {data.round_id} not found")
    _ensure_evaluator_mapped(db, data.evaluatee_id, evaluator_id, data.round_id)

    saved: list[CompEvalBoss] = []
    for item in data.items:
        if (
            db.query(CompIndicator)
            .filter(CompIndicator.id == item.indicator_id)
            .first()
            is None
        ):
            raise ValueError(f"CompIndicator {item.indicator_id} not found")
        existing = (
            db.query(CompEvalBoss)
            .filter(
                CompEvalBoss.evaluatee_id == data.evaluatee_id,
                CompEvalBoss.evaluator_id == evaluator_id,
                CompEvalBoss.round_id == data.round_id,
                CompEvalBoss.indicator_id == item.indicator_id,
            )
            .first()
        )
        if existing is None:
            existing = CompEvalBoss(
                evaluatee_id=data.evaluatee_id,
                evaluator_id=evaluator_id,
                round_id=data.round_id,
                indicator_id=item.indicator_id,
                score=item.score,
                comment=item.comment,
            )
            db.add(existing)
        else:
            existing.score = item.score
            existing.comment = item.comment
        saved.append(existing)

    db.commit()
    for s in saved:
        db.refresh(s)
    return saved
