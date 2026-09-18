"""HTTP integration tests for PHASE 15 `/api/v1/holiday` routes."""

from __future__ import annotations

from datetime import date

import pytest

from app.core.security import create_access_token, hash_password
from app.db.models import Employee, Holiday, Role, User, UserRole


# ── Fixtures ───────────────────────────────────────────────


@pytest.fixture
def emp_user(db_session):
    role = Role(code="EMPLOYEE", name="직원")
    db_session.add(role)
    db_session.flush()
    emp = Employee(
        emp_no="H0001",
        name_ko="직원",
        hire_date=date(2020, 1, 1),
    )
    db_session.add(emp)
    db_session.flush()
    u = User(
        login_id="emp1",
        password_hash=hash_password("x"),
        employee_id=emp.id,
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
    token = create_access_token(str(emp_user.id), extra={"roles": ["EMPLOYEE"]})
    return {"Authorization": f"Bearer {token}"}


# ── Tests ──────────────────────────────────────────────────


class TestHolidayAPI:
    def test_create_and_list(self, client, auth_headers):
        resp = client.post(
            "/api/v1/holiday",
            json={"date": "2026-05-05", "name": "어린이날", "is_recurring": True},
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["name"] == "어린이날"
        assert body["is_recurring"] is True

        lst = client.get("/api/v1/holiday?year=2026", headers=auth_headers)
        assert lst.status_code == 200
        items = lst.json()
        assert any(h["name"] == "어린이날" for h in items)

    def test_recurring_appears_in_other_years(
        self, client, auth_headers, db_session
    ):
        """A recurring (solar) holiday should appear when listing any year."""
        db_session.add(
            Holiday(date=date(2025, 5, 5), name="어린이날", is_recurring=True)
        )
        db_session.commit()

        for year in (2024, 2025, 2026, 2030):
            resp = client.get(f"/api/v1/holiday?year={year}", headers=auth_headers)
            assert resp.status_code == 200
            items = resp.json()
            assert any(
                h["name"] == "어린이날" and h["date"].endswith("-05-05")
                for h in items
            ), f"missing in {year}"

    def test_duplicate_rejected(self, client, auth_headers):
        client.post(
            "/api/v1/holiday",
            json={"date": "2026-10-03", "name": "개천절", "is_recurring": False},
            headers=auth_headers,
        )
        dup = client.post(
            "/api/v1/holiday",
            json={"date": "2026-10-03", "name": "중복", "is_recurring": False},
            headers=auth_headers,
        )
        assert dup.status_code == 409

    def test_delete(self, client, auth_headers):
        created = client.post(
            "/api/v1/holiday",
            json={"date": "2026-12-25", "name": "크리스마스", "is_recurring": True},
            headers=auth_headers,
        ).json()
        resp = client.delete(
            f"/api/v1/holiday/{created['id']}", headers=auth_headers
        )
        assert resp.status_code == 204

        lst = client.get("/api/v1/holiday?year=2026", headers=auth_headers)
        assert not any(h["id"] == created["id"] for h in lst.json())

    def test_delete_missing_404(self, client, auth_headers):
        resp = client.delete("/api/v1/holiday/999999", headers=auth_headers)
        assert resp.status_code == 404

    def test_employee_can_list_but_not_create(
        self, client, emp_headers, auth_headers
    ):
        # HR seeds
        client.post(
            "/api/v1/holiday",
            json={"date": "2026-08-15", "name": "광복절", "is_recurring": True},
            headers=auth_headers,
        )
        # Employee can read
        lst = client.get("/api/v1/holiday", headers=emp_headers)
        assert lst.status_code == 200

        # Employee cannot write
        resp = client.post(
            "/api/v1/holiday",
            json={"date": "2026-01-01", "name": "신정", "is_recurring": True},
            headers=emp_headers,
        )
        assert resp.status_code == 403

        dl = client.delete("/api/v1/holiday/1", headers=emp_headers)
        assert dl.status_code == 403
