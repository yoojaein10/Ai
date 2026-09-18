"""End-to-end tests for the ATT_LEAVE doc-hook pipeline (PHASE 15-C)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.db.models import (
    ApprovalDocType,
    ApprovalLineStep,
    ApprovalLineTemplate,
    Calendar,
    CalendarEvent,
    Department,
    Employee,
    Holiday,
    LeaveBalance,
    LeaveType,
    Role,
    User,
    UserRole,
)
from app.services import approval_service, leave_request_service


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
        password_hash="x",
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
def employee_user(db_session, dept, roles, dept_head):  # dept_head ensures head exists
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
        password_hash="x",
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
def leave_types(db_session):
    day = LeaveType(
        code="ANNUAL",
        name="연차",
        deduct_from="ANNUAL",
        unit="DAY",
        is_paid=True,
        requires_evidence=False,
        sort_order=10,
    )
    db_session.add(day)
    db_session.commit()
    return {"day": day}


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
def leave_calendar(db_session):
    cal = Calendar(
        name="휴가",
        color_hex="#52c41a",
        scope="COMPANY",
        is_default=False,
    )
    db_session.add(cal)
    db_session.commit()
    return cal


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


# ── Helper ─────────────────────────────────────────────────


def _draft_and_submit(
    db_session, employee_user, leave_types, approval_template
) -> int:
    doc, _ = leave_request_service.create_draft(
        db_session,
        user=employee_user,
        leave_type_id=leave_types["day"].id,
        line_template_id=approval_template.id,
        start_date=date(2026, 4, 27),
        end_date=date(2026, 4, 27),
        half_type=None,
        title="연차 테스트",
        reason="개인사유",
        delegate_emp_id=None,
        contact_during_leave=None,
        evidence_file_url=None,
    )
    leave_request_service.submit(db_session, doc.id, employee_user)
    return doc.id


# ── Tests ──────────────────────────────────────────────────


class TestApprovalHooks:
    def test_submit_reserves_scheduled(
        self,
        db_session,
        employee_user,
        leave_types,
        approval_template,
        balance,
    ):
        _draft_and_submit(db_session, employee_user, leave_types, approval_template)
        db_session.refresh(balance)
        assert Decimal(balance.scheduled_days) == Decimal("1")
        assert Decimal(balance.used_days) == Decimal("0")

    def test_approve_consumes_balance_and_creates_event(
        self,
        db_session,
        employee_user,
        leave_types,
        approval_template,
        balance,
        leave_calendar,
        dept_head,
    ):
        doc_id = _draft_and_submit(
            db_session, employee_user, leave_types, approval_template
        )
        approval_service.approve_step(db_session, doc_id, dept_head)

        db_session.refresh(balance)
        assert Decimal(balance.used_days) == Decimal("1")
        assert Decimal(balance.scheduled_days) == Decimal("0")

        event = (
            db_session.query(CalendarEvent)
            .filter(
                CalendarEvent.source_type == "APPROVAL_DOC",
                CalendarEvent.source_ref == doc_id,
            )
            .first()
        )
        assert event is not None
        assert event.event_type == "LEAVE"
        assert event.owner_id == employee_user.employee_id
        assert event.all_day is True

    def test_reject_releases_scheduled(
        self,
        db_session,
        employee_user,
        leave_types,
        approval_template,
        balance,
        dept_head,
    ):
        doc_id = _draft_and_submit(
            db_session, employee_user, leave_types, approval_template
        )
        approval_service.reject_step(db_session, doc_id, dept_head, comment="사유 미흡")

        db_session.refresh(balance)
        assert Decimal(balance.scheduled_days) == Decimal("0")
        assert Decimal(balance.used_days) == Decimal("0")

    def test_recall_releases_scheduled(
        self,
        db_session,
        employee_user,
        leave_types,
        approval_template,
        balance,
    ):
        doc_id = _draft_and_submit(
            db_session, employee_user, leave_types, approval_template
        )
        leave_request_service.cancel(db_session, doc_id, employee_user)

        db_session.refresh(balance)
        assert Decimal(balance.scheduled_days) == Decimal("0")
        assert Decimal(balance.used_days) == Decimal("0")

    def test_approve_event_idempotent(
        self,
        db_session,
        employee_user,
        leave_types,
        approval_template,
        balance,
        leave_calendar,
        dept_head,
    ):
        """Calling the hook twice for the same doc must not create a duplicate."""
        doc_id = _draft_and_submit(
            db_session, employee_user, leave_types, approval_template
        )
        approval_service.approve_step(db_session, doc_id, dept_head)

        # Simulate a re-dispatch (should update-in-place, not duplicate)
        from app.db.models import ApprovalDoc
        from app.services import doc_hooks

        doc = db_session.get(ApprovalDoc, doc_id)
        doc_hooks.dispatch(db_session, doc, "approved")

        events = (
            db_session.query(CalendarEvent)
            .filter(
                CalendarEvent.source_type == "APPROVAL_DOC",
                CalendarEvent.source_ref == doc_id,
            )
            .all()
        )
        assert len(events) == 1
