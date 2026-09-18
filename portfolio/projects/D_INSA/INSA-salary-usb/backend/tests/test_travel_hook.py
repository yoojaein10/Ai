"""End-to-end tests for TRAVEL_ORDER / TRAVEL_REPORT doc-hook pipeline (PHASE 16)."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.db.models import (
    ApprovalDoc,
    ApprovalDocType,
    ApprovalLineStep,
    ApprovalLineTemplate,
    Calendar,
    CalendarEvent,
    CalendarEventParticipant,
    Department,
    Employee,
    Role,
    TravelReport,
    User,
    UserRole,
)
from app.services import (
    approval_service,
    doc_hooks,
    travel_order_service,
    travel_report_service,
)


# ── Fixtures ───────────────────────────────────────────────


@pytest.fixture
def roles(db_session):
    emp_role = Role(code="EMPLOYEE", name="직원")
    head_role = Role(code="DEPT_HEAD", name="부서장")
    db_session.add_all([emp_role, head_role])
    db_session.flush()
    return {"emp": emp_role, "head": head_role}


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
        login_id="H0001", password_hash="x",
        employee_id=e.id, is_active=True,
    )
    db_session.add(u)
    db_session.flush()
    db_session.add(UserRole(user_id=u.id, role_id=roles["head"].id))
    db_session.commit()
    db_session.refresh(u)
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
def emp_user(db_session, employee, roles, dept_head):
    u = User(
        login_id=employee.emp_no, password_hash="x",
        employee_id=employee.id, is_active=True,
    )
    db_session.add(u)
    db_session.flush()
    db_session.add(UserRole(user_id=u.id, role_id=roles["emp"].id))
    db_session.commit()
    db_session.refresh(u)
    return u


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


# ── Helper ─────────────────────────────────────────────────


def _draft_and_submit_order(
    db_session, emp_user, travel_order_template, companion_ids,
):
    doc, _ = travel_order_service.create_draft(
        db_session, user=emp_user,
        line_template_id=travel_order_template.id,
        title=None, travel_type="DOMESTIC",
        purpose="고객사 기술 협의", destination="부산",
        client_company="XX사",
        start_at=datetime(2026, 5, 1, 9, 0),
        end_at=datetime(2026, 5, 2, 18, 0),
        transportation="KTX", estimated_cost=None,
        project_code=None, appraisal_case_no=None,
        remarks=None, companion_emp_ids=companion_ids,
    )
    travel_order_service.submit(db_session, doc.id, emp_user)
    return doc.id


# ── TRAVEL_ORDER hooks ─────────────────────────────────────


class TestTravelOrderApproval:
    def test_approve_creates_event_with_participants(
        self, db_session, emp_user, travel_order_template,
        travel_calendar, dept_head, companion_a, companion_b,
    ):
        doc_id = _draft_and_submit_order(
            db_session, emp_user, travel_order_template,
            [companion_a.id, companion_b.id],
        )
        approval_service.approve_step(db_session, doc_id, dept_head)

        event = (
            db_session.query(CalendarEvent)
            .filter(
                CalendarEvent.source_type == "APPROVAL_DOC",
                CalendarEvent.source_ref == doc_id,
            )
            .first()
        )
        assert event is not None
        assert event.event_type == "TRAVEL"
        assert event.owner_id == emp_user.employee_id
        assert event.location == "부산"

        participants = (
            db_session.query(CalendarEventParticipant)
            .filter(CalendarEventParticipant.event_id == event.id)
            .all()
        )
        emp_ids = {p.emp_id for p in participants}
        assert companion_a.id in emp_ids
        assert companion_b.id in emp_ids

    def test_approve_without_companions_creates_event(
        self, db_session, emp_user, travel_order_template,
        travel_calendar, dept_head,
    ):
        doc_id = _draft_and_submit_order(
            db_session, emp_user, travel_order_template, [],
        )
        approval_service.approve_step(db_session, doc_id, dept_head)
        event = (
            db_session.query(CalendarEvent)
            .filter(CalendarEvent.source_ref == doc_id)
            .first()
        )
        assert event is not None
        participants = (
            db_session.query(CalendarEventParticipant)
            .filter(CalendarEventParticipant.event_id == event.id)
            .all()
        )
        # Only the drafter as ORGANIZER, no companions.
        assert len(participants) == 1
        assert participants[0].emp_id == emp_user.employee_id
        assert participants[0].role == "ORGANIZER"

    def test_approve_event_idempotent(
        self, db_session, emp_user, travel_order_template,
        travel_calendar, dept_head, companion_a,
    ):
        doc_id = _draft_and_submit_order(
            db_session, emp_user, travel_order_template, [companion_a.id],
        )
        approval_service.approve_step(db_session, doc_id, dept_head)

        doc = db_session.get(ApprovalDoc, doc_id)
        doc_hooks.dispatch(db_session, doc, "approved")

        events = (
            db_session.query(CalendarEvent)
            .filter(CalendarEvent.source_ref == doc_id)
            .all()
        )
        assert len(events) == 1

    def test_reject_deletes_event(
        self, db_session, emp_user, travel_order_template,
        travel_calendar, dept_head, companion_a,
    ):
        doc_id = _draft_and_submit_order(
            db_session, emp_user, travel_order_template, [companion_a.id],
        )
        approval_service.approve_step(db_session, doc_id, dept_head)
        assert (
            db_session.query(CalendarEvent)
            .filter(CalendarEvent.source_ref == doc_id)
            .first()
            is not None
        )
        # Reject via dispatch (ApprovalDoc state doesn't matter for hook impl)
        doc = db_session.get(ApprovalDoc, doc_id)
        doc_hooks.dispatch(db_session, doc, "rejected")
        assert (
            db_session.query(CalendarEvent)
            .filter(CalendarEvent.source_ref == doc_id)
            .first()
            is None
        )

    def test_recall_deletes_event(
        self, db_session, emp_user, travel_order_template,
        travel_calendar, dept_head, companion_a,
    ):
        doc_id = _draft_and_submit_order(
            db_session, emp_user, travel_order_template, [companion_a.id],
        )
        approval_service.approve_step(db_session, doc_id, dept_head)
        doc = db_session.get(ApprovalDoc, doc_id)
        doc_hooks.dispatch(db_session, doc, "recalled")
        assert (
            db_session.query(CalendarEvent)
            .filter(CalendarEvent.source_ref == doc_id)
            .first()
            is None
        )


# ── TRAVEL_REPORT hooks ────────────────────────────────────


class TestTravelReportApproval:
    def test_report_approved_stamps_reported_at(
        self, db_session, emp_user, travel_order_template,
        travel_report_template, travel_calendar, dept_head,
    ):
        order_id = _draft_and_submit_order(
            db_session, emp_user, travel_order_template, [],
        )
        approval_service.approve_step(db_session, order_id, dept_head)

        report_doc, report = travel_report_service.create_draft(
            db_session, user=emp_user,
            travel_order_doc_id=order_id,
            line_template_id=travel_report_template.id,
            title=None,
            report_content="출장 결과 보고",
            actual_cost=None, receipts_url=None,
        )
        travel_report_service.submit(db_session, report_doc.id, emp_user)
        approval_service.approve_step(db_session, report_doc.id, dept_head)

        db_session.refresh(report)
        assert report.reported_at is not None
