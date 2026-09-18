import json
from datetime import datetime
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import (
    CompEvalBoss,
    EvalApprover,
    EvalComprehensive,
    EvalRound,
    EvalSetting,
    MultiEvalResult,
    PerfEvalResult,
)

DEFAULT_WEIGHT = {"perf": 40, "comp": 30, "multi": 30}
DEFAULT_GRADE_CRITERIA = [
    {"grade": "S", "min": 90, "max": 100},
    {"grade": "A", "min": 80, "max": 90},
    {"grade": "B", "min": 70, "max": 80},
    {"grade": "C", "min": 60, "max": 70},
    {"grade": "D", "min": 0, "max": 60},
]


def _load_setting(db: Session, year: int) -> tuple[dict, list[dict]]:
    setting = db.query(EvalSetting).filter(EvalSetting.year == year).first()
    weight = DEFAULT_WEIGHT.copy()
    criteria = list(DEFAULT_GRADE_CRITERIA)
    if setting is not None:
        if setting.weight_config:
            weight = json.loads(setting.weight_config)
        if setting.grade_criteria:
            criteria = json.loads(setting.grade_criteria)
    total_weight = weight.get("perf", 0) + weight.get("comp", 0) + weight.get("multi", 0)
    if total_weight != 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"weight_config sum must be 100 (got {total_weight})",
        )
    return weight, criteria


def _grade_for_score(total: Decimal, criteria: list[dict]) -> str | None:
    """min <= score < max (단 max==100 이면 score==100 포함)."""
    score = float(total)
    for entry in criteria:
        lo = float(entry["min"])
        hi = float(entry["max"])
        upper_inclusive = hi >= 100
        if lo <= score < hi or (upper_inclusive and score == hi):
            return entry["grade"]
    return None


def _avg(values: list[Decimal | None]) -> Decimal | None:
    cleaned = [Decimal(str(v)) for v in values if v is not None]
    if not cleaned:
        return None
    return (sum(cleaned) / Decimal(len(cleaned))).quantize(Decimal("0.01"))


def _perf_score(db: Session, emp_id: int, round_id: int) -> Decimal | None:
    rows = (
        db.query(PerfEvalResult.score)
        .filter(
            PerfEvalResult.emp_id == emp_id,
            PerfEvalResult.round_id == round_id,
        )
        .all()
    )
    return _avg([r.score for r in rows])


def _comp_score(db: Session, emp_id: int, round_id: int) -> Decimal | None:
    rows = (
        db.query(CompEvalBoss.score)
        .filter(
            CompEvalBoss.evaluatee_id == emp_id,
            CompEvalBoss.round_id == round_id,
        )
        .all()
    )
    return _avg([Decimal(r.score) for r in rows])


def _multi_score(db: Session, emp_id: int, round_id: int) -> Decimal | None:
    rows = (
        db.query(MultiEvalResult.avg_score)
        .filter(
            MultiEvalResult.evaluatee_id == emp_id,
            MultiEvalResult.round_id == round_id,
        )
        .all()
    )
    return _avg([r.avg_score for r in rows])


def calculate_comprehensive(db: Session, round_id: int) -> int:
    round_obj = db.query(EvalRound).filter(EvalRound.id == round_id).first()
    if round_obj is None:
        raise HTTPException(status_code=404, detail="round not found")

    weight, criteria = _load_setting(db, round_obj.year)
    w_perf = Decimal(weight["perf"])
    w_comp = Decimal(weight["comp"])
    w_multi = Decimal(weight["multi"])

    emp_ids = (
        db.query(EvalApprover.evaluatee_id)
        .filter(EvalApprover.round_id == round_id)
        .distinct()
        .all()
    )
    upserted = 0
    for (emp_id,) in emp_ids:
        perf = _perf_score(db, emp_id, round_id)
        comp = _comp_score(db, emp_id, round_id)
        multi = _multi_score(db, emp_id, round_id)

        total = (
            (perf or Decimal("0")) * w_perf
            + (comp or Decimal("0")) * w_comp
            + (multi or Decimal("0")) * w_multi
        ) / Decimal("100")
        total = total.quantize(Decimal("0.01"))
        original = _grade_for_score(total, criteria)

        existing = (
            db.query(EvalComprehensive)
            .filter(
                EvalComprehensive.emp_id == emp_id,
                EvalComprehensive.round_id == round_id,
            )
            .first()
        )
        if existing is None:
            db.add(
                EvalComprehensive(
                    emp_id=emp_id,
                    round_id=round_id,
                    perf_score=perf,
                    comp_score=comp,
                    multi_score=multi,
                    total_score=total,
                    original_grade=original,
                    final_grade=original,
                    is_adjusted=False,
                )
            )
        else:
            existing.perf_score = perf
            existing.comp_score = comp
            existing.multi_score = multi
            existing.total_score = total
            existing.original_grade = original
            if not existing.is_adjusted:
                existing.final_grade = original
            existing.calculated_at = datetime.utcnow()
        upserted += 1

    db.commit()
    return upserted


def list_comprehensive(
    db: Session, round_id: int, emp_id: int | None = None
) -> list[EvalComprehensive]:
    q = db.query(EvalComprehensive).filter(EvalComprehensive.round_id == round_id)
    if emp_id is not None:
        q = q.filter(EvalComprehensive.emp_id == emp_id)
    return q.order_by(EvalComprehensive.total_score.desc()).all()


def manual_adjust_grade(
    db: Session,
    comp_id: int,
    new_grade: str,
    adjusted_reason: str,
    adjusted_by: int,
) -> EvalComprehensive:
    if not adjusted_reason or not adjusted_reason.strip():
        raise HTTPException(status_code=400, detail="adjusted_reason required")
    row = db.query(EvalComprehensive).filter(EvalComprehensive.id == comp_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="comprehensive row not found")
    # NOTE: original_grade 는 절대 변경하지 않는다 (이력 보존).
    row.final_grade = new_grade
    row.is_adjusted = True
    row.adjusted_by = adjusted_by
    row.adjusted_reason = adjusted_reason
    row.adjusted_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return row
