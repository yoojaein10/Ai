from datetime import date

import pytest

from app.core.security import create_access_token, hash_password
from app.db.models import Employee, EvalApprover, Role, User, UserRole


def _create_round(client, auth_headers) -> int:
    resp = client.post(
        "/api/v1/eval/rounds",
        json={"year": 2026, "name": "2026"},
        headers=auth_headers,
    )
    return resp.json()["id"]


def _create_indicator(client, auth_headers, round_id: int, name: str) -> int:
    resp = client.post(
        "/api/v1/eval/multi/indicators",
        json={"round_id": round_id, "name": name, "max_score": 5},
        headers=auth_headers,
    )
    return resp.json()["id"]


def _make_user(db_session, login_id: str, emp_no: str) -> User:
    role = db_session.query(Role).filter(Role.code == "EMPLOYEE").first()
    if role is None:
        role = Role(code="EMPLOYEE", name="사원")
        db_session.add(role)
        db_session.flush()
    emp = Employee(emp_no=emp_no, name_ko=login_id, hire_date=date(2021, 1, 1))
    db_session.add(emp)
    db_session.flush()
    user = User(
        login_id=login_id,
        password_hash=hash_password("password123"),
        is_active=True,
        employee_id=emp.id,
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    db_session.commit()
    db_session.refresh(user)
    return user


def _headers(user: User, role: str = "EMPLOYEE") -> dict:
    token = create_access_token(str(user.id), extra={"roles": [role]})
    return {"Authorization": f"Bearer {token}"}


def _map_and_submit(
    client, db_session, round_id, ind_id, evaluatee, rater, score
):
    db_session.add(
        EvalApprover(
            round_id=round_id,
            evaluatee_id=evaluatee.employee_id,
            evaluator_id=rater.employee_id,
            eval_type="MULTI",
            rater_type="PEER",
        )
    )
    db_session.commit()
    resp = client.post(
        "/api/v1/eval/multi/response",
        json={
            "round_id": round_id,
            "evaluatee_id": evaluatee.employee_id,
            "rater_type": "PEER",
            "items": [{"indicator_id": ind_id, "score": str(score)}],
        },
        headers=_headers(rater),
    )
    assert resp.status_code == 201, resp.text


@pytest.fixture
def evaluatee(db_session):
    return _make_user(db_session, "result_tee", "R0000001")


def test_result_insufficient_when_under_3_responses(
    client, auth_headers, evaluatee, db_session
):
    round_id = _create_round(client, auth_headers)
    ind_id = _create_indicator(client, auth_headers, round_id, "협업")

    rater_a = _make_user(db_session, "rater_a", "RA000001")
    rater_b = _make_user(db_session, "rater_b", "RB000001")
    _map_and_submit(client, db_session, round_id, ind_id, evaluatee, rater_a, 4)
    _map_and_submit(client, db_session, round_id, ind_id, evaluatee, rater_b, 5)

    resp = client.get(
        f"/api/v1/eval/multi/results/{evaluatee.employee_id}?round_id={round_id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["insufficient"] is True
    assert body["indicators"] == []


def test_result_returns_average_when_3_or_more(
    client, auth_headers, evaluatee, db_session
):
    round_id = _create_round(client, auth_headers)
    ind_id = _create_indicator(client, auth_headers, round_id, "리더십")

    raters = [
        _make_user(db_session, f"r3_{i}", f"R3{i:06d}") for i in range(3)
    ]
    for r, score in zip(raters, [3, 4, 5]):
        _map_and_submit(client, db_session, round_id, ind_id, evaluatee, r, score)

    resp = client.get(
        f"/api/v1/eval/multi/results/{evaluatee.employee_id}?round_id={round_id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["insufficient"] is False
    assert len(body["indicators"]) == 1
    ind = body["indicators"][0]
    assert ind["response_count"] == 3
    assert float(ind["avg_score"]) == 4.0


def test_other_emp_cannot_view_my_result(
    client, evaluatee, db_session
):
    other = _make_user(db_session, "intruder", "IN000001")
    other_headers = _headers(other)
    resp = client.get(
        f"/api/v1/eval/multi/results/{evaluatee.employee_id}?round_id=1",
        headers=other_headers,
    )
    assert resp.status_code == 403


def test_status_admin_only(client, db_session):
    other = _make_user(db_session, "non_admin_status", "ST000001")
    resp = client.get(
        "/api/v1/eval/multi/status?round_id=1", headers=_headers(other)
    )
    assert resp.status_code == 403


def test_status_returns_submission_rate(
    client, auth_headers, evaluatee, db_session
):
    round_id = _create_round(client, auth_headers)
    ind_id = _create_indicator(client, auth_headers, round_id, "성장")
    raters = [
        _make_user(db_session, f"st_{i}", f"ST1{i:05d}") for i in range(2)
    ]
    # 두 명만 매핑, 한 명만 제출
    for r in raters:
        db_session.add(
            EvalApprover(
                round_id=round_id,
                evaluatee_id=evaluatee.employee_id,
                evaluator_id=r.employee_id,
                eval_type="MULTI",
                rater_type="PEER",
            )
        )
    db_session.commit()

    client.post(
        "/api/v1/eval/multi/response",
        json={
            "round_id": round_id,
            "evaluatee_id": evaluatee.employee_id,
            "rater_type": "PEER",
            "items": [{"indicator_id": ind_id, "score": "4"}],
        },
        headers=_headers(raters[0]),
    )

    resp = client.get(
        f"/api/v1/eval/multi/status?round_id={round_id}", headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["expected"] == 2
    assert body["submitted"] == 1
    assert body["submission_rate"] == 0.5
