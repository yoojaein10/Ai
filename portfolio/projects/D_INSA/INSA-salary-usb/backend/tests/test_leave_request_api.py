"""HTTP integration tests for PHASE 15 `/api/v1/leave-request` routes."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.core.security import create_access_token, hash_password
from app.db.models import (
    ApprovalDocType,
    ApprovalLineStep,
    ApprovalLineTemplate,
    Calendar,
    Department,
    Employee,
    LeaveBalance,
    LeaveType,
    Role,
    User,
    UserRole,
)


# ── Fixtures ───────────────────────────────────────────────


@pytest.fixture
def roles(db_session):
    emp = Role(code="EMPLOYEE", name="직원")
    head = Role(code="DEPT_HEAD", name="부서장")
    db_session.add_all([emp, head])
    db_session.flush()
    return {"emp": emp, "head": head}


@pytest.fixture
def dept(db_session):
    d = Department(code="DEV", name="개발팀")
    db_session.add(d)
    db_session.flush()
    return d


@pytest.fixture
def dept_head(db_session, dept, roles):
    e = Employee(
        emp_no="H0001",
        name_ko="김부장",
        hire_date=date(2018, 1, 1),
        dept_id=dept.id,
    )
    db_session.add(e)
    db_session.flush()
    dept.head_employee_id = e.id
    u = User(
        login_id="H0001",
        password_hash=hash_password("x"),
        employee_id=e.id,
        is_active=True,
    )
    db_session.add(u)
    db_session.flush()
    db_session.add(UserRole(user_id=u.id, role_id=roles["head"].id))
    db_session.commit()
    db_session.refresh(u)
    return u


@pytest.fixture
def head_headers(dept_head):
    token = create_access_token(
        str(dept_head.id), extra={"roles": ["DEPT_HEAD"]}
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def employee_user(db_session, dept, roles, dept_head):
    e = Employee(
        emp_no="E0001",
        name_ko="홍길동",
        hire_date=date(2020, 1, 1),
        dept_id=dept.id,
    )
    db_session.add(e)
    db_session.flush()
    u = User(
        login_id="E0001",
        password_hash=hash_password("x"),
        employee_id=e.id,
        is_active=True,
    )
    db_session.add(u)
    db_session.flush()
    db_session.add(UserRole(user_id=u.id, role_id=roles["emp"].id))
    db_session.commit()
    db_session.refresh(u)
    return u


@pytest.fixture
def emp_headers(employee_user):
    token = create_access_token(
        str(employee_user.id), extra={"roles": ["EMPLOYEE"]}
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def leave_types(db_session):
    lt = LeaveType(
        code="ANNUAL",
        name="연차",
        deduct_from="ANNUAL",
        unit="DAY",
        is_paid=True,
        requires_evidence=False,
        sort_order=10,
    )
    db_session.add(lt)
    db_session.commit()
    return {"day": lt}


@pytest.fixture
def approval_template(db_session):
    dt = ApprovalDocType(
        code="ATT_LEAVE",
        name="휴가신청서",
        category="ATTENDANCE",
    )
    db_session.add(dt)
    db_session.flush()
    tmpl = ApprovalLineTemplate(
        doc_type_id=dt.id, name="부서장 전결", scope="GLOBAL", is_default=True
    )
    db_session.add(tmpl)
    db_session.flush()
    db_session.add(
        ApprovalLineStep(
            template_id=tmpl.id,
            step_order=1,
            approver_type="DEPT_HEAD",
            is_required=True,
        )
    )
    db_session.commit()
    return tmpl


@pytest.fixture
def balance(db_session, employee_user):
    b = LeaveBalance(
        emp_id=employee_user.employee_id,
        year=date.today().year,
        initial_days=Decimal("15"),
    )
    db_session.add(b)
    db_session.commit()
    return b


@pytest.fixture
def leave_calendar(db_session):
    cal = Calendar(
        name="휴가", color_hex="#52c41a", scope="COMPANY", is_default=False
    )
    db_session.add(cal)
    db_session.commit()
    return cal


# ── Tests ──────────────────────────────────────────────────


class TestCalculateDays:
    def test_happy_path(self, client, emp_headers, leave_types):
        resp = client.post(
            "/api/v1/leave-request/calculate-days",
            json={
                "leave_type_id": leave_types["day"].id,
                "start_date": "2026-04-27",
                "end_date": "2026-04-27",
            },
            headers=emp_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert Decimal(body["days"]) == Decimal("1")
        assert body["business_days"] == 1

    def test_weekend_returns_zero_days(self, client, emp_headers, leave_types):
        """2026-04-25 is Saturday — DAY unit returns business_days=0."""
        resp = client.post(
            "/api/v1/leave-request/calculate-days",
            json={
                "leave_type_id": leave_types["day"].id,
                "start_date": "2026-04-25",
                "end_date": "2026-04-25",
            },
            headers=emp_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["business_days"] == 0
        assert Decimal(body["days"]) == Decimal("0")

    def test_reversed_range_rejected(self, client, emp_headers, leave_types):
        resp = client.post(
            "/api/v1/leave-request/calculate-days",
            json={
                "leave_type_id": leave_types["day"].id,
                "start_date": "2026-04-27",
                "end_date": "2026-04-26",
            },
            headers=emp_headers,
        )
        assert resp.status_code == 400

    def test_missing_type_404(self, client, emp_headers):
        resp = client.post(
            "/api/v1/leave-request/calculate-days",
            json={
                "leave_type_id": 999999,
                "start_date": "2026-04-27",
                "end_date": "2026-04-27",
            },
            headers=emp_headers,
        )
        assert resp.status_code == 404


class TestDraftSubmitCancel:
    def test_create_draft(
        self,
        client,
        emp_headers,
        leave_types,
        approval_template,
        balance,
    ):
        resp = client.post(
            "/api/v1/leave-request",
            json={
                "leave_type_id": leave_types["day"].id,
                "line_template_id": approval_template.id,
                "start_date": "2026-04-27",
                "end_date": "2026-04-27",
                "reason": "개인사유",
            },
            headers=emp_headers,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["status"] == "DRAFT"
        assert body["doc_id"] > 0

    def test_insufficient_balance_409(
        self,
        client,
        emp_headers,
        leave_types,
        approval_template,
        db_session,
        employee_user,
    ):
        # tiny balance
        b = LeaveBalance(
            emp_id=employee_user.employee_id,
            year=date.today().year,
            initial_days=Decimal("0.5"),
        )
        db_session.add(b)
        db_session.commit()

        resp = client.post(
            "/api/v1/leave-request",
            json={
                "leave_type_id": leave_types["day"].id,
                "line_template_id": approval_template.id,
                "start_date": "2026-04-27",
                "end_date": "2026-04-28",
            },
            headers=emp_headers,
        )
        assert resp.status_code == 409

    def test_submit_transitions_to_pending(
        self,
        client,
        emp_headers,
        leave_types,
        approval_template,
        balance,
    ):
        created = client.post(
            "/api/v1/leave-request",
            json={
                "leave_type_id": leave_types["day"].id,
                "line_template_id": approval_template.id,
                "start_date": "2026-04-27",
                "end_date": "2026-04-27",
            },
            headers=emp_headers,
        ).json()

        resp = client.post(
            f"/api/v1/leave-request/{created['doc_id']}/submit",
            headers=emp_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "PENDING"

    def test_cancel_draft(
        self,
        client,
        emp_headers,
        leave_types,
        approval_template,
        balance,
    ):
        created = client.post(
            "/api/v1/leave-request",
            json={
                "leave_type_id": leave_types["day"].id,
                "line_template_id": approval_template.id,
                "start_date": "2026-04-27",
                "end_date": "2026-04-27",
            },
            headers=emp_headers,
        ).json()

        resp = client.post(
            f"/api/v1/leave-request/{created['doc_id']}/cancel",
            headers=emp_headers,
        )
        assert resp.status_code == 200, resp.text

    def test_submit_missing_404(self, client, emp_headers):
        resp = client.post(
            "/api/v1/leave-request/999999/submit", headers=emp_headers
        )
        assert resp.status_code == 404


class TestLists:
    def test_list_my(
        self,
        client,
        emp_headers,
        leave_types,
        approval_template,
        balance,
    ):
        client.post(
            "/api/v1/leave-request",
            json={
                "leave_type_id": leave_types["day"].id,
                "line_template_id": approval_template.id,
                "start_date": "2026-04-27",
                "end_date": "2026-04-27",
            },
            headers=emp_headers,
        )
        resp = client.get("/api/v1/leave-request/my", headers=emp_headers)
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["leave_type_name"] == "연차"

    def test_list_my_status_filter(
        self,
        client,
        emp_headers,
        leave_types,
        approval_template,
        balance,
    ):
        client.post(
            "/api/v1/leave-request",
            json={
                "leave_type_id": leave_types["day"].id,
                "line_template_id": approval_template.id,
                "start_date": "2026-04-27",
                "end_date": "2026-04-27",
            },
            headers=emp_headers,
        )
        resp = client.get(
            "/api/v1/leave-request/my?status=DRAFT", headers=emp_headers
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 1

        resp2 = client.get(
            "/api/v1/leave-request/my?status=APPROVED", headers=emp_headers
        )
        assert resp2.status_code == 200
        assert len(resp2.json()) == 0

    def test_list_team_as_dept_head(
        self,
        client,
        head_headers,
        emp_headers,
        leave_types,
        approval_template,
        balance,
    ):
        # Employee creates draft
        client.post(
            "/api/v1/leave-request",
            json={
                "leave_type_id": leave_types["day"].id,
                "line_template_id": approval_template.id,
                "start_date": "2026-04-27",
                "end_date": "2026-04-27",
            },
            headers=emp_headers,
        )
        # Dept head sees it
        resp = client.get("/api/v1/leave-request/team", headers=head_headers)
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["drafter_emp_no"] == "E0001"

    def test_list_team_as_hr(
        self,
        client,
        auth_headers,
        emp_headers,
        leave_types,
        approval_template,
        balance,
    ):
        client.post(
            "/api/v1/leave-request",
            json={
                "leave_type_id": leave_types["day"].id,
                "line_template_id": approval_template.id,
                "start_date": "2026-04-27",
                "end_date": "2026-04-27",
            },
            headers=emp_headers,
        )
        resp = client.get("/api/v1/leave-request/team", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) >= 1


class TestApprovalFlow:
    """End-to-end via HTTP: draft → submit → approve → balance drained."""

    def test_approve_drains_balance_and_creates_event(
        self,
        client,
        emp_headers,
        head_headers,
        leave_types,
        approval_template,
        balance,
        leave_calendar,
        db_session,
    ):
        from app.db.models import CalendarEvent

        created = client.post(
            "/api/v1/leave-request",
            json={
                "leave_type_id": leave_types["day"].id,
                "line_template_id": approval_template.id,
                "start_date": "2026-04-27",
                "end_date": "2026-04-27",
                "reason": "개인사유",
            },
            headers=emp_headers,
        ).json()

        # submit
        client.post(
            f"/api/v1/leave-request/{created['doc_id']}/submit",
            headers=emp_headers,
        )

        # dept head approves via /approval endpoint
        resp = client.post(
            f"/api/v1/approval/docs/{created['doc_id']}/approve",
            json={"comment": None},
            headers=head_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "APPROVED"

        db_session.refresh(balance)
        assert Decimal(balance.used_days) == Decimal("1")
        assert Decimal(balance.scheduled_days) == Decimal("0")

        event = (
            db_session.query(CalendarEvent)
            .filter(
                CalendarEvent.source_type == "APPROVAL_DOC",
                CalendarEvent.source_ref == created["doc_id"],
            )
            .first()
        )
        assert event is not None
        assert event.event_type == "LEAVE"
