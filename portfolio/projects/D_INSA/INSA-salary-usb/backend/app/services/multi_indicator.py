from sqlalchemy.orm import Session

from app.db.models import EvalRound, MultiEvalIndicator
from app.schemas.multi_indicator import MultiIndicatorCreate


def list_indicators(db: Session, round_id: int) -> list[MultiEvalIndicator]:
    return (
        db.query(MultiEvalIndicator)
        .filter(MultiEvalIndicator.round_id == round_id)
        .order_by(MultiEvalIndicator.id.asc())
        .all()
    )


def create_indicator(db: Session, data: MultiIndicatorCreate) -> MultiEvalIndicator:
    if db.query(EvalRound).filter(EvalRound.id == data.round_id).first() is None:
        raise ValueError(f"EvalRound {data.round_id} not found")
    indicator = MultiEvalIndicator(
        round_id=data.round_id,
        name=data.name,
        description=data.description,
        max_score=data.max_score,
    )
    db.add(indicator)
    db.commit()
    db.refresh(indicator)
    return indicator
