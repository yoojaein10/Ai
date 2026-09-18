from datetime import datetime
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import (
    EvalApprover,
    MultiEvalIndicator,
    MultiEvalResponse,
    MultiEvalResponseLog,
    MultiEvalResult,
)
from app.schemas.multi_response import MultiSubmissionStatus
from app.schemas.multi_result import MultiIndicatorResult, MultiResultResponse

MIN_RESPONSES = 3


def calculate_result(db: Session, round_id: int, evaluatee_id: int) -> None:
    """평균 재계산 후 result 테이블에 upsert."""
    indicators = (
        db.query(MultiEvalIndicator)
        .filter(MultiEvalIndicator.round_id == round_id)
        .all()
    )
    for ind in indicators:
        rows = (
            db.query(MultiEvalResponse)
            .filter(
                MultiEvalResponse.round_id == round_id,
                MultiEvalResponse.evaluatee_id == evaluatee_id,
                MultiEvalResponse.indicator_id == ind.id,
            )
            .all()
        )
        count = len(rows)
        avg = (
            sum(Decimal(str(r.score)) for r in rows) / Decimal(count)
            if count > 0
            else None
        )
        existing = (
            db.query(MultiEvalResult)
            .filter(
                MultiEvalResult.round_id == round_id,
                MultiEvalResult.evaluatee_id == evaluatee_id,
                MultiEvalResult.indicator_id == ind.id,
            )
            .first()
        )
        if existing is None:
            db.add(
                MultiEvalResult(
                    round_id=round_id,
                    evaluatee_id=evaluatee_id,
                    indicator_id=ind.id,
                    avg_score=avg,
                    response_count=count,
                )
            )
        else:
            existing.avg_score = avg
            existing.response_count = count
    db.commit()


def get_result_for_emp(
    db: Session, round_id: int, evaluatee_id: int
) -> MultiResultResponse:
    """평가자 수가 MIN_RESPONSES 미만이면 응답 보호."""
    distinct_evaluators = (
        db.query(func.count(func.distinct(MultiEvalResponseLog.evaluator_id)))
        .filter(
            MultiEvalResponseLog.round_id == round_id,
            MultiEvalResponseLog.evaluatee_id == evaluatee_id,
        )
        .scalar()
        or 0
    )

    if distinct_evaluators < MIN_RESPONSES:
        return MultiResultResponse(
            round_id=round_id,
            evaluatee_id=evaluatee_id,
            insufficient=True,
            min_required=MIN_RESPONSES,
            indicators=[],
        )

    calculate_result(db, round_id, evaluatee_id)

    rows = (
        db.query(MultiEvalResult, MultiEvalIndicator)
        .join(MultiEvalIndicator, MultiEvalIndicator.id == MultiEvalResult.indicator_id)
        .filter(
            MultiEvalResult.round_id == round_id,
            MultiEvalResult.evaluatee_id == evaluatee_id,
        )
        .order_by(MultiEvalIndicator.id.asc())
        .all()
    )

    return MultiResultResponse(
        round_id=round_id,
        evaluatee_id=evaluatee_id,
        insufficient=False,
        min_required=MIN_RESPONSES,
        indicators=[
            MultiIndicatorResult(
                indicator_id=ind.id,
                indicator_name=ind.name,
                avg_score=res.avg_score,
                response_count=res.response_count,
            )
            for res, ind in rows
        ],
    )


def get_submission_status(db: Session, round_id: int) -> MultiSubmissionStatus:
    expected = (
        db.query(func.count(EvalApprover.id))
        .filter(
            EvalApprover.round_id == round_id,
            EvalApprover.eval_type == "MULTI",
        )
        .scalar()
        or 0
    )
    submitted = (
        db.query(func.count(MultiEvalResponseLog.id))
        .filter(MultiEvalResponseLog.round_id == round_id)
        .scalar()
        or 0
    )
    latest: datetime | None = (
        db.query(func.max(MultiEvalResponseLog.submitted_at))
        .filter(MultiEvalResponseLog.round_id == round_id)
        .scalar()
    )
    rate = (submitted / expected) if expected > 0 else 0.0
    return MultiSubmissionStatus(
        round_id=round_id,
        expected=expected,
        submitted=submitted,
        submission_rate=round(rate, 4),
        submitted_at_latest=latest,
    )
