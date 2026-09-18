from datetime import date

import pytest

from app.core.security import create_access_token, hash_password
from app.db.models import EvalApprover, Role, User, UserRole


def _create_round(client, auth_headers) -> int:
    resp = client.post(
        "/api/v1/eval/rounds",
        json={"year": 2026, "name": "2026"},
        headers=auth_headers,
    )
    return resp.json()["id"]


def _create_indicator(client, auth_headers, code: str = "C100") -> int:
    resp = client.post(
        "/api/v1/eval/comp/indicators",
        json={"year": 2026, "code": code, "name": code, "behaviors": []},
        headers=auth_headers,
    )
    return resp.json()["id"]


@pytest.fixture
def employee_user(db_session):
    from app.db.models import Employee

    role = db_session.query(Role).filter(Role.code == "EMPLOYEE").first()
    if role is None:
        role = Role(code="EMPLOYEE", name="사원")
        db_session.add(role)
        db_session.flush()
    emp = Employee(emp_no="C0000001", name_ko="피평가자", hire_date=date(2021, 1, 1))
    db_session.add(emp)
    db_session.flush()
    user = User(
        login_id="comp_emp",
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


@pytest.fixture
def employee_headers(employee_user):
    token = create_access_token(str(employee_user.id), extra={"roles": ["EMPLOYEE"]})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def boss_user(db_session):
    from app.db.models import Employee

    role = db_session.query(Role).filter(Role.code == "DEPT_HEAD").first()
    if role is None:
        role = Role(code="DEPT_HEAD", name="부서장")
        db_session.add(role)
        db_session.flush()
    emp = Employee(emp_no="C0000002", name_ko="상사", hire_date=date(2021, 1, 1))
    db_session.add(emp)
    db_session.flush()
    user = User(
        login_id="comp_boss",
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


@pytest.fixture
def boss_headers(boss_user):
    token = create_access_token(str(boss_user.id), extra={"roles": ["DEPT_HEAD"]})
    return {"Authorization": f"Bearer {token}"}


def _map_comp_approver(db_session, round_id, evaluatee_id, evaluator_id):
    db_session.add(
        EvalApprover(
            round_id=round_id,
            evaluatee_id=evaluatee_id,
            evaluator_id=evaluator_id,
            eval_type="COMP",
        )
    )
    db_session.commit()


def test_self_eval_submit(client, auth_headers, employee_user, employee_headers):
    round_id = _create_round(client, auth_headers)
    ind_id = _create_indicator(client, auth_headers, "C-S1")

    resp = client.post(
        "/api/v1/eval/comp/self",
        json={
            "round_id": round_id,
            "items": [{"indicator_id": ind_id, "score": 4, "comment": "노력함"}],
        },
        headers=employee_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert len(data) == 1
    assert data[0]["score"] == 4
    assert data[0]["emp_id"] == employee_user.employee_id


def test_self_eval_score_out_of_range(client, auth_headers, employee_headers):
    round_id = _create_round(client, auth_headers)
    ind_id = _create_indicator(client, auth_headers, "C-S2")

    resp = client.post(
        "/api/v1/eval/comp/self",
        json={
            "round_id": round_id,
            "items": [{"indicator_id": ind_id, "score": 6}],
        },
        headers=employee_headers,
    )
    assert resp.status_code == 422


def test_self_eval_score_zero_invalid(client, auth_headers, employee_headers):
    round_id = _create_round(client, auth_headers)
    ind_id = _create_indicator(client, auth_headers, "C-S3")

    resp = client.post(
        "/api/v1/eval/comp/self",
        json={
            "round_id": round_id,
            "items": [{"indicator_id": ind_id, "score": 0}],
        },
        headers=employee_headers,
    )
    assert resp.status_code == 422


def test_self_eval_upsert(client, auth_headers, employee_headers):
    round_id = _create_round(client, auth_headers)
    ind_id = _create_indicator(client, auth_headers, "C-S4")

    client.post(
        "/api/v1/eval/comp/self",
        json={"round_id": round_id, "items": [{"indicator_id": ind_id, "score": 3}]},
        headers=employee_headers,
    )
    resp = client.post(
        "/api/v1/eval/comp/self",
        json={"round_id": round_id, "items": [{"indicator_id": ind_id, "score": 5}]},
        headers=employee_headers,
    )
    assert resp.status_code == 201
    listing = client.get(
        f"/api/v1/eval/comp/my-eval?round_id={round_id}", headers=employee_headers
    )
    rows = [r for r in listing.json() if r["indicator_id"] == ind_id]
    assert len(rows) == 1
    assert rows[0]["score"] == 5


def test_boss_eval_unmapped_forbidden(
    client, auth_headers, employee_user, boss_headers
):
    round_id = _create_round(client, auth_headers)
    ind_id = _create_indicator(client, auth_headers, "C-B1")

    resp = client.post(
        "/api/v1/eval/comp/boss",
        json={
            "evaluatee_id": employee_user.employee_id,
            "round_id": round_id,
            "items": [{"indicator_id": ind_id, "score": 4}],
        },
        headers=boss_headers,
    )
    assert resp.status_code == 403


def test_boss_eval_mapped_ok(
    client, auth_headers, employee_user, boss_user, boss_headers, db_session
):
    round_id = _create_round(client, auth_headers)
    ind_id = _create_indicator(client, auth_headers, "C-B2")
    _map_comp_approver(
        db_session, round_id, employee_user.employee_id, boss_user.employee_id
    )

    resp = client.post(
        "/api/v1/eval/comp/boss",
        json={
            "evaluatee_id": employee_user.employee_id,
            "round_id": round_id,
            "items": [{"indicator_id": ind_id, "score": 5, "comment": "탁월"}],
        },
        headers=boss_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data[0]["evaluator_id"] == boss_user.employee_id
    assert data[0]["score"] == 5
