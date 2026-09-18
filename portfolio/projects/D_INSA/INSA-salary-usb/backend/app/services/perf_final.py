from sqlalchemy.orm import Session

from app.db.models import PerfTarget, PerfTargetFinal
from app.schemas.perf_final import PerfFinalUpsert


def get_final(db: Session, target_id: int) -> PerfTargetFinal | None:
    return db.query(PerfTargetFinal).filter(PerfTargetFinal.target_id == target_id).first()


def upsert_final(db: Session, data: PerfFinalUpsert) -> PerfTargetFinal:
    target = db.query(PerfTarget).filter(PerfTarget.id == data.target_id).first()
    if target is None:
        raise ValueError(f"PerfTarget {data.target_id} not found")

    record = db.query(PerfTargetFinal).filter(PerfTargetFinal.target_id == data.target_id).first()
    if record is None:
        record = PerfTargetFinal(
            target_id=data.target_id,
            achievement_rate=data.achievement_rate,
            description=data.description,
            self_score=data.self_score,
        )
        db.add(record)
    else:
        record.achievement_rate = data.achievement_rate
        record.description = data.description
        record.self_score = data.self_score

    db.commit()
    db.refresh(record)
    return record
