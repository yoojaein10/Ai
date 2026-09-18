from sqlalchemy.orm import Session

from app.db.models import CompSarRecord, Employee
from app.schemas.comp_sar import CompSarCreate, CompSarUpdate


def list_sar(
    db: Session,
    target_emp_id: int | None = None,
    observer_id: int | None = None,
) -> list[CompSarRecord]:
    query = db.query(CompSarRecord)
    if target_emp_id is not None:
        query = query.filter(CompSarRecord.target_emp_id == target_emp_id)
    if observer_id is not None:
        query = query.filter(CompSarRecord.observer_id == observer_id)
    return query.order_by(CompSarRecord.observed_date.desc(), CompSarRecord.id.desc()).all()


def get_sar(db: Session, sar_id: int) -> CompSarRecord | None:
    return db.query(CompSarRecord).filter(CompSarRecord.id == sar_id).first()


def create_sar(db: Session, observer_id: int, data: CompSarCreate) -> CompSarRecord:
    if db.query(Employee).filter(Employee.id == data.target_emp_id).first() is None:
        raise ValueError(f"Employee {data.target_emp_id} not found")
    record = CompSarRecord(
        target_emp_id=data.target_emp_id,
        observer_id=observer_id,
        observed_date=data.observed_date,
        situation=data.situation,
        action=data.action,
        result=data.result,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def update_sar(db: Session, sar_id: int, data: CompSarUpdate) -> CompSarRecord:
    record = db.query(CompSarRecord).filter(CompSarRecord.id == sar_id).first()
    if record is None:
        raise ValueError(f"CompSarRecord {sar_id} not found")
    if data.observed_date is not None:
        record.observed_date = data.observed_date
    if data.situation is not None:
        record.situation = data.situation
    if data.action is not None:
        record.action = data.action
    if data.result is not None:
        record.result = data.result
    db.commit()
    db.refresh(record)
    return record


def delete_sar(db: Session, sar_id: int) -> None:
    record = db.query(CompSarRecord).filter(CompSarRecord.id == sar_id).first()
    if record is None:
        raise ValueError(f"CompSarRecord {sar_id} not found")
    db.delete(record)
    db.commit()
