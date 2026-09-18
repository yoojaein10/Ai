from datetime import date

import pytest

from app.core.security import create_access_token, hash_password
from app.db.models import (
    Employee,
    EvalApprover,
    MultiEvalResponse,
    MultiEvalResponseLog,
    Role,
    User,
    UserRole,
)


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
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _make_user(db_session, login_id: str, emp_no: str, role_code: str) -> User:
    role = db_session.query(Role).filter(Role.code == role_code).first()
    if role is None:
        role = Role(code=role_code, name=role_code)
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


def _headers(user: User, role: str) -> dict:
    token = create_access_token(str(user.id), extra={"roles": [role]})
    return {"Authorization": f"Bearer {token}"}


def _map(db_session, round_id, evaluatee_id, evaluator_id, rater_type):
    db_session.add(
        EvalApprover(
            round_id=round_id,
            evaluatee_id=evaluatee_id,
            evaluator_id=evaluator_id,
            eval_type="MULTI",
            rater_type=rater_type,
        )
    )
    db_session.commit()


@pytest.fixture
def evaluatee(db_session):
    return _make_user(db_session, "tee_user", "M0000001", "EMPLOYEE")


@pytest.fixture
def peer_users(db_session):
    return [
        _make_user(db_session, f"peer{i}", f"P000000{i}", "EMPLOYEE")
        for i in range(1, 5)
    ]


def test_indicator_admin_only(client, auth_headers, evaluatee, peer_users):
    round_id = _create_round(client, auth_headers)
    not_admin_headers = _headers(peer_users[0], "EMPLOYEE")
    resp = client.post(
        "/api/v1/eval/multi/indicators",
        json={"round_id": round_id, "name": "협업", "max_score": 5},
        headers=not_admin_headers,
    )
    assert resp.status_code == 403


def test_submit_unmapped_forbidden(
    client, auth_headers, evaluatee, peer_users, db_session
):
    round_id = _create_round(client, auth_headers)
    ind_id = _create_indicator(client, auth_headers, round_id, "협업")

    resp = client.post(
        "/api/v1/eval/multi/response",
        json={
            "round_id": round_id,
            "evaluatee_id": evaluatee.employee_id,
            "rater_type": "PEER",
            "items": [{"indicator_id": ind_id, "score": "4.0"}],
        },
        headers=_headers(peer_users[0], "EMPLOYEE"),
    )
    assert resp.status_code == 403


def test_submit_persists_only_anonymous_data(
    client, auth_headers, evaluatee, peer_users, db_session
):
    round_id = _create_round(client, auth_headers)
    ind_id = _create_indicator(client, auth_headers, round_id, "리더십")
    _map(
        db_session,
        round_id,
        evaluatee.employee_id,
        peer_users[0].employee_id,
        "PEER",
    )

    resp = client.post(
        "/api/v1/eval/multi/response",
        json={
            "round_id": round_id,
            "evaluatee_id": evaluatee.employee_id,
            "rater_type": "PEER",
            "items": [{"indicator_id": ind_id, "score": "4.5", "comment": "ok"}],
        },
        headers=_headers(peer_users[0], "EMPLOYEE"),
    )
    assert resp.status_code == 201
    assert resp.json()["inserted"] == 1

    # Response 테이블에는 평가자 식별 컬럼이 아예 없어야 한다.
    rows = db_session.query(MultiEvalResponse).all()
    assert len(rows) == 1
    row_attrs = {col.name for col in rows[0].__table__.columns}
    assert "evaluator_id" not in row_attrs

    # Log 테이블에는 evaluator_id 가 있지만 indicator/score 는 없어야 한다.
    log = db_session.query(MultiEvalResponseLog).first()
    assert log is not None
    assert log.evaluator_id == peer_users[0].employee_id
    log_attrs = {col.name for col in log.__table__.columns}
    assert "score" not in log_attrs
    assert "indicator_id" not in log_attrs


def test_duplicate_submit_blocked(
    client, auth_headers, evaluatee, peer_users, db_session
):
    round_id = _create_round(client, auth_headers)
    ind_id = _create_indicator(client, auth_headers, round_id, "소통")
    _map(db_session, round_id, evaluatee.employee_id, peer_users[0].employee_id, "PEER")

    payload = {
        "round_id": round_id,
        "evaluatee_id": evaluatee.employee_id,
        "rater_type": "PEER",
        "items": [{"indicator_id": ind_id, "score": "3"}],
    }
    headers = _headers(peer_users[0], "EMPLOYEE")
    first = client.post("/api/v1/eval/multi/response", json=payload, headers=headers)
    assert first.status_code == 201
    again = client.post("/api/v1/eval/multi/response", json=payload, headers=headers)
    assert again.status_code == 400


def test_score_out_of_range(
    client, auth_headers, evaluatee, peer_users, db_session
):
    round_id = _create_round(client, auth_headers)
    ind_id = _create_indicator(client, auth_headers, round_id, "전문성")
    _map(db_session, round_id, evaluatee.employee_id, peer_users[0].employee_id, "PEER")

    resp = client.post(
        "/api/v1/eval/multi/response",
        json={
            "round_id": round_id,
            "evaluatee_id": evaluatee.employee_id,
            "rater_type": "PEER",
            "items": [{"indicator_id": ind_id, "score": "9.9"}],
        },
        headers=_headers(peer_users[0], "EMPLOYEE"),
    )
    assert resp.status_code == 400


def test_my_targets_lists_mapped_evaluatees(
    client, auth_headers, evaluatee, peer_users, db_session
):
    round_id = _create_round(client, auth_headers)
    rater = peer_users[0]
    _map(db_session, round_id, evaluatee.employee_id, rater.employee_id, "PEER")

    resp = client.get(
        f"/api/v1/eval/multi/my-targets?round_id={round_id}",
        headers=_headers(rater, "EMPLOYEE"),
    )
    assert resp.status_code == 200
    rows = resp.json()
    assert any(r["evaluatee_id"] == evaluatee.employee_id for r in rows)
    assert all(r["submitted"] is False for r in rows)
