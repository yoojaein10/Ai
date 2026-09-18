from sqlalchemy.orm import Session

from app.db.models import CompBehavior, CompIndicator
from app.schemas.comp_indicator import CompIndicatorCreate


def list_indicators(db: Session, year: int | None = None) -> list[CompIndicator]:
    query = db.query(CompIndicator)
    if year is not None:
        query = query.filter(CompIndicator.year == year)
    return query.order_by(CompIndicator.id.asc()).all()


def get_indicator(db: Session, indicator_id: int) -> CompIndicator | None:
    return db.query(CompIndicator).filter(CompIndicator.id == indicator_id).first()


def create_indicator(db: Session, data: CompIndicatorCreate) -> CompIndicator:
    indicator = CompIndicator(
        year=data.year,
        code=data.code,
        name=data.name,
        description=data.description,
        weight=data.weight,
    )
    db.add(indicator)
    db.flush()
    for b in data.behaviors:
        db.add(
            CompBehavior(
                indicator_id=indicator.id,
                level=b.level,
                description=b.description,
            )
        )
    db.commit()
    db.refresh(indicator)
    return indicator
