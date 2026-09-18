"""Tests for leave_request_service (PHASE 15-B)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.db.models import (
    ApprovalDocType,
    ApprovalLineStep,
    ApprovalLineTemplate,
    Department,
    Employee,
    Holiday,
    LeaveBalance,
    LeaveType,
    Role,
    User,
    UserRole,
)
from app.services import leave_request_service as svc


# ── Fixtures ───────────────────────────────────────────────


@pytest.fixture
def kids_day(db_session):
    h = Holiday(date=date(2000, 5, 5), name="어린이날", is_recurring=True)
    db_session.add(h)
    db_session.commit()
    return h


@pytest.fixture
def dept(db_session):
    d = Department(code="DEV", name="개발팀")
    db_session.add(d)
    db_session.flush()
    return d


@pytest.fixture
def employee(db_session, dept):
    e = Employee(
        emp_no="E0001",
        name_ko="홍길동",
        hire_date=date(2020, 1, 1),
        dept_id=dept.id,
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
        login_id=employee.emp_no,
        password_hash="x",
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
def leave_types(db_session):
    lt_day = LeaveType(
        code="ANNUAL",
        name="연차",
        deduct_from="ANNUAL",
        unit="DAY",
        is_paid=True,
        requires_evidence=False,
        sort_order=10,
    )
    lt_half = LeaveType(
        code="HALF_AM",
        name="오전반차",
        deduct_from="ANNUAL",
        unit="HALF_DAY",
        is_paid=True,
        requires_evidence=False,
        sort_order=20,
    )
    lt_sick = LeaveType(
        code="SICK",
        name="병가",
        deduct_from="SEPARATE",
        unit="DAY",
        is_paid=True,
        requires_evidence=True,
        sort_order=30,
    )
    db_session.add_all([lt_day, lt_half, lt_sick])
    db_session.commit()
    return {"day": lt_day, "half": lt_half, "sick": lt_sick}


@pytest.fixture
def approval_config(db_session):
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
    return {"doc_type": dt, "template": tmpl}


@pytest.fixture
def balance(db_session, employee):
    b = LeaveBalance(
        emp_id=employee.id,
        year=date.today().year,
        initial_days=Decimal("15"),
        used_days=Decimal("0"),
        scheduled_days=Decimal("0"),
    )
    db_session.add(b)
    db_session.commit()
    return b


# ── calculate_days ─────────────────────────────────────────


class TestCalculateDays:
    def test_single_weekday_day_unit(self, db_session, leave_types):
        res = svc.calculate_days(
            db_session,
            leave_type=leave_types["day"],
            start_date=date(2026, 4, 27),  # Mon
            end_date=date(2026, 4, 27),
            half_type=None,
        )
        assert res["days"] == Decimal("1")
        assert res["business_days"] == 1
        assert res["excluded_holidays"] == []
        assert res["unit"] == "DAY"

    def test_week_range_excludes_weekend(self, db_session, leave_types):
        res = svc.calculate_days(
            db_session,
            leave_type=leave_types["day"],
            start_date=date(2026, 4, 27),  # Mon
            end_date=date(2026, 5, 3),  # Sun
            half_type=None,
        )
        assert res["business_days"] == 5
        assert res["days"] == Decimal("5")

    def test_week_range_with_holiday(self, db_session, leave_types, kids_day):
        res = svc.calculate_days(
            db_session,
            leave_type=leave_types["day"],
            start_date=date(2026, 5, 4),
            end_date=date(2026, 5, 8),
            half_type=None,
        )
        assert res["business_days"] == 4
        assert res["excluded_holidays"] == [date(2026, 5, 5)]

    def test_half_day_ok(self, db_session, leave_types):
        res = svc.calculate_days(
            db_session,
            leave_type=leave_types["half"],
            start_date=date(2026, 4, 27),
            end_date=date(2026, 4, 27),
            half_type="AM",
        )
        assert res["days"] == Decimal("0.5")
        assert res["business_days"] == 1

    def test_half_day_range_rejected(self, db_session, leave_types):
        with pytest.raises(svc.LeaveRequestInvalid):
            svc.calculate_days(
                db_session,
                leave_type=leave_types["half"],
                start_date=date(2026, 4, 27),
                end_date=date(2026, 4, 28),
                half_type="AM",
            )

    def test_half_day_missing_half_type(self, db_session, leave_types):
        with pytest.raises(svc.LeaveRequestInvalid):
            svc.calculate_days(
                db_session,
                leave_type=leave_types["half"],
                start_date=date(2026, 4, 27),
                end_date=date(2026, 4, 27),
                half_type=None,
            )

    def test_half_day_on_weekend_rejected(self, db_session, leave_types):
        with pytest.raises(svc.LeaveRequestInvalid):
            svc.calculate_days(
                db_session,
                leave_type=leave_types["half"],
                start_date=date(2026, 4, 25),  # Sat
                end_date=date(2026, 4, 25),
                half_type="AM",
            )

    def test_start_after_end_rejected(self, db_session, leave_types):
        with pytest.raises(svc.LeaveRequestInvalid):
            svc.calculate_days(
                db_session,
                leave_type=leave_types["day"],
                start_date=date(2026, 5, 5),
                end_date=date(2026, 5, 1),
                half_type=None,
            )


# ── create_draft / submit / cancel ─────────────────────────


class TestDraftSubmitCancel:
    def test_create_draft_day(
        self,
        db_session,
        leave_types,
        approval_config,
        balance,
        emp_user,
    ):
        doc, detail = svc.create_draft(
            db_session,
            user=emp_user,
            leave_type_id=leave_types["day"].id,
            line_template_id=approval_config["template"].id,
            start_date=date(2026, 4, 27),
            end_date=date(2026, 4, 27),
            half_type=None,
            title=None,
            reason="개인사유",
            delegate_emp_id=None,
            contact_during_leave=None,
            evidence_file_url=None,
        )
        assert doc.status == "DRAFT"
        assert detail.days == Decimal("1")
        # balance not reserved yet
        db_session.refresh(balance)
        assert Decimal(balance.scheduled_days) == Decimal("0")

    def test_insufficient_balance_rejects_draft(
        self,
        db_session,
        leave_types,
        approval_config,
        emp_user,
        employee,
    ):
        bal = LeaveBalance(
            emp_id=employee.id,
            year=date.today().year,
            initial_days=Decimal("0.5"),
        )
        db_session.add(bal)
        db_session.commit()

        with pytest.raises(svc.InsufficientLeaveBalance):
            svc.create_draft(
                db_session,
                user=emp_user,
                leave_type_id=leave_types["day"].id,
                line_template_id=approval_config["template"].id,
                start_date=date(2026, 4, 27),
                end_date=date(2026, 5, 1),  # 5 business days
                half_type=None,
                title=None,
                reason=None,
                delegate_emp_id=None,
                contact_during_leave=None,
                evidence_file_url=None,
            )

    def test_separate_type_skips_annual_balance_check(
        self,
        db_session,
        leave_types,
        approval_config,
        emp_user,
    ):
        # No LeaveBalance row — SICK is SEPARATE, must still succeed
        doc, detail = svc.create_draft(
            db_session,
            user=emp_user,
            leave_type_id=leave_types["sick"].id,
            line_template_id=approval_config["template"].id,
            start_date=date(2026, 4, 27),
            end_date=date(2026, 4, 27),
            half_type=None,
            title=None,
            reason="감기",
            delegate_emp_id=None,
            contact_during_leave=None,
            evidence_file_url=None,
        )
        assert doc.status == "DRAFT"
        assert detail.days == Decimal("1")

    def test_cancel_draft_deletes_detail(
        self,
        db_session,
        leave_types,
        approval_config,
        balance,
        emp_user,
    ):
        doc, detail = svc.create_draft(
            db_session,
            user=emp_user,
            leave_type_id=leave_types["day"].id,
            line_template_id=approval_config["template"].id,
            start_date=date(2026, 4, 27),
            end_date=date(2026, 4, 27),
            half_type=None,
            title=None,
            reason=None,
            delegate_emp_id=None,
            contact_during_leave=None,
            evidence_file_url=None,
        )
        doc_id = doc.id
        svc.cancel(db_session, doc_id, emp_user)
        from app.db.models import ApprovalDoc, LeaveRequestDetail

        assert db_session.get(ApprovalDoc, doc_id) is None
        assert (
            db_session.query(LeaveRequestDetail)
            .filter(LeaveRequestDetail.doc_id == doc_id)
            .first()
            is None
        )

    def test_list_my_returns_owner_rows(
        self,
        db_session,
        leave_types,
        approval_config,
        balance,
        emp_user,
    ):
        svc.create_draft(
            db_session,
            user=emp_user,
            leave_type_id=leave_types["day"].id,
            line_template_id=approval_config["template"].id,
            start_date=date(2026, 4, 27),
            end_date=date(2026, 4, 27),
            half_type=None,
            title="자기 계발",
            reason=None,
            delegate_emp_id=None,
            contact_during_leave=None,
            evidence_file_url=None,
        )
        rows = svc.list_my(db_session, user=emp_user)
        assert len(rows) == 1
        assert rows[0]["title"] == "자기 계발"
        assert rows[0]["drafter_name"] == "홍길동"
        assert rows[0]["dept_name"] == "개발팀"
