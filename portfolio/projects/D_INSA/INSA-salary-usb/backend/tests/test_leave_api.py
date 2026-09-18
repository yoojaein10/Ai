"""HTTP integration tests for PHASE 14 `/api/v1/leave` routes."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.core.security import create_access_token, hash_password
from app.db.models import (
    Department,
    Employee,
    LeaveAccrualRule,
    LeaveBalance,
    Role,
    User,
    UserRole,
)


# ── Helpers ────────────────────────────────────────────────


@pytest.fixture
def dept(db_session):
    d = Department(code="DEV", name="개발팀")
    db_session.add(d)
    db_session.commit()
    return d


@pytest.fixture
def employee(db_session, dept):
    e = Employee(
        emp_no="L0001",
        name_ko="연차사용자",
        gender="M",
        birth_date=date(1990, 1, 1),
        hire_date=date(2020, 1, 1),
        hire_type="신규",
        workplace="본사",
        work_location="서울",
        dept_id=dept.id,
        job_rank="사원",
        job_position="팀원",
        emp_type="정규직",
    )
    db_session.add(e)
    db_session.commit()
    return e


@pytest.fixture
def emp_user(db_session, employee):
    role = db_session.query(Role).filter(Role.code == "EMPLOYEE").first()
    if role is None:
        role = Role(code="EMPLOYEE", name="일반직원")
        db_session.add(role)
        db_session.flush()
    u = User(
        login_id="lu1",
        password_hash=hash_password("x"),
        employee_id=employee.id,
        is_active=True,
    )
    db_session.add(u)
    db_session.flush()
    db_session.add(UserRole(user_id=u.id, role_id=role.id))
    db_session.commit()
    db_session.refresh(u)
    return u


@pytest.fixture
def emp_headers(emp_user):
    token = create_access_token(
        str(emp_user.id), extra={"roles": ["EMPLOYEE"]}
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def rule_2026(db_session):
    r = LeaveAccrualRule(
        year=2026,
        under_1year_monthly=1,
        under_1year_max=11,
        base_days=15,
        tenure_bonus_start_years=3,
        tenure_bonus_interval=2,
        max_days=25,
        carry_over_enabled=False,
    )
    db_session.add(r)
    db_session.commit()
    return r


# ── Leave types ────────────────────────────────────────────


class TestLeaveTypes:
    def test_create_and_list(self, client, auth_headers):
        resp = client.post(
            "/api/v1/leave/types",
            json={"code": "ANNUAL", "name": "연차"},
            headers=auth_headers,
        )
        assert resp.status_code == 201

        resp = client.get("/api/v1/leave/types", headers=auth_headers)
        assert resp.status_code == 200
        types = resp.json()
        assert any(t["code"] == "ANNUAL" for t in types)

    def test_duplicate_code_rejected(self, client, auth_headers):
        client.post(
            "/api/v1/leave/types",
            json={"code": "ANNUAL", "name": "연차"},
            headers=auth_headers,
        )
        dup = client.post(
            "/api/v1/leave/types",
            json={"code": "ANNUAL", "name": "연차2"},
            headers=auth_headers,
        )
        assert dup.status_code == 409

    def test_employee_can_read(self, client, emp_headers, auth_headers):
        client.post(
            "/api/v1/leave/types",
            json={"code": "SICK", "name": "병가"},
            headers=auth_headers,
        )
        resp = client.get("/api/v1/leave/types", headers=emp_headers)
        assert resp.status_code == 200

    def test_employee_cannot_create(self, client, emp_headers):
        resp = client.post(
            "/api/v1/leave/types",
            json={"code": "X", "name": "X"},
            headers=emp_headers,
        )
        assert resp.status_code == 403


# ── Rules ──────────────────────────────────────────────────


class TestRules:
    def test_create_and_get_rule(self, client, auth_headers):
        resp = client.post(
            "/api/v1/leave/rules",
            json={"year": 2027},
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.text

        get = client.get("/api/v1/leave/rules/2027", headers=auth_headers)
        assert get.status_code == 200
        assert get.json()["base_days"] == 15

    def test_update_rule(self, client, auth_headers):
        client.post(
            "/api/v1/leave/rules",
            json={"year": 2028},
            headers=auth_headers,
        )
        upd = client.put(
            "/api/v1/leave/rules/2028",
            json={"base_days": 20},
            headers=auth_headers,
        )
        assert upd.status_code == 200
        assert upd.json()["base_days"] == 20


# ── Balance + transactions ─────────────────────────────────


class TestBalance:
    def test_my_balance_auto_creates(
        self, client, emp_headers, rule_2026, employee
    ):
        resp = client.get(
            "/api/v1/leave/balance/me?year=2026", headers=emp_headers
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["emp_id"] == employee.id
        assert body["year"] == 2026

    def test_grant_initial_and_list(
        self, client, auth_headers, rule_2026, employee
    ):
        resp = client.post(
            f"/api/v1/leave/grant-initial/{employee.id}?year=2026",
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # 6 years tenure → 17
        assert Decimal(body["initial_days"]) == Decimal("17")

        lst = client.get(
            "/api/v1/leave/balance?year=2026", headers=auth_headers
        )
        assert lst.status_code == 200
        items = lst.json()
        assert len(items) == 1
        assert items[0]["emp_id"] == employee.id

    def test_adjust_balance(
        self, client, auth_headers, rule_2026, employee
    ):
        client.post(
            f"/api/v1/leave/grant-initial/{employee.id}?year=2026",
            headers=auth_headers,
        )
        resp = client.post(
            "/api/v1/leave/adjust?year=2026",
            json={"emp_id": employee.id, "amount": 3, "reason": "포상"},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        assert Decimal(resp.json()["amount"]) == Decimal("3")

    def test_transactions_self_allowed(
        self, client, auth_headers, emp_headers, rule_2026, employee
    ):
        client.post(
            f"/api/v1/leave/grant-initial/{employee.id}?year=2026",
            headers=auth_headers,
        )
        resp = client.get(
            f"/api/v1/leave/transactions/{employee.id}", headers=emp_headers
        )
        assert resp.status_code == 200
        txs = resp.json()
        assert any(t["transaction_type"] == "INITIAL_GRANT" for t in txs)

    def test_transactions_other_forbidden(
        self, client, emp_headers, db_session, dept
    ):
        # Different employee
        other = Employee(
            emp_no="L9999",
            name_ko="다른사람",
            hire_date=date(2020, 1, 1),
            dept_id=dept.id,
            emp_status="재직",
            gender="M",
        )
        db_session.add(other)
        db_session.commit()

        resp = client.get(
            f"/api/v1/leave/transactions/{other.id}", headers=emp_headers
        )
        assert resp.status_code == 403


class TestAdminActions:
    def test_run_monthly(self, client, auth_headers, rule_2026, db_session, dept):
        # Create a <1yr employee
        emp = Employee(
            emp_no="NEW01",
            name_ko="신입",
            hire_date=date(2025, 10, 1),
            dept_id=dept.id,
            emp_status="재직",
            gender="M",
        )
        db_session.add(emp)
        db_session.commit()

        resp = client.post(
            "/api/v1/leave/run-monthly?year=2026&month=2",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["granted"] == 1

    def test_run_yearly_reset(
        self, client, auth_headers, rule_2026, employee
    ):
        resp = client.post(
            "/api/v1/leave/run-yearly-reset?year=2026",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["granted"] >= 1

    def test_carry_over_exempt_toggle(
        self, client, auth_headers, rule_2026, employee
    ):
        resp = client.post(
            "/api/v1/leave/carry-over-exempt",
            json={"emp_id": employee.id, "year": 2026, "exempt": True},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["carry_over_exempt"] is True

    def test_employee_cannot_adjust(
        self, client, emp_headers, rule_2026, employee
    ):
        resp = client.post(
            "/api/v1/leave/adjust",
            json={"emp_id": employee.id, "amount": 1, "reason": "x"},
            headers=emp_headers,
        )
        assert resp.status_code == 403
