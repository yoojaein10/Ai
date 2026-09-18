from sqlalchemy.orm import Session

from app.db.models import CompEvalSelf, CompIndicator, EvalRound
from app.schemas.comp_self import CompEvalSelfBulkCreate


def list_self(db: Session, emp_id: int, round_id: int | None = None) -> list[CompEvalSelf]:
    query = db.query(CompEvalSelf).filter(CompEvalSelf.emp_id == emp_id)
    if round_id is not None:
        query = query.filter(CompEvalSelf.round_id == round_id)
    return query.order_by(CompEvalSelf.id.asc()).all()


def upsert_self_bulk(
    db: Session, emp_id: int, data: CompEvalSelfBulkCreate
) -> list[CompEvalSelf]:
    if db.query(EvalRound).filter(EvalRound.id == data.round_id).first() is None:
        raise ValueError(f"EvalRound {data.round_id} not found")

    saved: list[CompEvalSelf] = []
    for item in data.items:
        if (
            db.query(CompIndicator)
            .filter(CompIndicator.id == item.indicator_id)
            .first()
            is None
        ):
            raise ValueError(f"CompIndicator {item.indicator_id} not found")
        existing = (
            db.query(CompEvalSelf)
            .filter(
                CompEvalSelf.emp_id == emp_id,
                CompEvalSelf.round_id == data.round_id,
                CompEvalSelf.indicator_id == item.indicator_id,
            )
            .first()
        )
        if existing is None:
            existing = CompEvalSelf(
                emp_id=emp_id,
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
