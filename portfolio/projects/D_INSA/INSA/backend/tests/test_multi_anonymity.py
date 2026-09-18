"""익명성 보장 검증 — 컬럼/엔드포인트 introspection."""
from app.db.models import (
    MultiEvalResponse,
    MultiEvalResponseLog,
)


def test_response_table_has_no_evaluator_id_column():
    cols = {c.name for c in MultiEvalResponse.__table__.columns}
    forbidden = {"evaluator_id", "rater_id", "submitter_id", "user_id"}
    assert not (cols & forbidden), (
        f"insa_multi_eval_response 에 평가자 추적 컬럼이 있어 익명성 위배: "
        f"{cols & forbidden}"
    )


def test_response_log_table_has_no_score_or_indicator():
    cols = {c.name for c in MultiEvalResponseLog.__table__.columns}
    forbidden = {"score", "indicator_id", "rater_type", "comment"}
    assert not (cols & forbidden), (
        f"insa_multi_eval_response_log 에 점수/지표 컬럼이 있어 역추적 가능: "
        f"{cols & forbidden}"
    )


def test_response_and_log_have_no_common_join_key():
    """response 와 log 사이엔 ID 외 공통 키가 없어야 함 (id 는 PK 라 자연 무관)."""
    response_cols = {c.name for c in MultiEvalResponse.__table__.columns}
    log_cols = {c.name for c in MultiEvalResponseLog.__table__.columns}
    response_cols.discard("id")
    log_cols.discard("id")

    common = response_cols & log_cols
    # 둘 다 round_id, evaluatee_id, created_at/submitted_at 등 일부 공통 차원이 있을 수 있으나
    # 핵심은 evaluator_id/평가자 식별 키가 응답 측에 없어야 한다는 것.
    # 따라서 evaluator_id 가 공통키에 포함되지 않음을 확인.
    assert "evaluator_id" not in common


def test_no_individual_score_query_endpoint():
    from app.api.v1.router import api_router

    paths = {route.path for route in api_router.routes}
    forbidden_paths = {
        "/eval/multi/responses",
        "/eval/multi/response/{response_id}",
        "/eval/multi/responses/{response_id}",
    }
    leaked = paths & forbidden_paths
    assert not leaked, f"개별 응답 조회 엔드포인트가 노출됨: {leaked}"


def test_service_does_not_persist_evaluator_id_on_response():
    """grep 대용 — 서비스 코드에 MultiEvalResponse(..., evaluator_id=...) 패턴 없음."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "app" / "services" / "multi_response.py"
    content = src.read_text(encoding="utf-8")
    # MultiEvalResponse 생성자에 evaluator_id 키워드가 들어가면 안 된다.
    assert "evaluator_id=" not in content.split("MultiEvalResponse(")[1].split(")")[0]


def test_ai_report_input_excludes_evaluator_id():
    """입력 빌드 결과에 어떤 evaluator_id 키도 들어가지 않음 (다면 익명성).

    Static check: input_builder 소스에 multi 관련 evaluator_id 참조 없음.
    """
    from app.services.ai_report.input_builder import build_input  # noqa: F401

    src = open("app/services/ai_report/input_builder.py", encoding="utf-8").read()
    assert "MultiEvalResponseLog" not in src, "log 테이블은 ID만 보유 — 입력에 포함 금지"
    # multi_summary 섹션과 그 다음 perf_results 섹션 사이에 'evaluator_id' 가 없어야 함
    multi_section = src.split("multi_summary")[1].split("perf_results")[0]
    assert "evaluator_id" not in multi_section


def test_ai_report_excludes_indicator_with_response_count_lt_3(db_session):
    """response_count<3인 indicator는 build_input 결과의 multi_summary에서 제외."""
    from datetime import date
    from decimal import Decimal
    from app.db.models import (
        Department, Employee, EvalComprehensive, EvalRound,
        MultiEvalIndicator, MultiEvalResult,
    )
    from app.services.ai_report.input_builder import build_input

    rnd = EvalRound(year=2026, name="정기", status="IN_PROGRESS")
    db_session.add(rnd)
    db_session.flush()
    dept = Department(name="DEV", code="D")
    db_session.add(dept)
    db_session.flush()
    emp = Employee(
        emp_no="E1", name_ko="A",
        dept_id=dept.id, job_rank="대리", hire_date=date(2020, 1, 1),
    )
    db_session.add(emp)
    db_session.flush()
    db_session.add(EvalComprehensive(
        round_id=rnd.id, emp_id=emp.id, total_score=Decimal("70"),
        original_grade="B", final_grade="B", is_adjusted=False,
    ))
    ind = MultiEvalIndicator(round_id=rnd.id, name="협업", max_score=5)
    db_session.add(ind)
    db_session.flush()
    db_session.add(MultiEvalResult(
        round_id=rnd.id, evaluatee_id=emp.id, indicator_id=ind.id,
        avg_score=Decimal("4"), response_count=2,
    ))
    db_session.commit()

    result = build_input(db_session, round_id=rnd.id, employee_id=emp.id)
    assert result["multi_summary"] == []
    assert result["header"]["multi_included"] is False
