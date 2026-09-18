from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.db.models import (
    Department,
    Employee,
    EvalComprehensive,
    EvalRound,
)


@pytest.fixture
def round_emp_comp(db_session, admin_user):
    rnd = EvalRound(year=2026, name="정기", status="IN_PROGRESS")
    db_session.add(rnd)
    db_session.flush()
    dept = Department(name="개발팀", code="DEV")
    db_session.add(dept)
    db_session.flush()
    emp = Employee(
        emp_no="E001", name_ko="홍길동",
        dept_id=dept.id, job_rank="과장", hire_date=date(2020, 1, 1),
    )
    db_session.add(emp)
    db_session.flush()
    db_session.add(EvalComprehensive(
        round_id=rnd.id, emp_id=emp.id, total_score=Decimal("82"),
        original_grade="A", final_grade="A", is_adjusted=False,
    ))
    db_session.commit()
    return rnd, emp


def _fake_response():
    return {
        "strengths": "성실함",
        "improvements": "발표 스킬",
        "coaching": "주1 발표",
        "interview_guide": "최근 도전 질문",
    }


def test_post_generate_returns_summary(client, auth_headers, round_emp_comp):
    rnd, _ = round_emp_comp
    with patch("app.services.ai_eval_report_service._call_gemini", return_value=_fake_response()):
        resp = client.post(
            "/api/v1/eval/ai-reports/generate",
            json={"round_id": rnd.id},
            headers=auth_headers,
        )
    assert resp.status_code == 202
    body = resp.json()
    assert body["round_id"] == rnd.id
    assert body["total"] == 1
    assert body["success"] == 1


def test_post_generate_400_when_no_comprehensive(client, auth_headers, db_session):
    rnd = EvalRound(year=2026, name="빈", status="IN_PROGRESS")
    db_session.add(rnd)
    db_session.commit()
    resp = client.post(
        "/api/v1/eval/ai-reports/generate",
        json={"round_id": rnd.id},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_post_generate_403_for_non_admin(client, db_session):
    from app.core.security import create_access_token
    from app.db.models import Role, User, UserRole
    role = Role(code="EMPLOYEE", name="직원")
    db_session.add(role)
    db_session.flush()
    user = User(login_id="emp", password_hash="x", is_active=True)
    db_session.add(user)
    db_session.flush()
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    db_session.commit()
    token = create_access_token(str(user.id), extra={"roles": ["EMPLOYEE"]})

    resp = client.post(
        "/api/v1/eval/ai-reports/generate",
        json={"round_id": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_get_list_returns_left_joined_rows(client, auth_headers, round_emp_comp):
    rnd, _ = round_emp_comp
    resp = client.get(
        f"/api/v1/eval/ai-reports?round_id={rnd.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["status"] is None  # 미생성


def test_post_generate_individual(client, auth_headers, round_emp_comp):
    rnd, emp = round_emp_comp
    with patch("app.services.ai_eval_report_service._call_gemini", return_value=_fake_response()):
        resp = client.post(
            f"/api/v1/eval/ai-reports/generate/{emp.id}",
            json={"round_id": rnd.id},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "SUCCESS"
    assert body["version"] == 1


def test_get_history_returns_versions(client, auth_headers, round_emp_comp):
    rnd, emp = round_emp_comp
    with patch("app.services.ai_eval_report_service._call_gemini", return_value=_fake_response()):
        client.post(f"/api/v1/eval/ai-reports/generate/{emp.id}",
                    json={"round_id": rnd.id}, headers=auth_headers)
        client.post(f"/api/v1/eval/ai-reports/generate/{emp.id}",
                    json={"round_id": rnd.id}, headers=auth_headers)
    resp = client.get(
        f"/api/v1/eval/ai-reports/employees/{emp.id}/history?round_id={rnd.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    versions = resp.json()
    assert len(versions) == 2
    assert versions[0]["version"] == 2
    assert versions[0]["is_latest"] is True
    assert versions[1]["is_latest"] is False
