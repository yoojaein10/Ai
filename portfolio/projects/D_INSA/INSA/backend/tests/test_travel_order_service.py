"""Tests for travel_order_service (PHASE 16)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.db.models import (
    ApprovalDocType,
    ApprovalLineStep,
    ApprovalLineTemplate,
    Calendar,
    Department,
    Employee,
    Role,
    TravelCompanion,
    TravelOrderDetail,
    User,
    UserRole,
)
from app.services import approval_service as approval_svc
from app.services import travel_order_service as svc


# ── Fixtures ───────────────────────────────────────────────


@pytest.fixture
def dept(db_session):
    d = Department(code="DEV", name="개발팀")
    db_session.add(d)
    db_session.flush()
    return d


@pytest.fixture
def dept_head(db_session, dept):
    e = Employee(
        emp_no="H0001", name_ko="부서장",
        hire_date=date(2015, 1, 1), dept_id=dept.id,
    )
    db_session.add(e)
    db_session.flush()
    role = Role(code="DEPT_HEAD", name="부서장")
    db_session.add(role)
    db_session.flush()
    u = User(
        login_id=e.emp_no, password_hash="x",
        employee_id=e.id, is_active=True,
    )
    db_session.add(u)
    db_session.flush()
    db_session.add(UserRole(user_id=u.id, role_id=role.id))
    dept.head_employee_id = e.id
    db_session.commit()
    return u


@pytest.fixture
def employee(db_session, dept):
    e = Employee(
        emp_no="E0001", name_ko="홍길동",
        hire_date=date(2020, 1, 1), dept_id=dept.id,
    )
    db_session.add(e)
    db_session.flush()
    return e


@pytest.fixture
def companion_a(db_session, dept):
    e = Employee(
        emp_no="E0002", name_ko="동행A",
        hire_date=date(2021, 1, 1), dept_id=dept.id,
    )
    db_session.add(e)
    db_session.flush()
    return e


@pytest.fixture
def companion_b(db_session, dept):
    e = Employee(
        emp_no="E0003", name_ko="동행B",
        hire_date=date(2022, 1, 1), dept_id=dept.id,
    )
    db_session.add(e)
    db_session.flush()
    return e


@pytest.fixture
def emp_user(db_session, employee):
    role = Role(code="EMPLOYEE", name="직원")
    db_session.add(role)
    db_session.flush()
    u = User(
        login_id=employee.emp_no, password_hash="x",
        employee_id=employee.id, is_active=True,
    )
    db_session.add(u)
    db_session.flush()
    db_session.add(UserRole(user_id=u.id, role_id=role.id))
    db_session.commit()
    db_session.refresh(u)
    return u


@pytest.fixture
def travel_doc_config(db_session):
    dt = ApprovalDocType(
        code="TRAVEL_ORDER", name="출장명령부", category="TRAVEL"
    )
    db_session.add(dt)
    db_session.flush()
    tmpl = ApprovalLineTemplate(
        doc_type_id=dt.id, name="팀장 → 부서장",
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
    return {"doc_type": dt, "template": tmpl}


@pytest.fixture
def travel_calendar(db_session):
    cal = Calendar(
        name="출장", color_hex="#ff4d4f",
        scope="COMPANY", is_default=False,
    )
    db_session.add(cal)
    db_session.commit()
    return cal


# ── Draft ──────────────────────────────────────────────────


class TestCreateDraft:
    def test_happy_path(
        self, db_session, emp_user, travel_doc_config,
        companion_a, companion_b,
    ):
        doc, detail = svc.create_draft(
            db_session,
            user=emp_user,
            line_template_id=travel_doc_config["template"].id,
            title=None,
            travel_type="DOMESTIC",
            purpose="고객사 기술 협의",
            destination="부산",
            client_company="XX사",
            start_at=datetime(2026, 5, 1, 9, 0),
            end_at=datetime(2026, 5, 2, 18, 0),
            transportation="KTX",
            estimated_cost=Decimal("300000"),
            project_code="PRJ-01",
            appraisal_case_no="2026-감-001",
            remarks=None,
            companion_emp_ids=[companion_a.id, companion_b.id],
        )
        assert doc.status == "DRAFT"
        assert detail.doc_id == doc.id
        assert detail.destination == "부산"
        assert detail.appraisal_case_no == "2026-감-001"
        # Auto-generated title
        assert "부산" in doc.title

        comps = (
            db_session.query(TravelCompanion)
            .filter(TravelCompanion.travel_id == detail.id)
            .all()
        )
        emp_ids = {c.emp_id for c in comps}
        assert companion_a.id in emp_ids
        assert companion_b.id in emp_ids

    def test_drafter_excluded_from_companions(
        self, db_session, emp_user, employee, travel_doc_config, companion_a,
    ):
        _, detail = svc.create_draft(
            db_session, user=emp_user,
            line_template_id=travel_doc_config["template"].id,
            title="x", travel_type="DOMESTIC",
            purpose="p", destination="d",
            client_company=None,
            start_at=datetime(2026, 5, 1, 9, 0),
            end_at=datetime(2026, 5, 1, 18, 0),
            transportation=None, estimated_cost=None,
            project_code=None, appraisal_case_no=None,
            remarks=None,
            companion_emp_ids=[employee.id, companion_a.id],
        )
        comps = (
            db_session.query(TravelCompanion)
            .filter(TravelCompanion.travel_id == detail.id)
            .all()
        )
        emp_ids = {c.emp_id for c in comps}
        assert employee.id not in emp_ids
        assert companion_a.id in emp_ids

    def test_reversed_range_rejected(
        self, db_session, emp_user, travel_doc_config,
    ):
        with pytest.raises(svc.TravelOrderInvalid):
            svc.create_draft(
                db_session, user=emp_user,
                line_template_id=travel_doc_config["template"].id,
                title=None, travel_type="DOMESTIC",
                purpose="p", destination="d",
                client_company=None,
                start_at=datetime(2026, 5, 2, 9, 0),
                end_at=datetime(2026, 5, 1, 9, 0),
                transportation=None, estimated_cost=None,
                project_code=None, appraisal_case_no=None,
                remarks=None, companion_emp_ids=[],
            )


# ── Submit / Cancel ────────────────────────────────────────


class TestSubmitCancel:
    def _draft(self, db_session, emp_user, travel_doc_config, **overrides):
        return svc.create_draft(
            db_session, user=emp_user,
            line_template_id=travel_doc_config["template"].id,
            title=None, travel_type="DOMESTIC",
            purpose="고객 미팅", destination="서울",
            client_company=None,
            start_at=overrides.get("start_at", datetime(2026, 5, 1, 9, 0)),
            end_at=overrides.get("end_at", datetime(2026, 5, 1, 18, 0)),
            transportation=None, estimated_cost=None,
            project_code=None,
            appraisal_case_no=overrides.get("case_no"),
            remarks=None, companion_emp_ids=[],
        )

    def test_submit_transitions_to_pending(
        self, db_session, emp_user, travel_doc_config, dept_head,
    ):
        doc, _ = self._draft(db_session, emp_user, travel_doc_config)
        submitted = svc.submit(db_session, doc.id, emp_user)
        assert submitted.status in ("PENDING", "IN_PROGRESS")

    def test_cancel_draft_deletes(
        self, db_session, emp_user, travel_doc_config,
    ):
        doc, detail = self._draft(db_session, emp_user, travel_doc_config)
        detail_id = detail.id
        svc.cancel(db_session, doc.id, emp_user)
        assert (
            db_session.query(TravelOrderDetail)
            .filter(TravelOrderDetail.id == detail_id)
            .first()
            is None
        )


# ── Read ──────────────────────────────────────────────────


class TestRead:
    def _create_order(self, db_session, emp_user, travel_doc_config, **kw):
        return svc.create_draft(
            db_session, user=emp_user,
            line_template_id=travel_doc_config["template"].id,
            title=None, travel_type="DOMESTIC",
            purpose="x", destination=kw.get("destination", "서울"),
            client_company=None,
            start_at=datetime(2026, 5, 1, 9, 0),
            end_at=datetime(2026, 5, 1, 18, 0),
            transportation=None, estimated_cost=None,
            project_code=None,
            appraisal_case_no=kw.get("case_no"),
            remarks=None,
            companion_emp_ids=kw.get("companions", []),
        )

    def test_get_detail_includes_companions(
        self, db_session, emp_user, travel_doc_config,
        companion_a,
    ):
        doc, _ = self._create_order(
            db_session, emp_user, travel_doc_config,
            companions=[companion_a.id],
        )
        result = svc.get_detail(db_session, doc.id)
        assert len(result["companions"]) == 1
        assert result["companions"][0]["emp_id"] == companion_a.id
        assert result["companions"][0]["name_ko"] == "동행A"

    def test_list_my_includes_drafter(
        self, db_session, emp_user, travel_doc_config,
    ):
        self._create_order(db_session, emp_user, travel_doc_config)
        rows = svc.list_my(db_session, user=emp_user)
        assert len(rows) == 1
        assert rows[0]["status"] == "DRAFT"

    def test_list_my_includes_companion_trips(
        self, db_session, emp_user, employee, travel_doc_config,
        companion_a,
    ):
        # companion_a gets trip drafted by employee (emp_user)
        self._create_order(
            db_session, emp_user, travel_doc_config,
            companions=[companion_a.id],
        )
        # create a User for companion_a
        role = (
            db_session.query(Role).filter(Role.code == "EMPLOYEE").first()
        )
        if role is None:
            role = Role(code="EMPLOYEE", name="직원")
            db_session.add(role)
            db_session.flush()
        comp_user = User(
            login_id=companion_a.emp_no, password_hash="x",
            employee_id=companion_a.id, is_active=True,
        )
        db_session.add(comp_user)
        db_session.flush()
        db_session.add(UserRole(user_id=comp_user.id, role_id=role.id))
        db_session.commit()

        rows = svc.list_my(
            db_session, user=comp_user, include_companion=True
        )
        assert len(rows) == 1
        assert rows[0]["drafter_id"] == employee.id

    def test_find_by_case_no(
        self, db_session, emp_user, travel_doc_config,
    ):
        self._create_order(
            db_session, emp_user, travel_doc_config, case_no="2026-감-777",
        )
        self._create_order(
            db_session, emp_user, travel_doc_config, case_no="2026-감-888",
        )
        hits = svc.find_by_case_no(db_session, "2026-감-777")
        assert len(hits) == 1
        assert hits[0]["appraisal_case_no"] == "2026-감-777"
