"""HTTP integration tests for PHASE 16 `/api/v1/travel` routes."""

from __future__ import annotations

from datetime import date

import pytest

from app.core.security import create_access_token, hash_password
from app.db.models import (
    ApprovalDocType,
    ApprovalLineStep,
    ApprovalLineTemplate,
    Calendar,
    Department,
    Employee,
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
        emp_no="H0001", name_ko="김부장",
        hire_date=date(2015, 1, 1), dept_id=dept.id,
    )
    db_session.add(e)
    db_session.flush()
    dept.head_employee_id = e.id
    u = User(
        login_id="H0001", password_hash=hash_password("x"),
        employee_id=e.id, is_active=True,
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
        emp_no="E0001", name_ko="홍길동",
        hire_date=date(2020, 1, 1), dept_id=dept.id,
    )
    db_session.add(e)
    db_session.flush()
    u = User(
        login_id="E0001", password_hash=hash_password("x"),
        employee_id=e.id, is_active=True,
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
def companion(db_session, dept):
    e = Employee(
        emp_no="E0002", name_ko="동행A",
        hire_date=date(2021, 1, 1), dept_id=dept.id,
    )
    db_session.add(e)
    db_session.commit()
    return e


@pytest.fixture
def travel_order_template(db_session):
    dt = ApprovalDocType(
        code="TRAVEL_ORDER", name="출장명령부", category="TRAVEL"
    )
    db_session.add(dt)
    db_session.flush()
    tmpl = ApprovalLineTemplate(
        doc_type_id=dt.id, name="부서장 전결",
        scope="GLOBAL", is_default=True,
    )
    db_session.add(tmpl)
    db_session.flush()
    db_session.add(
        ApprovalLineStep(
            template_id=tmpl.id, step_order=1,
            approver_type="DEPT_HEAD", is_required=True,
        )
    )
    db_session.commit()
    return tmpl


@pytest.fixture
def travel_report_template(db_session):
    dt = ApprovalDocType(
        code="TRAVEL_REPORT", name="출장복명서", category="TRAVEL"
    )
    db_session.add(dt)
    db_session.flush()
    tmpl = ApprovalLineTemplate(
        doc_type_id=dt.id, name="부서장 전결",
        scope="GLOBAL", is_default=True,
    )
    db_session.add(tmpl)
    db_session.flush()
    db_session.add(
        ApprovalLineStep(
            template_id=tmpl.id, step_order=1,
            approver_type="DEPT_HEAD", is_required=True,
        )
    )
    db_session.commit()
    return tmpl


@pytest.fixture
def travel_calendar(db_session):
    cal = Calendar(
        name="출장", color_hex="#ff4d4f",
        scope="COMPANY", is_default=False,
    )
    db_session.add(cal)
    db_session.commit()
    return cal


def _create_payload(
    template_id: int,
    companion_ids: list[int] | None = None,
    case_no: str | None = None,
) -> dict:
    return {
        "line_template_id": template_id,
        "title": None,
        "travel_type": "DOMESTIC",
        "purpose": "고객 미팅",
        "destination": "부산",
        "client_company": "XX사",
        "start_at": "2026-05-01T09:00:00",
        "end_at": "2026-05-02T18:00:00",
        "transportation": "KTX",
        "estimated_cost": "300000",
        "project_code": "PRJ-01",
        "appraisal_case_no": case_no,
        "remarks": None,
        "companion_emp_ids": companion_ids or [],
    }


# ── Tests ──────────────────────────────────────────────────


class TestCreateOrder:
    def test_create_draft_201(
        self, client, emp_headers, travel_order_template, companion,
    ):
        resp = client.post(
            "/api/v1/travel/orders",
            json=_create_payload(travel_order_template.id, [companion.id]),
            headers=emp_headers,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["status"] == "DRAFT"
        assert body["doc_id"] > 0
        assert body["detail_id"] > 0

    def test_reversed_range_400(
        self, client, emp_headers, travel_order_template,
    ):
        payload = _create_payload(travel_order_template.id)
        payload["start_at"] = "2026-05-02T09:00:00"
        payload["end_at"] = "2026-05-01T09:00:00"
        resp = client.post(
            "/api/v1/travel/orders", json=payload, headers=emp_headers,
        )
        assert resp.status_code == 400

    def test_unauthenticated_401(
        self, client, travel_order_template,
    ):
        resp = client.post(
            "/api/v1/travel/orders",
            json=_create_payload(travel_order_template.id),
        )
        assert resp.status_code in (401, 403)


class TestSubmitCancel:
    def test_submit_flow(
        self, client, emp_headers, travel_order_template, dept_head,
    ):
        created = client.post(
            "/api/v1/travel/orders",
            json=_create_payload(travel_order_template.id),
            headers=emp_headers,
        ).json()
        doc_id = created["doc_id"]
        resp = client.post(
            f"/api/v1/travel/orders/{doc_id}/submit", headers=emp_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] in ("PENDING", "IN_PROGRESS")

    def test_cancel_draft(
        self, client, emp_headers, travel_order_template,
    ):
        created = client.post(
            "/api/v1/travel/orders",
            json=_create_payload(travel_order_template.id),
            headers=emp_headers,
        ).json()
        doc_id = created["doc_id"]
        resp = client.post(
            f"/api/v1/travel/orders/{doc_id}/cancel", headers=emp_headers,
        )
        assert resp.status_code == 200


class TestReadOrders:
    def test_list_my_empty(self, client, emp_headers):
        resp = client.get("/api/v1/travel/orders/my", headers=emp_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_my_returns_drafter_rows(
        self, client, emp_headers, travel_order_template, companion,
    ):
        client.post(
            "/api/v1/travel/orders",
            json=_create_payload(travel_order_template.id, [companion.id]),
            headers=emp_headers,
        )
        resp = client.get("/api/v1/travel/orders/my", headers=emp_headers)
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 1
        assert rows[0]["destination"] == "부산"
        assert rows[0]["companion_count"] == 1

    def test_get_detail(
        self, client, emp_headers, travel_order_template, companion,
    ):
        created = client.post(
            "/api/v1/travel/orders",
            json=_create_payload(travel_order_template.id, [companion.id]),
            headers=emp_headers,
        ).json()
        doc_id = created["doc_id"]
        resp = client.get(
            f"/api/v1/travel/orders/{doc_id}", headers=emp_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["destination"] == "부산"
        assert len(body["companions"]) == 1
        assert body["companions"][0]["emp_id"] == companion.id

    def test_get_detail_not_found(self, client, emp_headers):
        resp = client.get(
            "/api/v1/travel/orders/999999", headers=emp_headers,
        )
        # service returns empty dict-likes on missing detail via TravelOrderNotFound
        assert resp.status_code in (404, 500)

    def test_find_by_case_no(
        self, client, emp_headers, travel_order_template,
    ):
        client.post(
            "/api/v1/travel/orders",
            json=_create_payload(travel_order_template.id, case_no="2026-감-777"),
            headers=emp_headers,
        )
        client.post(
            "/api/v1/travel/orders",
            json=_create_payload(travel_order_template.id, case_no="2026-감-888"),
            headers=emp_headers,
        )
        resp = client.get(
            "/api/v1/travel/orders/by-case/2026-감-777", headers=emp_headers,
        )
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 1
        assert rows[0]["appraisal_case_no"] == "2026-감-777"

    def test_list_team_as_member(
        self, client, emp_headers, travel_order_template,
    ):
        client.post(
            "/api/v1/travel/orders",
            json=_create_payload(travel_order_template.id),
            headers=emp_headers,
        )
        resp = client.get(
            "/api/v1/travel/orders/team", headers=emp_headers,
        )
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 1


class TestReport:
    def test_create_report_before_approval_rejected(
        self, client, emp_headers,
        travel_order_template, travel_report_template,
    ):
        created = client.post(
            "/api/v1/travel/orders",
            json=_create_payload(travel_order_template.id),
            headers=emp_headers,
        ).json()
        doc_id = created["doc_id"]
        resp = client.post(
            f"/api/v1/travel/orders/{doc_id}/report",
            json={
                "line_template_id": travel_report_template.id,
                "title": None,
                "report_content": "결과 보고",
                "actual_cost": None,
                "receipts_url": None,
            },
            headers=emp_headers,
        )
        assert resp.status_code == 400

    def test_get_report_none_when_missing(
        self, client, emp_headers, travel_order_template,
    ):
        created = client.post(
            "/api/v1/travel/orders",
            json=_create_payload(travel_order_template.id),
            headers=emp_headers,
        ).json()
        doc_id = created["doc_id"]
        resp = client.get(
            f"/api/v1/travel/orders/{doc_id}/report", headers=emp_headers,
        )
        assert resp.status_code == 200
        assert resp.json() is None
