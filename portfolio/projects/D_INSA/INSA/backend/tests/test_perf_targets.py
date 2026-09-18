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
def employee_user(db_session):
    """Non-admin user tied to an employee."""
    from app.db.models import Employee

    role = db_session.query(Role).filter(Role.code == "EMPLOYEE").first()
    if role is None:
        role = Role(code="EMPLOYEE", name="사원")
        db_session.add(role)
        db_session.flush()

    emp = Employee(emp_no="90000001", name_ko="직원", hire_date=date(2021, 1, 1))
    db_session.add(emp)
    db_session.flush()

    user = User(
        login_id="emp1",
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
def evaluator_user(db_session):
    """Non-admin evaluator user (acts as DEPT_HEAD)."""
    from app.db.models import Employee

    role = db_session.query(Role).filter(Role.code == "DEPT_HEAD").first()
    if role is None:
        role = Role(code="DEPT_HEAD", name="부서장")
        db_session.add(role)
        db_session.flush()

    emp = Employee(emp_no="90000002", name_ko="평가자", hire_date=date(2021, 1, 1))
    db_session.add(emp)
    db_session.flush()

    user = User(
        login_id="eval1",
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


def _map_approver(db_session, round_id: int, evaluatee_id: int, evaluator_id: int) -> None:
    db_session.add(EvalApprover(
        round_id=round_id,
        evaluatee_id=evaluatee_id,
        evaluator_id=evaluator_id,
        eval_type="PERF",
    ))
    db_session.commit()


def test_create_target_by_admin(client, auth_headers):
    round_id = _create_round(client, auth_headers)
    emp_id = _create_employee(client, auth_headers, "20000001", "대상자")

    resp = client.post(
        "/api/v1/eval/perf/targets",
        json={
            "emp_id": emp_id,
            "round_id": round_id,
            "target_value": "매출 10% 증가",
            "weight_percent": "50.00",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "DRAFT"
    assert data["emp_id"] == emp_id


def test_weight_percent_sum_exceeds_100(client, auth_headers):
    round_id = _create_round(client, auth_headers)
    emp_id = _create_employee(client, auth_headers, "20000002", "대상자")

    client.post(
        "/api/v1/eval/perf/targets",
        json={"emp_id": emp_id, "round_id": round_id, "weight_percent": "60.00"},
        headers=auth_headers,
    )
    resp = client.post(
        "/api/v1/eval/perf/targets",
        json={"emp_id": emp_id, "round_id": round_id, "weight_percent": "50.00"},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "weight" in resp.json()["detail"].lower()


def test_status_transition_draft_to_submitted_to_approved(
    client, auth_headers, employee_user, employee_headers, evaluator_user, evaluator_headers, db_session
):
    round_id = _create_round(client, auth_headers)
    _map_approver(db_session, round_id, employee_user.employee_id, evaluator_user.employee_id)

    create = client.post(
        "/api/v1/eval/perf/targets",
        json={"emp_id": employee_user.employee_id, "round_id": round_id, "target_value": "T1"},
        headers=employee_headers,
    )
    assert create.status_code == 201
    target_id = create.json()["id"]

    submit = client.put(f"/api/v1/eval/perf/targets/{target_id}/submit", headers=employee_headers)
    assert submit.status_code == 200
    assert submit.json()["status"] == "SUBMITTED"

    approve = client.put(f"/api/v1/eval/perf/targets/{target_id}/approve", headers=evaluator_headers)
    assert approve.status_code == 200
    assert approve.json()["status"] == "APPROVED"


def test_approve_rejected_when_evaluator_not_mapped(
    client, auth_headers, employee_user, employee_headers, evaluator_headers
):
    round_id = _create_round(client, auth_headers)

    create = client.post(
        "/api/v1/eval/perf/targets",
        json={"emp_id": employee_user.employee_id, "round_id": round_id, "target_value": "T2"},
        headers=employee_headers,
    )
    target_id = create.json()["id"]
    client.put(f"/api/v1/eval/perf/targets/{target_id}/submit", headers=employee_headers)

    approve = client.put(f"/api/v1/eval/perf/targets/{target_id}/approve", headers=evaluator_headers)
    assert approve.status_code == 403


def test_cannot_submit_already_approved(
    client, auth_headers, employee_user, employee_headers, evaluator_user, evaluator_headers, db_session
):
    round_id = _create_round(client, auth_headers)
    _map_approver(db_session, round_id, employee_user.employee_id, evaluator_user.employee_id)

    create = client.post(
        "/api/v1/eval/perf/targets",
        json={"emp_id": employee_user.employee_id, "round_id": round_id, "target_value": "T3"},
        headers=employee_headers,
    )
    target_id = create.json()["id"]
    client.put(f"/api/v1/eval/perf/targets/{target_id}/submit", headers=employee_headers)
    client.put(f"/api/v1/eval/perf/targets/{target_id}/approve", headers=evaluator_headers)

    submit_again = client.put(f"/api/v1/eval/perf/targets/{target_id}/submit", headers=employee_headers)
    assert submit_again.status_code == 400


def test_reject_transitions_back_to_rejected(
    client, auth_headers, employee_user, employee_headers, evaluator_user, evaluator_headers, db_session
):
    round_id = _create_round(client, auth_headers)
    _map_approver(db_session, round_id, employee_user.employee_id, evaluator_user.employee_id)

    create = client.post(
        "/api/v1/eval/perf/targets",
        json={"emp_id": employee_user.employee_id, "round_id": round_id, "target_value": "T4"},
        headers=employee_headers,
    )
    target_id = create.json()["id"]
    client.put(f"/api/v1/eval/perf/targets/{target_id}/submit", headers=employee_headers)

    reject = client.put(f"/api/v1/eval/perf/targets/{target_id}/reject", headers=evaluator_headers)
    assert reject.status_code == 200
    assert reject.json()["status"] == "REJECTED"

    # REJECTED can go back to SUBMITTED
    resubmit = client.put(f"/api/v1/eval/perf/targets/{target_id}/submit", headers=employee_headers)
    assert resubmit.status_code == 200
    assert resubmit.json()["status"] == "SUBMITTED"


def test_employee_cannot_create_target_for_other(
    client, auth_headers, employee_headers
):
    round_id = _create_round(client, auth_headers)
    other_emp = _create_employee(client, auth_headers, "20000099", "남")

    resp = client.post(
        "/api/v1/eval/perf/targets",
        json={"emp_id": other_emp, "round_id": round_id, "target_value": "X"},
        headers=employee_headers,
    )
    assert resp.status_code == 403


def test_list_filters_by_emp_round(client, auth_headers):
    round_id = _create_round(client, auth_headers)
    emp_id = _create_employee(client, auth_headers, "20000010", "조회대상")

    client.post(
        "/api/v1/eval/perf/targets",
        json={"emp_id": emp_id, "round_id": round_id, "target_value": "A", "weight_percent": "30"},
        headers=auth_headers,
    )
    client.post(
        "/api/v1/eval/perf/targets",
        json={"emp_id": emp_id, "round_id": round_id, "target_value": "B", "weight_percent": "40"},
        headers=auth_headers,
    )

    resp = client.get(
        f"/api/v1/eval/perf/targets?emp_id={emp_id}&round_id={round_id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 2
