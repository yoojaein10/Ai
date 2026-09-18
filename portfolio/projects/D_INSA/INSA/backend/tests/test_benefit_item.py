from datetime import date
from decimal import Decimal

import pytest

from app.db.models import BenefitEvent, BenefitItem, Employee
from app.schemas.benefit import BenefitItemCreate, BenefitItemUpdate
from app.services import benefit_item as svc


@pytest.fixture
def emp(db_session):
    e = Employee(emp_no="BI001", name_ko="홍길동", hire_date=date(2020, 1, 1))
    db_session.add(e)
    db_session.commit()
    return e


@pytest.fixture
def item_marriage(db_session):
    it = svc.create_item(db_session, BenefitItemCreate(
        code="M-001", name="결혼축하금", category="경조",
        event_type="결혼", default_amount=Decimal("500000"),
        default_leave_days=Decimal("5.0"),
    ))
    return it


@pytest.fixture
def item_birth(db_session):
    return svc.create_item(db_session, BenefitItemCreate(
        code="B-001", name="출산축하금", category="경조",
        event_type="출산", default_amount=Decimal("300000"),
    ))


@pytest.fixture
def item_med(db_session):
    return svc.create_item(db_session, BenefitItemCreate(
        code="MED-001", name="의료비지원", category="의료", is_active=False,
    ))


# ── list ──────────────────────────────────────────────────


def test_list_all_no_filter(db_session, item_marriage, item_birth, item_med):
    rows = svc.list_items(db_session)
    assert len(rows) == 3


def test_list_filter_by_category(db_session, item_marriage, item_birth, item_med):
    rows = svc.list_items(db_session, category="경조")
    assert len(rows) == 2
    assert {r.code for r in rows} == {"M-001", "B-001"}


def test_list_filter_by_active(db_session, item_marriage, item_med):
    active = svc.list_items(db_session, is_active=True)
    inactive = svc.list_items(db_session, is_active=False)
    assert all(r.is_active for r in active)
    assert all(not r.is_active for r in inactive)


def test_list_keyword_matches_code_or_name(db_session, item_marriage, item_birth):
    by_code = svc.list_items(db_session, keyword="M-001")
    by_name = svc.list_items(db_session, keyword="출산")
    assert {r.code for r in by_code} == {"M-001"}
    assert {r.code for r in by_name} == {"B-001"}


def test_list_orders_by_category_then_code(db_session, item_marriage, item_birth, item_med):
    rows = svc.list_items(db_session)
    pairs = [(r.category, r.code) for r in rows]
    assert pairs == sorted(pairs)


# ── get ───────────────────────────────────────────────────


def test_get_item_by_id(db_session, item_marriage):
    found = svc.get_item(db_session, item_marriage.id)
    assert found is not None
    assert found.code == "M-001"


def test_get_item_not_found(db_session):
    assert svc.get_item(db_session, 99999) is None


def test_get_item_by_code(db_session, item_marriage):
    assert svc.get_item_by_code(db_session, "M-001").id == item_marriage.id
    assert svc.get_item_by_code(db_session, "missing") is None


# ── update ────────────────────────────────────────────────


def test_update_partial_fields(db_session, item_marriage):
    updated = svc.update_item(
        db_session, item_marriage.id,
        BenefitItemUpdate(name="결혼축하금(개정)", default_amount=Decimal("600000")),
    )
    assert updated.name == "결혼축하금(개정)"
    assert updated.default_amount == Decimal("600000")
    assert updated.code == "M-001"


def test_update_not_found(db_session):
    assert svc.update_item(db_session, 99999, BenefitItemUpdate(name="x")) is None


def test_update_can_deactivate(db_session, item_marriage):
    updated = svc.update_item(db_session, item_marriage.id, BenefitItemUpdate(is_active=False))
    assert updated.is_active is False


# ── delete ────────────────────────────────────────────────


def test_delete_not_found(db_session):
    ok, msg = svc.delete_item(db_session, 99999)
    assert ok is False
    assert "찾을 수 없습니다" in msg


def test_delete_unused_succeeds(db_session, item_marriage):
    ok, msg = svc.delete_item(db_session, item_marriage.id)
    assert ok is True
    assert svc.get_item(db_session, item_marriage.id) is None


def test_delete_blocked_when_used_by_event(db_session, emp, item_marriage):
    ev = BenefitEvent(
        employee_id=emp.id, item_id=item_marriage.id,
        event_type="결혼", event_date=date(2025, 5, 1),
    )
    db_session.add(ev)
    db_session.commit()
    ok, msg = svc.delete_item(db_session, item_marriage.id)
    assert ok is False
    assert "1건" in msg
    assert svc.get_item(db_session, item_marriage.id) is not None
