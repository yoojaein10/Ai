from datetime import date
from decimal import Decimal

import pytest

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
from app.services.ai_report.input_builder import build_input


def _seed_round(db, year=2026):
    rnd = EvalRound(year=year, name=f"{year}년 정기평가", status="IN_PROGRESS")
    db.add(rnd)
    db.flush()
    return rnd


def _seed_employee(db, name="홍길동"):
    dept = Department(name="개발팀", code=f"DEV_{name}")
    db.add(dept)
    db.flush()
    emp = Employee(
        emp_no=f"E{name}",
        name_ko=name,
        dept_id=dept.id,
        job_rank="과장",
        hire_date=date(2020, 1, 1),
    )
    db.add(emp)
    db.flush()
    return emp, dept


def test_build_input_raises_when_comprehensive_missing(db_session):
    rnd = _seed_round(db_session)
    emp, _ = _seed_employee(db_session)
    with pytest.raises(ValueError, match="comprehensive not calculated"):
        build_input(db_session, round_id=rnd.id, employee_id=emp.id)


def test_build_input_returns_quantitative_header(db_session):
    rnd = _seed_round(db_session)
    emp, dept = _seed_employee(db_session)
    db_session.add(EvalComprehensive(
        round_id=rnd.id, emp_id=emp.id,
        perf_score=Decimal("85"), comp_score=Decimal("80"), multi_score=Decimal("75"),
        total_score=Decimal("82"), original_grade="A", final_grade="A",
        is_adjusted=False,
    ))
    db_session.commit()

    result = build_input(db_session, round_id=rnd.id, employee_id=emp.id)
    assert result["header"]["total_score"] == Decimal("82")
    assert result["header"]["final_grade"] == "A"
    assert result["header"]["dept_name"] == "개발팀"
    assert result["header"]["job_rank"] == "과장"


def test_multi_excluded_when_response_count_lt_3(db_session):
    rnd = _seed_round(db_session)
    emp, _ = _seed_employee(db_session, name="이철수")
    db_session.add(EvalComprehensive(
        round_id=rnd.id, emp_id=emp.id, total_score=Decimal("70"),
        original_grade="B", final_grade="B", is_adjusted=False,
    ))
    ind = MultiEvalIndicator(round_id=rnd.id, name="협업", max_score=5)
    db_session.add(ind)
    db_session.flush()
    db_session.add(MultiEvalResult(
        round_id=rnd.id, evaluatee_id=emp.id, indicator_id=ind.id,
        avg_score=Decimal("4.0"), response_count=2,  # < 3
    ))
    db_session.commit()

    result = build_input(db_session, round_id=rnd.id, employee_id=emp.id)
    assert result["header"]["multi_included"] is False
    assert result["multi_summary"] == []


def test_multi_included_when_response_count_ge_3(db_session):
    rnd = _seed_round(db_session)
    emp, _ = _seed_employee(db_session, name="박민준")
    db_session.add(EvalComprehensive(
        round_id=rnd.id, emp_id=emp.id, total_score=Decimal("70"),
        original_grade="B", final_grade="B", is_adjusted=False,
    ))
    ind = MultiEvalIndicator(round_id=rnd.id, name="협업", max_score=5)
    db_session.add(ind)
    db_session.flush()
    db_session.add(MultiEvalResult(
        round_id=rnd.id, evaluatee_id=emp.id, indicator_id=ind.id,
        avg_score=Decimal("4.0"), response_count=4,
    ))
    db_session.commit()

    result = build_input(db_session, round_id=rnd.id, employee_id=emp.id)
    assert result["header"]["multi_included"] is True
    assert result["header"]["multi_response_count"] == 4
    assert len(result["multi_summary"]) == 1
    assert result["multi_summary"][0]["indicator"] == "협업"


def test_partial_indicator_lt_3_excluded(db_session):
    """전체 응답 수>=3이지만 일부 indicator만 <3이면 그 indicator만 제외."""
    rnd = _seed_round(db_session)
    emp, _ = _seed_employee(db_session, name="김유진")
    db_session.add(EvalComprehensive(
        round_id=rnd.id, emp_id=emp.id, total_score=Decimal("70"),
        original_grade="B", final_grade="B", is_adjusted=False,
    ))
    ind1 = MultiEvalIndicator(round_id=rnd.id, name="협업", max_score=5)
    ind2 = MultiEvalIndicator(round_id=rnd.id, name="리더십", max_score=5)
    db_session.add_all([ind1, ind2])
    db_session.flush()
    db_session.add_all([
        MultiEvalResult(round_id=rnd.id, evaluatee_id=emp.id, indicator_id=ind1.id,
                        avg_score=Decimal("4.0"), response_count=5),
        MultiEvalResult(round_id=rnd.id, evaluatee_id=emp.id, indicator_id=ind2.id,
                        avg_score=Decimal("3.0"), response_count=2),  # 제외 대상
    ])
    db_session.commit()

    result = build_input(db_session, round_id=rnd.id, employee_id=emp.id)
    indicators = [m["indicator"] for m in result["multi_summary"]]
    assert "협업" in indicators
    assert "리더십" not in indicators


def test_multi_response_count_excludes_suppressed_indicators(db_session):
    """multi_response_count는 visible indicators의 응답 수 합계만 카운트."""
    rnd = _seed_round(db_session)
    emp, *_ = _seed_employee(db_session)
    db_session.add(EvalComprehensive(
        round_id=rnd.id, emp_id=emp.id, total_score=Decimal("70"),
        original_grade="B", final_grade="B", is_adjusted=False,
    ))
    ind1 = MultiEvalIndicator(round_id=rnd.id, name="협업", max_score=5)
    ind2 = MultiEvalIndicator(round_id=rnd.id, name="리더십", max_score=5)
    db_session.add_all([ind1, ind2])
    db_session.flush()
    db_session.add_all([
        MultiEvalResult(round_id=rnd.id, evaluatee_id=emp.id, indicator_id=ind1.id,
                        avg_score=Decimal("4.0"), response_count=5),  # included
        MultiEvalResult(round_id=rnd.id, evaluatee_id=emp.id, indicator_id=ind2.id,
                        avg_score=Decimal("3.0"), response_count=2),  # suppressed
    ])
    db_session.commit()

    result = build_input(db_session, round_id=rnd.id, employee_id=emp.id)
    # Suppressed indicator's 2 responses must NOT count
    assert result["header"]["multi_response_count"] == 5
