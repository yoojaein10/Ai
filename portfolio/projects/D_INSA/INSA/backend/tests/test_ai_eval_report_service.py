from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.db.models import (
    Department,
    Employee,
    EvalAiReport,
    EvalComprehensive,
    EvalRound,
    Notification,
    Role,
    User,
    UserRole,
)
from app.services.ai_eval_report_service import (
    BatchInProgressError,
    generate_one_report,
    list_reports_for_round,
)
from app.services.ai_report.gemini_client import GeminiError


@pytest.fixture
def hr_user(db_session):
    role = Role(code="HR_ADMIN", name="인사")
    db_session.add(role)
    db_session.flush()
    user = User(login_id="hr1", password_hash="x", is_active=True)
    db_session.add(user)
    db_session.flush()
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    db_session.commit()
    return user


@pytest.fixture
def round_with_comp(db_session):
    rnd = EvalRound(year=2026, name="정기", status="IN_PROGRESS")
    db_session.add(rnd)
    db_session.flush()
    dept = Department(name="개발팀", code="DEV")
    db_session.add(dept)
    db_session.flush()
    emp = Employee(
        emp_no="E001",
        name_ko="홍길동",
        dept_id=dept.id,
        job_rank="과장",
        hire_date=date(2020, 1, 1),
    )
    db_session.add(emp)
    db_session.flush()
    db_session.add(EvalComprehensive(
        round_id=rnd.id, emp_id=emp.id,
        perf_score=Decimal("85"), comp_score=Decimal("80"), multi_score=Decimal("75"),
        total_score=Decimal("82"), original_grade="A", final_grade="A", is_adjusted=False,
    ))
    db_session.commit()
    return rnd, emp


def _fake_gemini_response():
    return {
        "strengths": "성실함과 책임감",
        "improvements": "발표 스킬",
        "coaching": "주 1회 발표 연습",
        "interview_guide": "최근 도전 사례 질문",
    }


def test_generate_one_report_happy_path(db_session, hr_user, round_with_comp):
    rnd, emp = round_with_comp
    with patch("app.services.ai_eval_report_service._call_gemini", return_value=_fake_gemini_response()):
        report = generate_one_report(db_session, rnd.id, emp.id, generated_by=hr_user.id)
    assert report.status == "SUCCESS"
    assert report.version == 1
    assert report.is_latest is True
    assert report.content_strengths == "성실함과 책임감"
    assert report.total_score == Decimal("82")
    assert report.final_grade == "A"


def test_regenerate_creates_new_version_and_demotes_prev(db_session, hr_user, round_with_comp):
    rnd, emp = round_with_comp
    with patch("app.services.ai_eval_report_service._call_gemini", return_value=_fake_gemini_response()):
        v1 = generate_one_report(db_session, rnd.id, emp.id, generated_by=hr_user.id)
        v2 = generate_one_report(db_session, rnd.id, emp.id, generated_by=hr_user.id)

    db_session.refresh(v1)
    assert v1.is_latest is False
    assert v2.version == 2
    assert v2.is_latest is True


def test_gemini_error_persists_failed_row(db_session, hr_user, round_with_comp):
    rnd, emp = round_with_comp
    with patch(
        "app.services.ai_eval_report_service._call_gemini",
        side_effect=GeminiError("503: service unavailable"),
    ):
        report = generate_one_report(db_session, rnd.id, emp.id, generated_by=hr_user.id)
    assert report.status == "FAILED"
    assert "503" in report.error_message
    assert report.content_strengths is None


def test_comprehensive_missing_raises_value_error(db_session, hr_user):
    rnd = EvalRound(year=2026, name="정기", status="IN_PROGRESS")
    db_session.add(rnd)
    db_session.flush()
    emp = Employee(emp_no="E999", name_ko="유령", hire_date=date(2020, 1, 1))
    db_session.add(emp)
    db_session.commit()
    with pytest.raises(ValueError, match="comprehensive"):
        generate_one_report(db_session, rnd.id, emp.id, generated_by=hr_user.id)


def test_list_reports_left_joins_comprehensive(db_session, hr_user, round_with_comp):
    """리포트 미생성 직원도 응답에 포함."""
    rnd, emp = round_with_comp
    rows = list_reports_for_round(db_session, rnd.id)
    assert len(rows) == 1
    assert rows[0]["employee_id"] == emp.id
    assert rows[0]["status"] is None  # 미생성

    with patch("app.services.ai_eval_report_service._call_gemini", return_value=_fake_gemini_response()):
        generate_one_report(db_session, rnd.id, emp.id, generated_by=hr_user.id)
    rows = list_reports_for_round(db_session, rnd.id)
    assert rows[0]["status"] == "SUCCESS"
    assert rows[0]["version"] == 1


def test_generate_batch_processes_all_employees(db_session, hr_user, round_with_comp):
    rnd, emp = round_with_comp
    # 두 번째 직원 추가
    emp2 = Employee(
        emp_no="E002", name_ko="김철수",
        dept_id=emp.dept_id, job_rank=emp.job_rank, hire_date=date(2020, 1, 1),
    )
    db_session.add(emp2)
    db_session.flush()
    db_session.add(EvalComprehensive(
        round_id=rnd.id, emp_id=emp2.id,
        total_score=Decimal("70"), original_grade="B", final_grade="B", is_adjusted=False,
    ))
    db_session.commit()

    from app.services.ai_eval_report_service import generate_batch

    with patch("app.services.ai_eval_report_service._call_gemini", return_value=_fake_gemini_response()):
        summary = generate_batch(db_session, rnd.id, generated_by=hr_user.id)
    assert summary["total"] == 2
    assert summary["success"] == 2
    assert summary["failed"] == 0


def test_generate_batch_records_failures(db_session, hr_user, round_with_comp):
    rnd, emp = round_with_comp
    from app.services.ai_eval_report_service import generate_batch

    with patch(
        "app.services.ai_eval_report_service._call_gemini",
        side_effect=GeminiError("400: bad request"),
    ):
        summary = generate_batch(db_session, rnd.id, generated_by=hr_user.id)
    assert summary["failed"] == 1
    assert summary["success"] == 0


def test_generate_batch_creates_notification(db_session, hr_user, round_with_comp):
    rnd, _ = round_with_comp
    from app.services.ai_eval_report_service import generate_batch

    with patch("app.services.ai_eval_report_service._call_gemini", return_value=_fake_gemini_response()):
        generate_batch(db_session, rnd.id, generated_by=hr_user.id)
    notif = db_session.query(Notification).filter(Notification.user_id == hr_user.id).first()
    assert notif is not None
    assert "AI 리포트 생성" in notif.message


def test_generate_batch_409_when_in_progress(db_session, hr_user, round_with_comp):
    rnd, _ = round_with_comp
    from app.services.ai_eval_report_service import _batch_locks, generate_batch

    _batch_locks.add(rnd.id)
    try:
        with pytest.raises(BatchInProgressError):
            generate_batch(db_session, rnd.id, generated_by=hr_user.id)
    finally:
        _batch_locks.discard(rnd.id)


def test_generate_batch_400_when_no_comprehensive(db_session, hr_user):
    from app.services.ai_eval_report_service import generate_batch

    rnd = EvalRound(year=2026, name="빈회차", status="IN_PROGRESS")
    db_session.add(rnd)
    db_session.commit()
    with pytest.raises(ValueError, match="no comprehensive"):
        generate_batch(db_session, rnd.id, generated_by=hr_user.id)
