from sqlalchemy.orm import Session

from app.db.models import EvalRound, PerfKpi
from app.schemas.perf_kpi import PerfKpiCreate, PerfKpiUpdate


def list_kpis(db: Session, round_id: int) -> list[PerfKpi]:
    return (
        db.query(PerfKpi)
        .filter(PerfKpi.round_id == round_id)
        .order_by(PerfKpi.id.asc())
        .all()
    )


def get_kpi(db: Session, kpi_id: int) -> PerfKpi | None:
    return db.query(PerfKpi).filter(PerfKpi.id == kpi_id).first()


def create_kpi(db: Session, data: PerfKpiCreate) -> PerfKpi:
    round_ = db.query(EvalRound).filter(EvalRound.id == data.round_id).first()
    if round_ is None:
        raise ValueError(f"EvalRound {data.round_id} not found")

    kpi = PerfKpi(
        round_id=data.round_id,
        code=data.code,
        name=data.name,
        measure_type=data.measure_type,
        weight=data.weight,
        perspective=data.perspective,
    )
    db.add(kpi)
    db.commit()
    db.refresh(kpi)
    return kpi


def update_kpi(db: Session, kpi_id: int, data: PerfKpiUpdate) -> PerfKpi:
    kpi = db.query(PerfKpi).filter(PerfKpi.id == kpi_id).first()
    if kpi is None:
        raise ValueError(f"PerfKpi {kpi_id} not found")

    if data.code is not None:
        kpi.code = data.code
    if data.name is not None:
        kpi.name = data.name
    if data.measure_type is not None:
        kpi.measure_type = data.measure_type
    if data.weight is not None:
        kpi.weight = data.weight
    if data.perspective is not None:
        kpi.perspective = data.perspective

    db.commit()
    db.refresh(kpi)
    return kpi


def delete_kpi(db: Session, kpi_id: int) -> None:
    kpi = db.query(PerfKpi).filter(PerfKpi.id == kpi_id).first()
    if kpi is None:
        raise ValueError(f"PerfKpi {kpi_id} not found")
    db.delete(kpi)
    db.commit()
