from datetime import date

import pytest

from app.core.security import create_access_token, hash_password
from app.db.models import Role, User, UserRole


def _create_employee(client, auth_headers, emp_no, name) -> int:
    resp = client.post(
        "/api/v1/employees",
        json={"emp_no": emp_no, "name_ko": name, "hire_date": "2021-01-01"},
        headers=auth_headers,
    )
    return resp.json()["id"]


@pytest.fixture
def observer_user(db_session):
    from app.db.models import Employee

    role = db_session.query(Role).filter(Role.code == "DEPT_HEAD").first()
    if role is None:
        role = Role(code="DEPT_HEAD", name="부서장")
        db_session.add(role)
        db_session.flush()
    emp = Employee(emp_no="SAR0001", name_ko="관찰자", hire_date=date(2021, 1, 1))
    db_session.add(emp)
    db_session.flush()
    user = User(
        login_id="sar_obs",
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
def observer_headers(observer_user):
    token = create_access_token(str(observer_user.id), extra={"roles": ["DEPT_HEAD"]})
    return {"Authorization": f"Bearer {token}"}


def test_sar_create_list_update_delete(
    client, auth_headers, observer_user, observer_headers
):
    target_emp = _create_employee(client, auth_headers, "TGT00001", "관찰대상")

    create = client.post(
        "/api/v1/eval/comp/sar",
        json={
            "target_emp_id": target_emp,
            "observed_date": "2026-04-01",
            "situation": "긴급한 고객 이슈 발생",
            "action": "즉시 회의 소집",
            "result": "1시간 내 해결",
        },
        headers=observer_headers,
    )
    assert create.status_code == 201
    sar_id = create.json()["id"]
    assert create.json()["observer_id"] == observer_user.employee_id

    listing = client.get(
        f"/api/v1/eval/comp/sar?emp_id={target_emp}", headers=observer_headers
    )
    assert listing.status_code == 200
    assert any(r["id"] == sar_id for r in listing.json())

    update = client.put(
        f"/api/v1/eval/comp/sar/{sar_id}",
        json={"result": "고객 만족도 상승까지 확인"},
        headers=observer_headers,
    )
    assert update.status_code == 200
    assert update.json()["result"] == "고객 만족도 상승까지 확인"

    delete = client.delete(f"/api/v1/eval/comp/sar/{sar_id}", headers=observer_headers)
    assert delete.status_code == 204


def test_sar_other_observer_cannot_edit(
    client, auth_headers, observer_user, observer_headers, db_session
):
    """Another non-admin user cannot modify someone else's SAR record."""
    from app.db.models import Employee

    target_emp = _create_employee(client, auth_headers, "TGT00002", "관찰대상2")

    create = client.post(
        "/api/v1/eval/comp/sar",
        json={
            "target_emp_id": target_emp,
            "observed_date": "2026-04-02",
            "situation": "S",
            "action": "A",
            "result": "R",
        },
        headers=observer_headers,
    )
    sar_id = create.json()["id"]

    role = db_session.query(Role).filter(Role.code == "EMPLOYEE").first()
    if role is None:
        role = Role(code="EMPLOYEE", name="사원")
        db_session.add(role)
        db_session.flush()
    other_emp = Employee(emp_no="OTHER001", name_ko="다른관찰자", hire_date=date(2021, 1, 1))
    db_session.add(other_emp)
    db_session.flush()
    other_user = User(
        login_id="sar_other",
        password_hash=hash_password("password123"),
        is_active=True,
        employee_id=other_emp.id,
    )
    db_session.add(other_user)
    db_session.flush()
    db_session.add(UserRole(user_id=other_user.id, role_id=role.id))
    db_session.commit()

    other_token = create_access_token(str(other_user.id), extra={"roles": ["EMPLOYEE"]})
    other_headers = {"Authorization": f"Bearer {other_token}"}

    update = client.put(
        f"/api/v1/eval/comp/sar/{sar_id}",
        json={"result": "남의 글 수정"},
        headers=other_headers,
    )
    assert update.status_code == 403
