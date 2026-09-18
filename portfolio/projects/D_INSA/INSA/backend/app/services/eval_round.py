from sqlalchemy.orm import Session

from app.db.models import EvalRound, EvalSchedule
from app.schemas.eval_round import EvalRoundCreate, EvalRoundUpdate
from app.schemas.eval_schedule import EvalScheduleBulkCreate


def list_rounds(db: Session, year: int | None = None) -> list[EvalRound]:
    query = db.query(EvalRound)
    if year is not None:
        query = query.filter(EvalRound.year == year)
    return query.order_by(EvalRound.year.desc(), EvalRound.id.desc()).all()


def get_round(db: Session, round_id: int) -> EvalRound | None:
    return db.query(EvalRound).filter(EvalRound.id == round_id).first()


def create_round(db: Session, data: EvalRoundCreate) -> EvalRound:
    round_ = EvalRound(
        year=data.year,
        name=data.name,
        start_date=data.start_date,
        end_date=data.end_date,
        status=data.status,
    )
    db.add(round_)
    db.commit()
    db.refresh(round_)
    return round_


def update_round(db: Session, round_id: int, data: EvalRoundUpdate) -> EvalRound:
    round_ = db.query(EvalRound).filter(EvalRound.id == round_id).first()
    if round_ is None:
        raise ValueError(f"EvalRound {round_id} not found")

    if data.name is not None:
        round_.name = data.name
    if data.start_date is not None:
        round_.start_date = data.start_date
    if data.end_date is not None:
        round_.end_date = data.end_date
    if data.status is not None:
        round_.status = data.status

    db.commit()
    db.refresh(round_)
    return round_


def close_round(db: Session, round_id: int) -> EvalRound:
    round_ = db.query(EvalRound).filter(EvalRound.id == round_id).first()
    if round_ is None:
        raise ValueError(f"EvalRound {round_id} not found")
    if round_.status == "CLOSED":
        raise ValueError("Round already closed")

    round_.status = "CLOSED"
    db.commit()
    db.refresh(round_)
    return round_


def list_schedules(db: Session, round_id: int) -> list[EvalSchedule]:
    return (
        db.query(EvalSchedule)
        .filter(EvalSchedule.round_id == round_id)
        .order_by(EvalSchedule.start_date.asc().nulls_last(), EvalSchedule.id.asc())
        .all()
    )


def bulk_upsert_schedules(db: Session, data: EvalScheduleBulkCreate) -> list[EvalSchedule]:
    round_ = db.query(EvalRound).filter(EvalRound.id == data.round_id).first()
    if round_ is None:
        raise ValueError(f"EvalRound {data.round_id} not found")

    db.query(EvalSchedule).filter(EvalSchedule.round_id == data.round_id).delete(synchronize_session=False)

    created: list[EvalSchedule] = []
    for item in data.schedules:
        sched = EvalSchedule(
            round_id=data.round_id,
            stage=item.stage,
            start_date=item.start_date,
            end_date=item.end_date,
        )
        db.add(sched)
        created.append(sched)
    db.commit()
    for sched in created:
        db.refresh(sched)
    return created
