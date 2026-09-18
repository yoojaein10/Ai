"""DB → 프롬프트 입력 dict 변환.

수집 항목:
- EvalComprehensive (정량 헤더)
- PerfEvalResult, CompEvalSelf, CompEvalBoss (점수+코멘트)
- MultiEvalResult (avg_score + response_count, response_count<3 indicator 제외)
- CompSarRecord (관찰기록) — 회차 무관 전체 기록 포함 (longitudinal context)
- Employee + Department (메타) — Employee.job_rank는 String 컬럼

다면평가 익명성 보장:
- evaluator_id는 어떤 단계에서도 입력에 포함되지 않음
- response_count<3 indicator 제외, 전체<3이면 multi 통째로 제외
- multi_response_count는 visible indicators의 응답 수만 카운트 (suppressed 제외)
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import (
    CompEvalBoss,
    CompEvalSelf,
    CompIndicator,
    CompSarRecord,
    Department,
    Employee,
    EvalComprehensive,
    EvalRound,
    MultiEvalIndicator,
    MultiEvalResult,
    PerfEvalResult,
)


def build_input(db: Session, round_id: int, employee_id: int) -> dict[str, Any]:
    comp = (
        db.query(EvalComprehensive)
        .filter(
            EvalComprehensive.round_id == round_id,
            EvalComprehensive.emp_id == employee_id,
        )
        .first()
    )
    if comp is None:
        raise ValueError(
            f"comprehensive not calculated for round={round_id}, emp={employee_id}"
        )

    rnd = db.query(EvalRound).filter(EvalRound.id == round_id).first()
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    dept = (
        db.query(Department).filter(Department.id == emp.dept_id).first()
        if emp.dept_id
        else None
    )

    # job_rank is a plain string column on Employee (no FK to a JobRank table)
    job_rank_name = emp.job_rank or ""

    multi_results = (
        db.query(MultiEvalResult, MultiEvalIndicator.name)
        .join(MultiEvalIndicator, MultiEvalResult.indicator_id == MultiEvalIndicator.id)
        .filter(
            MultiEvalResult.round_id == round_id,
            MultiEvalResult.evaluatee_id == employee_id,
        )
        .all()
    )

    # Per-indicator anonymity: exclude indicators with response_count < 3
    multi_summary = [
        {
            "indicator": indicator_name,
            "avg_score": r.avg_score,
            "response_count": r.response_count,
        }
        for r, indicator_name in multi_results
        if r.response_count >= 3
    ]
    included_responses = sum(m["response_count"] for m in multi_summary)

    # Block-level anonymity: if included responses < 3, exclude multi entirely
    multi_included = bool(multi_summary) and included_responses >= 3
    if not multi_included:
        multi_summary = []
        included_responses = 0

    perf_results = (
        db.query(PerfEvalResult)
        .filter(
            PerfEvalResult.round_id == round_id,
            PerfEvalResult.emp_id == employee_id,
        )
        .all()
    )

    self_evals = (
        db.query(CompEvalSelf, CompIndicator.name)
        .join(CompIndicator, CompEvalSelf.indicator_id == CompIndicator.id)
        .filter(
            CompEvalSelf.round_id == round_id,
            CompEvalSelf.emp_id == employee_id,
        )
        .all()
    )

    boss_evals = (
        db.query(CompEvalBoss, CompIndicator.name)
        .join(CompIndicator, CompEvalBoss.indicator_id == CompIndicator.id)
        .filter(
            CompEvalBoss.round_id == round_id,
            CompEvalBoss.evaluatee_id == employee_id,
        )
        .all()
    )

    sars = (
        db.query(CompSarRecord)
        .filter(CompSarRecord.target_emp_id == employee_id)
        .all()
    )

    return {
        "round": {"year": rnd.year, "name": rnd.name},
        "employee": {
            "emp_id": emp.id,
            "name": emp.name_ko,
            "emp_no": emp.emp_no,
        },
        "header": {
            "perf_score": comp.perf_score,
            "comp_score": comp.comp_score,
            "multi_score": comp.multi_score,
            "total_score": comp.total_score,
            "final_grade": comp.final_grade,
            "dept_name": dept.name if dept else "",
            "job_rank": job_rank_name,
            "multi_response_count": included_responses,
            "multi_included": multi_included,
        },
        "perf_results": [
            {
                "score": p.score,
                "grade": p.grade,
                "comment": p.comment,
                "evaluator_id": p.evaluator_id,
            }
            for p in perf_results
        ],
        "self_evals": [
            {"indicator": ind, "score": s.score, "comment": s.comment}
            for s, ind in self_evals
        ],
        "boss_evals": [
            {
                "indicator": ind,
                "score": b.score,
                "comment": b.comment,
                "evaluator_id": b.evaluator_id,
            }
            for b, ind in boss_evals
        ],
        "multi_summary": multi_summary,
        "sars": [
            {
                "date": s.observed_date,
                "situation": s.situation,
                "action": s.action,
                "result": s.result,
                "observer_id": s.observer_id,
            }
            for s in sars
        ],
    }
