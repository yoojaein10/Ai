from sqlalchemy.orm import Session

from app.db.models import PerfTarget, PerfTargetMid
from app.schemas.perf_midterm import PerfMidtermUpsert


def get_midterm(db: Session, target_id: int) -> PerfTargetMid | None:
    return db.query(PerfTargetMid).filter(PerfTargetMid.target_id == target_id).first()


def upsert_midterm(db: Session, data: PerfMidtermUpsert) -> PerfTargetMid:
    target = db.query(PerfTarget).filter(PerfTarget.id == data.target_id).first()
    if target is None:
        raise ValueError(f"PerfTarget {data.target_id} not found")

    record = db.query(PerfTargetMid).filter(PerfTargetMid.target_id == data.target_id).first()
    if record is None:
        record = PerfTargetMid(
            target_id=data.target_id,
            progress_rate=data.progress_rate,
            description=data.description,
            expected_rate=data.expected_rate,
        )
        db.add(record)
    else:
        record.progress_rate = data.progress_rate
        record.description = data.description
        record.expected_rate = data.expected_rate

    db.commit()
    db.refresh(record)
    return record
