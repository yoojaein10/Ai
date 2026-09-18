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


def _create_employee(client, auth_headers, emp_no: str, name: str) -> int:
    resp = client.post(
        "/api/v1/employees",
        json={"emp_no": emp_no, "name_ko": name, "hire_date": "2021-01-01"},
        headers=auth_headers,
    )
    return resp.json()["id"]


@pytest.fixture
def evaluator_user(db_session):
    from app.db.models import Employee

    role = db_session.query(Role).filter(Role.code == "DEPT_HEAD").first()
    if role is None:
        role = Role(code="DEPT_HEAD", name="부서장")
        db_session.add(role)
        db_session.flush()

    emp = Employee(emp_no="91000001", name_ko="평가자R", hire_date=date(2021, 1, 1))
    db_session.add(emp)
    db_session.flush()

    user = User(
        login_id="evalR",
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
def evaluator_headers(evaluator_user):
    token = create_access_token(str(evaluator_user.id), extra={"roles": ["DEPT_HEAD"]})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_with_emp(db_session, admin_user):
    from app.db.models import Employee

    emp = Employee(emp_no="92000001", name_ko="관리자E", hire_date=date(2021, 1, 1))
    db_session.add(emp)
    db_session.flush()
    admin_user.employee_id = emp.id
    db_session.commit()
    db_session.refresh(admin_user)
    return admin_user


def test_create_result_by_admin(client, admin_with_emp, auth_headers):
    round_id = _create_round(client, auth_headers)
    emp_id = _create_employee(client, auth_headers, "50000001", "결과대상")

    resp = client.post(
        "/api/v1/eval/perf/results",
        json={"emp_id": emp_id, "round_id": round_id, "score": "88.00", "grade": "A"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["grade"] == "A"


def test_evaluator_cannot_create_result_without_mapping(client, auth_headers, evaluator_headers):
    round_id = _create_round(client, auth_headers)
    emp_id = _create_employee(client, auth_headers, "50000002", "비매핑대상")

    resp = client.post(
        "/api/v1/eval/perf/results",
        json={"emp_id": emp_id, "round_id": round_id, "score": "70.00", "grade": "B"},
        headers=evaluator_headers,
    )
    assert resp.status_code == 403


def test_evaluator_can_create_result_when_mapped(
    client, auth_headers, evaluator_user, evaluator_headers, db_session
):
    round_id = _create_round(client, auth_headers)
    emp_id = _create_employee(client, auth_headers, "50000003", "매핑대상")

    db_session.add(EvalApprover(
        round_id=round_id,
        evaluatee_id=emp_id,
        evaluator_id=evaluator_user.employee_id,
        eval_type="PERF",
    ))
    db_session.commit()

    resp = client.post(
        "/api/v1/eval/perf/results",
        json={"emp_id": emp_id, "round_id": round_id, "score": "75.00", "grade": "B"},
        headers=evaluator_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["evaluator_id"] == evaluator_user.employee_id


def test_list_results_by_round(client, admin_with_emp, auth_headers):
    round_id = _create_round(client, auth_headers)
    emp1 = _create_employee(client, auth_headers, "50000010", "R1")
    emp2 = _create_employee(client, auth_headers, "50000011", "R2")

    client.post("/api/v1/eval/perf/results",
                json={"emp_id": emp1, "round_id": round_id, "score": "90", "grade": "A"},
                headers=auth_headers)
    client.post("/api/v1/eval/perf/results",
                json={"emp_id": emp2, "round_id": round_id, "score": "70", "grade": "B"},
                headers=auth_headers)

    resp = client.get(f"/api/v1/eval/perf/results?round_id={round_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 2
