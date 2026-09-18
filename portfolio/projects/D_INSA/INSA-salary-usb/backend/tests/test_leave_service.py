"""Tests for leave_service (PHASE 14).

Coverage targets:
- `calculate_initial_days` across tenure edge cases (8+ scenarios)
- `create_initial_balance` idempotency
- `monthly_accrual` idempotency + max cap + tenure-gated eligibility
- `yearly_reset` expire vs carry-over (global + per-employee exempt)
- `consume_leave` / `release_leave` with INSUFFICIENT BALANCE + row lock
- `adjust_balance` positive/negative + negative-balance guard
- Transaction ledger `balance_after` snapshot correctness
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.db.models import (
    Department,
    Employee,
    LeaveAccrualRule,
    LeaveBalance,
    LeaveTransaction,
)
from app.services.leave_service import (
    InsufficientBalance,
    LeaveInvalid,
    LeaveNotFound,
    adjust_balance,
    calculate_initial_days,
    completed_years,
    consume_leave,
    create_initial_balance,
    get_balance_remaining,
    monthly_accrual,
    release_leave,
    set_carry_over_exempt,
    yearly_reset,
)


# ── Fixtures ──────────────────────────────────────────────────


def _rule(year: int = 2026, **overrides) -> LeaveAccrualRule:
    defaults = dict(
        year=year,
        under_1year_monthly=1,
        under_1year_max=11,
        base_days=15,
        tenure_bonus_start_years=3,
        tenure_bonus_interval=2,
        max_days=25,
        carry_over_enabled=False,
    )
    defaults.update(overrides)
    return LeaveAccrualRule(**defaults)


@pytest.fixture
def dept(db_session):
    d = Department(code="DEV", name="개발팀")
    db_session.add(d)
    db_session.flush()
    return d


@pytest.fixture
def seeded(db_session, dept):
    """Install rule + one rule-gated seed helper."""
    db_session.add(_rule(2026))
    db_session.add(_rule(2025))
    db_session.commit()
    return db_session


def _emp(db_session, dept, emp_no: str, hire_date: date, name: str = "홍길동") -> Employee:
    e = Employee(
        emp_no=emp_no,
        name_ko=name,
        gender="M",
        birth_date=date(1990, 1, 1),
        hire_date=hire_date,
        hire_type="신규",
        workplace="본사",
        work_location="서울",
        dept_id=dept.id,
        job_rank="사원",
        job_position="팀원",
        emp_type="정규직",
    )
    db_session.add(e)
    db_session.flush()
    return e


# ── calculate_initial_days: 8+ tenure edge cases ────────────────


class TestCalculateInitialDays:
    def test_not_yet_hired_returns_zero(self):
        rule = _rule(2026)
        assert calculate_initial_days(date(2026, 6, 1), 2026, rule) == Decimal("0")

    def test_hired_same_day_as_year_start(self):
        # Hired 2026-01-01 — 0 completed years at 2026-01-01 → monthly mode
        rule = _rule(2026)
        assert calculate_initial_days(date(2026, 1, 1), 2026, rule) == Decimal("0")

    def test_under_1yr_returns_zero(self):
        # Hired 2025-06-01 — 7 months tenure at 2026-01-01 → monthly mode
        rule = _rule(2026)
        assert calculate_initial_days(date(2025, 6, 1), 2026, rule) == Decimal("0")

    def test_just_over_1yr(self):
        # Hired 2024-12-31 — 1 completed year at 2026-01-01 → base 15
        rule = _rule(2026)
        assert calculate_initial_days(date(2024, 12, 31), 2026, rule) == Decimal("15")

    def test_2yr_tenure_base_only(self):
        rule = _rule(2026)
        # Hired 2023-06-01 — 2 completed years at 2026-01-01 → 15 (no bonus yet)
        assert calculate_initial_days(date(2023, 6, 1), 2026, rule) == Decimal("15")

    def test_3yr_tenure_first_bonus(self):
        rule = _rule(2026)
        # Hired 2022-12-31 — 3 completed years → 15+1=16
        assert calculate_initial_days(date(2022, 12, 31), 2026, rule) == Decimal("16")

    def test_5yr_tenure(self):
        rule = _rule(2026)
        # Hired 2020-12-31 — 5 completed years → 15+2=17
        assert calculate_initial_days(date(2020, 12, 31), 2026, rule) == Decimal("17")

    def test_21yr_caps_at_max_25(self):
        rule = _rule(2026)
        # Hired 2004-12-31 — 21 completed years → raw 15 + 10 = 25, cap 25
        assert calculate_initial_days(date(2004, 12, 31), 2026, rule) == Decimal("25")

    def test_30yr_capped_at_max_25(self):
        rule = _rule(2026)
        # Hired 1995-01-01 — 31 completed years → raw 15 + 15 = 30, capped 25
        assert calculate_initial_days(date(1995, 1, 1), 2026, rule) == Decimal("25")

    def test_leap_day_hire_feb29(self):
        rule = _rule(2026)
        # Hired 2020-02-29. At 2026-01-01: (1,1) < (2,29) → years = 6-1 = 5 → 17
        assert calculate_initial_days(date(2020, 2, 29), 2026, rule) == Decimal("17")

    def test_leap_day_hire_in_leap_year_check(self):
        rule = _rule(2024)
        # Hired 2020-02-29. At 2024-01-01: (1,1)<(2,29) → 4-1=3 → 16
        assert calculate_initial_days(date(2020, 2, 29), 2024, rule) == Decimal("16")

    def test_completed_years_helper_leap_edge(self):
        # completed_years on 2/29 hire at 2/28 non-leap → still 0 years
        assert completed_years(date(2020, 2, 29), date(2021, 2, 28)) == 0
        # at 3/1 non-leap → 1 year
        assert completed_years(date(2020, 2, 29), date(2021, 3, 1)) == 1

    def test_custom_rule_overrides(self):
        rule = _rule(2026, base_days=20, tenure_bonus_start_years=5, max_days=30)
        # Hired 2020-01-01 → 6 yrs at 2026-01-01 → (6-5)//2+1 = 1 → 21
        assert calculate_initial_days(date(2020, 1, 1), 2026, rule) == Decimal("21")


# ── create_initial_balance: idempotency ───────────────────────


class TestCreateInitialBalance:
    def test_creates_balance_and_transaction(self, seeded, dept):
        emp = _emp(seeded, dept, "E001", date(2022, 1, 1))

        bal = create_initial_balance(seeded, emp.id, 2026)
        assert bal.initial_days == Decimal("16")  # 4 years → 15+1

        txs = (
            seeded.query(LeaveTransaction)
            .filter(LeaveTransaction.emp_id == emp.id)
            .all()
        )
        assert len(txs) == 1
        assert txs[0].transaction_type == "INITIAL_GRANT"
        assert txs[0].amount == Decimal("16")
        assert txs[0].balance_after == Decimal("16")

    def test_idempotent(self, seeded, dept):
        emp = _emp(seeded, dept, "E002", date(2022, 1, 1))
        create_initial_balance(seeded, emp.id, 2026)
        create_initial_balance(seeded, emp.id, 2026)
        create_initial_balance(seeded, emp.id, 2026)

        txs = (
            seeded.query(LeaveTransaction)
            .filter(LeaveTransaction.emp_id == emp.id)
            .all()
        )
        assert len(txs) == 1

    def test_no_rule_raises(self, db_session, dept):
        emp = _emp(db_session, dept, "E003", date(2022, 1, 1))
        db_session.commit()
        with pytest.raises(LeaveNotFound):
            create_initial_balance(db_session, emp.id, 2030)

    def test_missing_employee_raises(self, seeded):
        with pytest.raises(LeaveNotFound):
            create_initial_balance(seeded, 99999, 2026)


# ── monthly_accrual ────────────────────────────────────────────


class TestMonthlyAccrual:
    def test_grants_to_under_1yr_employees(self, seeded, dept):
        emp_new = _emp(seeded, dept, "N001", date(2025, 6, 1))
        emp_old = _emp(seeded, dept, "O001", date(2020, 1, 1))

        granted = monthly_accrual(seeded, 2026, 1)
        assert granted == 1  # only the <1yr employee

        bal_new = (
            seeded.query(LeaveBalance)
            .filter_by(emp_id=emp_new.id, year=2026)
            .first()
        )
        assert bal_new.additional_days == Decimal("1")

        bal_old = (
            seeded.query(LeaveBalance)
            .filter_by(emp_id=emp_old.id, year=2026)
            .first()
        )
        assert bal_old is None  # old employee not touched by monthly

    def test_skips_unhired_employees(self, seeded, dept):
        emp = _emp(seeded, dept, "F001", date(2026, 3, 15))
        granted = monthly_accrual(seeded, 2026, 1)
        assert granted == 0

        bal = (
            seeded.query(LeaveBalance)
            .filter_by(emp_id=emp.id, year=2026)
            .first()
        )
        assert bal is None

    def test_idempotent_same_month(self, seeded, dept):
        _emp(seeded, dept, "N002", date(2025, 6, 1))
        granted1 = monthly_accrual(seeded, 2026, 2)
        granted2 = monthly_accrual(seeded, 2026, 2)
        assert granted1 == 1
        assert granted2 == 0  # lock prevents re-run

    def test_multiple_months_accumulate(self, seeded, dept):
        emp = _emp(seeded, dept, "N003", date(2025, 6, 1))
        monthly_accrual(seeded, 2026, 1)
        monthly_accrual(seeded, 2026, 2)
        monthly_accrual(seeded, 2026, 3)
        bal = (
            seeded.query(LeaveBalance)
            .filter_by(emp_id=emp.id, year=2026)
            .first()
        )
        assert bal.additional_days == Decimal("3")

    def test_capped_at_max_11(self, seeded, dept):
        emp = _emp(seeded, dept, "N004", date(2025, 6, 1))
        for m in range(1, 13):
            monthly_accrual(seeded, 2026, m)
        bal = (
            seeded.query(LeaveBalance)
            .filter_by(emp_id=emp.id, year=2026)
            .first()
        )
        assert bal.additional_days == Decimal("11")

    def test_invalid_month(self, seeded):
        with pytest.raises(LeaveInvalid):
            monthly_accrual(seeded, 2026, 0)
        with pytest.raises(LeaveInvalid):
            monthly_accrual(seeded, 2026, 13)


# ── yearly_reset ───────────────────────────────────────────────


class TestYearlyReset:
    def test_expires_by_default(self, seeded, dept):
        emp = _emp(seeded, dept, "R001", date(2020, 1, 1))
        bal = LeaveBalance(
            emp_id=emp.id,
            year=2025,
            initial_days=Decimal("15"),
            used_days=Decimal("5"),
        )
        seeded.add(bal)
        seeded.commit()

        result = yearly_reset(seeded, 2026)
        assert result["status"] == "ok"
        assert result["expired"] == 1
        assert result["carried"] == 0

        # Prev year balance fully consumed (expired)
        prev = (
            seeded.query(LeaveBalance)
            .filter_by(emp_id=emp.id, year=2025)
            .first()
        )
        assert get_balance_remaining(prev) == Decimal("0")

        # Expire transaction exists
        expire_tx = (
            seeded.query(LeaveTransaction)
            .filter_by(emp_id=emp.id, transaction_type="EXPIRE")
            .first()
        )
        assert expire_tx is not None
        assert expire_tx.amount == Decimal("-10")

        # New year balance granted
        new = (
            seeded.query(LeaveBalance)
            .filter_by(emp_id=emp.id, year=2026)
            .first()
        )
        # 6 years → (6-3)//2+1 = 2 bonus → 17
        assert new.initial_days == Decimal("17")

    def test_carry_over_exempt_employee(self, seeded, dept):
        emp = _emp(seeded, dept, "R002", date(2020, 1, 1))
        bal = LeaveBalance(
            emp_id=emp.id,
            year=2025,
            initial_days=Decimal("15"),
            used_days=Decimal("5"),
            carry_over_exempt=True,
        )
        seeded.add(bal)
        seeded.commit()

        result = yearly_reset(seeded, 2026)
        assert result["carried"] == 1
        assert result["expired"] == 0

        new = (
            seeded.query(LeaveBalance)
            .filter_by(emp_id=emp.id, year=2026)
            .first()
        )
        assert new.carried_over_days == Decimal("10")
        # Plus initial grant
        assert new.initial_days == Decimal("17")

    def test_global_carry_over_enabled(self, db_session, dept):
        db_session.add(_rule(2025, carry_over_enabled=True))
        db_session.add(_rule(2026))
        emp = _emp(db_session, dept, "R003", date(2020, 1, 1))
        bal = LeaveBalance(
            emp_id=emp.id,
            year=2025,
            initial_days=Decimal("15"),
            used_days=Decimal("3"),
        )
        db_session.add(bal)
        db_session.commit()

        result = yearly_reset(db_session, 2026)
        assert result["carried"] == 1

        new = (
            db_session.query(LeaveBalance)
            .filter_by(emp_id=emp.id, year=2026)
            .first()
        )
        assert new.carried_over_days == Decimal("12")

    def test_idempotent(self, seeded, dept):
        _emp(seeded, dept, "R004", date(2020, 1, 1))
        result1 = yearly_reset(seeded, 2026)
        result2 = yearly_reset(seeded, 2026)
        assert result1["status"] == "ok"
        assert result2["status"] == "skipped"


# ── consume_leave / release_leave ──────────────────────────────


class TestConsumeRelease:
    def test_basic_consume(self, seeded, dept):
        emp = _emp(seeded, dept, "C001", date(2020, 1, 1))
        create_initial_balance(seeded, emp.id, 2026)

        tx = consume_leave(
            seeded, emp.id, Decimal("3"), ref_doc_id=100, year=2026
        )
        assert tx.transaction_type == "USE"
        assert tx.amount == Decimal("-3")

        bal = (
            seeded.query(LeaveBalance)
            .filter_by(emp_id=emp.id, year=2026)
            .first()
        )
        assert bal.used_days == Decimal("3")
        # 17 initial (6yr) - 3 = 14
        assert get_balance_remaining(bal) == Decimal("14")

    def test_insufficient_balance_blocks(self, seeded, dept):
        emp = _emp(seeded, dept, "C002", date(2020, 1, 1))
        create_initial_balance(seeded, emp.id, 2026)
        with pytest.raises(InsufficientBalance):
            consume_leave(seeded, emp.id, Decimal("100"), year=2026)

    def test_negative_days_invalid(self, seeded, dept):
        emp = _emp(seeded, dept, "C003", date(2020, 1, 1))
        create_initial_balance(seeded, emp.id, 2026)
        with pytest.raises(LeaveInvalid):
            consume_leave(seeded, emp.id, Decimal("-1"), year=2026)
        with pytest.raises(LeaveInvalid):
            consume_leave(seeded, emp.id, Decimal("0"), year=2026)

    def test_no_balance_raises(self, seeded, dept):
        emp = _emp(seeded, dept, "C004", date(2020, 1, 1))
        with pytest.raises(LeaveNotFound):
            consume_leave(seeded, emp.id, Decimal("1"), year=2026)

    def test_release_reverses_use(self, seeded, dept):
        emp = _emp(seeded, dept, "C005", date(2020, 1, 1))
        create_initial_balance(seeded, emp.id, 2026)
        consume_leave(seeded, emp.id, Decimal("5"), ref_doc_id=200, year=2026)

        cnt = release_leave(seeded, 200)
        assert cnt == 1

        bal = (
            seeded.query(LeaveBalance)
            .filter_by(emp_id=emp.id, year=2026)
            .first()
        )
        assert bal.used_days == Decimal("0")

    def test_release_idempotent(self, seeded, dept):
        emp = _emp(seeded, dept, "C006", date(2020, 1, 1))
        create_initial_balance(seeded, emp.id, 2026)
        consume_leave(seeded, emp.id, Decimal("2"), ref_doc_id=300, year=2026)
        release_leave(seeded, 300)
        cnt = release_leave(seeded, 300)
        assert cnt == 0  # no new USE rows to cancel

    def test_half_day_consume(self, seeded, dept):
        emp = _emp(seeded, dept, "C007", date(2020, 1, 1))
        create_initial_balance(seeded, emp.id, 2026)
        tx = consume_leave(
            seeded, emp.id, Decimal("0.5"), ref_doc_id=400, year=2026
        )
        assert tx.amount == Decimal("-0.5")

    def test_balance_after_accumulates(self, seeded, dept):
        emp = _emp(seeded, dept, "C008", date(2020, 1, 1))
        create_initial_balance(seeded, emp.id, 2026)
        tx1 = consume_leave(seeded, emp.id, Decimal("3"), year=2026)
        tx2 = consume_leave(seeded, emp.id, Decimal("4"), year=2026)
        # 17 - 3 = 14, 14 - 4 = 10
        assert tx1.balance_after == Decimal("14")
        assert tx2.balance_after == Decimal("10")


# ── adjust_balance ─────────────────────────────────────────────


class TestAdjust:
    def test_positive_adjustment(self, seeded, dept):
        emp = _emp(seeded, dept, "A001", date(2020, 1, 1))
        create_initial_balance(seeded, emp.id, 2026)
        tx = adjust_balance(seeded, emp.id, Decimal("5"), "포상", year=2026)
        assert tx.amount == Decimal("5")
        assert tx.transaction_type == "ADJUST"

        bal = (
            seeded.query(LeaveBalance)
            .filter_by(emp_id=emp.id, year=2026)
            .first()
        )
        # 17 initial + 5 additional = 22
        assert get_balance_remaining(bal) == Decimal("22")

    def test_negative_adjustment_within_balance(self, seeded, dept):
        emp = _emp(seeded, dept, "A002", date(2020, 1, 1))
        create_initial_balance(seeded, emp.id, 2026)
        adjust_balance(seeded, emp.id, Decimal("-2"), "조정차감", year=2026)
        bal = (
            seeded.query(LeaveBalance)
            .filter_by(emp_id=emp.id, year=2026)
            .first()
        )
        assert get_balance_remaining(bal) == Decimal("15")

    def test_negative_adjustment_exceeds_balance(self, seeded, dept):
        emp = _emp(seeded, dept, "A003", date(2020, 1, 1))
        create_initial_balance(seeded, emp.id, 2026)
        with pytest.raises(InsufficientBalance):
            adjust_balance(seeded, emp.id, Decimal("-100"), "excess", year=2026)

    def test_zero_amount_invalid(self, seeded, dept):
        emp = _emp(seeded, dept, "A004", date(2020, 1, 1))
        create_initial_balance(seeded, emp.id, 2026)
        with pytest.raises(LeaveInvalid):
            adjust_balance(seeded, emp.id, Decimal("0"), "x", year=2026)

    def test_empty_reason_invalid(self, seeded, dept):
        emp = _emp(seeded, dept, "A005", date(2020, 1, 1))
        create_initial_balance(seeded, emp.id, 2026)
        with pytest.raises(LeaveInvalid):
            adjust_balance(seeded, emp.id, Decimal("1"), "   ", year=2026)


class TestSetCarryOverExempt:
    def test_toggle_exempt(self, seeded, dept):
        emp = _emp(seeded, dept, "X001", date(2020, 1, 1))
        bal = set_carry_over_exempt(seeded, emp.id, 2026, True)
        assert bal.carry_over_exempt is True
        bal2 = set_carry_over_exempt(seeded, emp.id, 2026, False)
        assert bal2.carry_over_exempt is False
