from sqlalchemy.orm import Session

from app.db.models import (
    Employee,
    EvalApprover,
    EvalRound,
    MultiEvalIndicator,
    MultiEvalResponse,
    MultiEvalResponseLog,
)
from app.schemas.multi_response import MultiResponseSubmit, MyEvalTarget


def _ensure_mapped(
    db: Session,
    evaluator_id: int,
    evaluatee_id: int,
    round_id: int,
    rater_type: str,
) -> None:
    mapped = (
        db.query(EvalApprover)
        .filter(
            EvalApprover.round_id == round_id,
            EvalApprover.evaluatee_id == evaluatee_id,
            EvalApprover.evaluator_id == evaluator_id,
            EvalApprover.eval_type == "MULTI",
            EvalApprover.rater_type == rater_type,
        )
        .first()
    )
    if mapped is None:
        raise PermissionError(
            f"Evaluator {evaluator_id} not mapped for evaluatee {evaluatee_id} (rater_type={rater_type})"
        )


def already_submitted(
    db: Session, evaluator_id: int, round_id: int, evaluatee_id: int
) -> bool:
    return (
        db.query(MultiEvalResponseLog)
        .filter(
            MultiEvalResponseLog.evaluator_id == evaluator_id,
            MultiEvalResponseLog.round_id == round_id,
            MultiEvalResponseLog.evaluatee_id == evaluatee_id,
        )
        .first()
        is not None
    )


def submit_multi_response(
    db: Session, evaluator_id: int, data: MultiResponseSubmit
) -> int:
    """
    익명 저장:
      1) log 테이블: 누가 제출했는지만 (점수/지표 없음)
      2) response 테이블: 점수만 (evaluator_id 컬럼 자체가 없음)
    두 테이블 사이엔 공통 키가 없어 JOIN으로 역추적 불가.
    중복 제출 방지: log 기준으로 검사.
    """
    if db.query(EvalRound).filter(EvalRound.id == data.round_id).first() is None:
        raise ValueError(f"EvalRound {data.round_id} not found")
    if (
        db.query(Employee).filter(Employee.id == data.evaluatee_id).first()
        is None
    ):
        raise ValueError(f"Employee {data.evaluatee_id} not found")

    _ensure_mapped(
        db, evaluator_id, data.evaluatee_id, data.round_id, data.rater_type
    )

    if already_submitted(db, evaluator_id, data.round_id, data.evaluatee_id):
        raise ValueError("Already submitted for this evaluatee in this round")

    for item in data.items:
        ind = (
            db.query(MultiEvalIndicator)
            .filter(MultiEvalIndicator.id == item.indicator_id)
            .first()
        )
        if ind is None or ind.round_id != data.round_id:
            raise ValueError(
                f"MultiEvalIndicator {item.indicator_id} not found for round {data.round_id}"
            )
        if item.score < 0 or item.score > ind.max_score:
            raise ValueError(
                f"Score out of range for indicator {item.indicator_id} (0~{ind.max_score})"
            )

    log = MultiEvalResponseLog(
        evaluator_id=evaluator_id,
        round_id=data.round_id,
        evaluatee_id=data.evaluatee_id,
    )
    db.add(log)

    inserted = 0
    for item in data.items:
        # NOTE: evaluator_id 는 절대 포함하지 않는다.
        db.add(
            MultiEvalResponse(
                round_id=data.round_id,
                evaluatee_id=data.evaluatee_id,
                rater_type=data.rater_type,
                indicator_id=item.indicator_id,
                score=item.score,
                comment=item.comment,
            )
        )
        inserted += 1

    db.commit()
    return inserted


def list_my_targets(
    db: Session, evaluator_id: int, round_id: int
) -> list[MyEvalTarget]:
    rows = (
        db.query(EvalApprover, Employee)
        .join(Employee, Employee.id == EvalApprover.evaluatee_id)
        .filter(
            EvalApprover.evaluator_id == evaluator_id,
            EvalApprover.round_id == round_id,
            EvalApprover.eval_type == "MULTI",
        )
        .all()
    )
    targets: list[MyEvalTarget] = []
    for approver, emp in rows:
        targets.append(
            MyEvalTarget(
                evaluatee_id=emp.id,
                evaluatee_emp_no=emp.emp_no,
                evaluatee_name=emp.name_ko,
                rater_type=approver.rater_type or "PEER",
                submitted=already_submitted(db, evaluator_id, round_id, emp.id),
            )
        )
    return targets
