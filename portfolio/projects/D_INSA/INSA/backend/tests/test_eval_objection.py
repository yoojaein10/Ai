from datetime import date

import pytest

from app.core.security import create_access_token, hash_password
from app.db.models import Employee, EvalRound, Role, User, UserRole


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


def _seed_round(db_session, year: int = 2026) -> EvalRound:
    r = EvalRound(year=year, name=f"{year}-종합", status="IN_PROGRESS")
    db_session.add(r)
    db_session.commit()
    db_session.refresh(r)
    return r


@pytest.fixture
def employee(db_session):
    return _make_user(db_session, "obj_user", "OB000001")


def test_create_objection_requires_reason(client, employee, db_session):
    r = _seed_round(db_session)
    resp = client.post(
        "/api/v1/eval/objections",
        json={"round_id": r.id, "reason": ""},
        headers=_headers(employee),
    )
    assert resp.status_code == 422


def test_create_objection_pending_status(client, employee, db_session):
    r = _seed_round(db_session)
    resp = client.post(
        "/api/v1/eval/objections",
        json={"round_id": r.id, "reason": "평가 결과에 동의하지 않음"},
        headers=_headers(employee),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "PENDING"
    assert body["emp_id"] == employee.employee_id


def test_employee_only_sees_own_objection(client, employee, db_session):
    r = _seed_round(db_session)
    other = _make_user(db_session, "other_obj", "OO000001")
    client.post(
        "/api/v1/eval/objections",
        json={"round_id": r.id, "reason": "내 이의"},
        headers=_headers(employee),
    )
    client.post(
        "/api/v1/eval/objections",
        json={"round_id": r.id, "reason": "다른 사람의 이의"},
        headers=_headers(other),
    )
    resp = client.get(
        f"/api/v1/eval/objections?round_id={r.id}", headers=_headers(employee)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["emp_id"] == employee.employee_id


def test_admin_sees_all_objections(client, auth_headers, employee, db_session):
    r = _seed_round(db_session)
    other = _make_user(db_session, "other_obj_a", "OA000001")
    client.post(
        "/api/v1/eval/objections",
        json={"round_id": r.id, "reason": "A"},
        headers=_headers(employee),
    )
    client.post(
        "/api/v1/eval/objections",
        json={"round_id": r.id, "reason": "B"},
        headers=_headers(other),
    )
    resp = client.get(f"/api/v1/eval/objections?round_id={r.id}", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_review_transitions_status_to_decision(
    client, auth_headers, employee, db_session
):
    r = _seed_round(db_session)
    create = client.post(
        "/api/v1/eval/objections",
        json={"round_id": r.id, "reason": "재심의 요청"},
        headers=_headers(employee),
    )
    obj_id = create.json()["id"]

    resp = client.put(
        f"/api/v1/eval/objections/{obj_id}/review",
        json={"decision": "ACCEPTED", "comment": "타당함"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    review = resp.json()
    assert review["decision"] == "ACCEPTED"

    list_resp = client.get(
        f"/api/v1/eval/objections?round_id={r.id}", headers=auth_headers
    )
    statuses = [o["status"] for o in list_resp.json()]
    assert "ACCEPTED" in statuses


def test_cannot_review_already_finalized(
    client, auth_headers, employee, db_session
):
    r = _seed_round(db_session)
    obj_id = client.post(
        "/api/v1/eval/objections",
        json={"round_id": r.id, "reason": "x"},
        headers=_headers(employee),
    ).json()["id"]
    client.put(
        f"/api/v1/eval/objections/{obj_id}/review",
        json={"decision": "REJECTED"},
        headers=auth_headers,
    )
    # 두 번째 review 시도는 400
    resp = client.put(
        f"/api/v1/eval/objections/{obj_id}/review",
        json={"decision": "ACCEPTED"},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_employee_cannot_review(client, employee, db_session):
    r = _seed_round(db_session)
    obj_id = client.post(
        "/api/v1/eval/objections",
        json={"round_id": r.id, "reason": "x"},
        headers=_headers(employee),
    ).json()["id"]
    resp = client.put(
        f"/api/v1/eval/objections/{obj_id}/review",
        json={"decision": "ACCEPTED"},
        headers=_headers(employee),
    )
    assert resp.status_code == 403
