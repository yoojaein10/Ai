"""Tests for holiday_service (PHASE 15-A)."""

from __future__ import annotations

from datetime import date

import pytest

from app.db.models import Holiday
from app.services import holiday_service as svc


# ── Fixtures ───────────────────────────────────────────────


@pytest.fixture
def recurring_jan1(db_session):
    h = Holiday(date=date(2000, 1, 1), name="신정", is_recurring=True)
    db_session.add(h)
    db_session.commit()
    return h


@pytest.fixture
def lunar_seollal_2026(db_session):
    # 2026 lunar new year: Feb 17 (example)
    h = Holiday(date=date(2026, 2, 17), name="설날", is_recurring=False)
    db_session.add(h)
    db_session.commit()
    return h


@pytest.fixture
def kids_day(db_session):
    h = Holiday(date=date(2000, 5, 5), name="어린이날", is_recurring=True)
    db_session.add(h)
    db_session.commit()
    return h


# ── is_holiday ─────────────────────────────────────────────


class TestIsHoliday:
    def test_recurring_matches_any_year(self, db_session, recurring_jan1):
        assert svc.is_holiday(db_session, date(2025, 1, 1)) is True
        assert svc.is_holiday(db_session, date(2030, 1, 1)) is True
        assert svc.is_holiday(db_session, date(2025, 1, 2)) is False

    def test_non_recurring_only_in_stored_year(
        self, db_session, lunar_seollal_2026
    ):
        assert svc.is_holiday(db_session, date(2026, 2, 17)) is True
        assert svc.is_holiday(db_session, date(2025, 2, 17)) is False

    def test_is_weekend(self):
        assert svc.is_weekend(date(2026, 4, 25)) is True  # Saturday
        assert svc.is_weekend(date(2026, 4, 26)) is True  # Sunday
        assert svc.is_weekend(date(2026, 4, 27)) is False  # Monday


# ── business_days ──────────────────────────────────────────


class TestBusinessDays:
    def test_single_weekday_no_holiday(self, db_session):
        d = date(2026, 4, 27)  # Mon
        assert svc.business_days(db_session, d, d) == 1

    def test_single_weekend(self, db_session):
        d = date(2026, 4, 25)  # Sat
        assert svc.business_days(db_session, d, d) == 0

    def test_weekday_that_is_holiday(self, db_session, kids_day):
        # 2026-05-05 Tuesday → 어린이날
        d = date(2026, 5, 5)
        assert svc.business_days(db_session, d, d) == 0

    def test_week_range(self, db_session):
        # Mon 4/27 — Sun 5/3 → 5 business days (no holiday in this range)
        start = date(2026, 4, 27)
        end = date(2026, 5, 3)
        assert svc.business_days(db_session, start, end) == 5

    def test_week_range_with_holiday(self, db_session, kids_day):
        # Mon 5/4 — Fri 5/8 → 5 weekdays, minus 5/5 어린이날 = 4
        start = date(2026, 5, 4)
        end = date(2026, 5, 8)
        assert svc.business_days(db_session, start, end) == 4

    def test_start_greater_than_end(self, db_session):
        assert (
            svc.business_days(db_session, date(2026, 5, 10), date(2026, 5, 1))
            == 0
        )

    def test_range_crosses_year(self, db_session, recurring_jan1):
        # 2025-12-29 Mon — 2026-01-05 Mon. New Year 1/1 (Thu, recurring) skipped.
        start = date(2025, 12, 29)
        end = date(2026, 1, 5)
        # Weekdays: 12/29 Mon, 12/30 Tue, 12/31 Wed, 1/1 Thu(holiday),
        # 1/2 Fri, 1/5 Mon = 6 business days minus holiday = 5.
        assert svc.business_days(db_session, start, end) == 5


# ── CRUD ────────────────────────────────────────────────────


class TestCRUD:
    def test_create_and_list(self, db_session):
        svc.create_holiday(
            db_session, on=date(2026, 8, 15), name="광복절", is_recurring=True
        )
        items = svc.list_holidays(db_session, year=2026)
        assert any(h.name == "광복절" for h in items)

    def test_duplicate_rejected(self, db_session):
        svc.create_holiday(db_session, on=date(2026, 8, 15), name="광복절")
        with pytest.raises(svc.HolidayDuplicate):
            svc.create_holiday(db_session, on=date(2026, 8, 15), name="dup")

    def test_delete(self, db_session):
        h = svc.create_holiday(
            db_session, on=date(2026, 3, 1), name="삼일절", is_recurring=True
        )
        svc.delete_holiday(db_session, h.id)
        assert (
            db_session.query(Holiday).filter(Holiday.id == h.id).first() is None
        )

    def test_delete_missing(self, db_session):
        with pytest.raises(svc.HolidayNotFound):
            svc.delete_holiday(db_session, 99999)

    def test_list_by_year_includes_recurring(
        self, db_session, recurring_jan1, lunar_seollal_2026
    ):
        items = svc.list_holidays(db_session, year=2026)
        names = {h.name for h in items}
        assert "신정" in names  # recurring
        assert "설날" in names  # year-specific 2026

    def test_list_by_year_excludes_other_year_non_recurring(
        self, db_session, lunar_seollal_2026
    ):
        items = svc.list_holidays(db_session, year=2025)
        names = {h.name for h in items}
        assert "설날" not in names
