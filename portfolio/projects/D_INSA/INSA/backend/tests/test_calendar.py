"""PHASE 13 shared calendar service tests.

Covers:
- Calendar CRUD + scope-based permissions
- Event CRUD + range filtering boundaries
- Visibility rules (PUBLIC / DEPT / PRIVATE)
- Participant add (dedup) + response
- my/dept event convenience views
- create_event_from_approval idempotency
- delete_events_from_approval cascade
"""

from datetime import date, datetime, timedelta

import pytest

from app.core.security import hash_password
from app.db.models import (
    Calendar,
    CalendarEvent,
    Department,
    Employee,
    Role,
    User,
    UserRole,
)
from app.services import calendar_service as svc


# ── Fixtures ────────────────────────────────────────────────


@pytest.fixture
def role_admin(db_session):
    r = Role(code="HR_ADMIN", name="인사담당")
    db_session.add(r)
    db_session.commit()
    return r


@pytest.fixture
def role_emp(db_session):
    r = Role(code="EMPLOYEE", name="일반직원")
    db_session.add(r)
    db_session.commit()
    return r


@pytest.fixture
def dept_a(db_session):
    d = Department(code="DA", name="A팀")
    db_session.add(d)
    db_session.commit()
    return d


@pytest.fixture
def dept_b(db_session):
    d = Department(code="DB", name="B팀")
    db_session.add(d)
    db_session.commit()
    return d


@pytest.fixture
def emp_alice(db_session, dept_a):
    e = Employee(
        emp_no="E-A-1",
        name_ko="앨리스",
        hire_date=date(2023, 1, 1),
        dept_id=dept_a.id,
        emp_status="재직",
        gender="F",
    )
    db_session.add(e)
    db_session.commit()
    return e


@pytest.fixture
def emp_bob(db_session, dept_a):
    e = Employee(
        emp_no="E-A-2",
        name_ko="밥",
        hire_date=date(2023, 1, 1),
        dept_id=dept_a.id,
        emp_status="재직",
        gender="M",
    )
    db_session.add(e)
    db_session.commit()
    return e


@pytest.fixture
def emp_carol(db_session, dept_b):
    e = Employee(
        emp_no="E-B-1",
        name_ko="캐롤",
        hire_date=date(2023, 1, 1),
        dept_id=dept_b.id,
        emp_status="재직",
        gender="F",
    )
    db_session.add(e)
    db_session.commit()
    return e


def _make_user(
    db_session, login_id: str, employee_id: int, role
) -> User:
    u = User(
        login_id=login_id,
        password_hash=hash_password("pass"),
        employee_id=employee_id,
        is_active=True,
    )
    db_session.add(u)
    db_session.flush()
    db_session.add(UserRole(user_id=u.id, role_id=role.id))
    db_session.commit()
    db_session.refresh(u)
    return u


@pytest.fixture
def user_alice(db_session, emp_alice, role_emp):
    return _make_user(db_session, "alice", emp_alice.id, role_emp)


@pytest.fixture
def user_bob(db_session, emp_bob, role_emp):
    return _make_user(db_session, "bob", emp_bob.id, role_emp)


@pytest.fixture
def user_carol(db_session, emp_carol, role_emp):
    return _make_user(db_session, "carol", emp_carol.id, role_emp)


@pytest.fixture
def user_admin(db_session, emp_alice, role_admin):
    # Separate user to keep admin distinct from alice; link to a different emp.
    e = Employee(
        emp_no="E-ADM",
        name_ko="관리자",
        hire_date=date(2022, 1, 1),
        dept_id=emp_alice.dept_id,
        emp_status="재직",
        gender="F",
    )
    db_session.add(e)
    db_session.flush()
    return _make_user(db_session, "admin", e.id, role_admin)


@pytest.fixture
def default_calendar(db_session):
    c = Calendar(
        name="회사 전사",
        color_hex="#1677ff",
        scope="COMPANY",
        is_default=True,
    )
    db_session.add(c)
    db_session.commit()
    return c


@pytest.fixture
def leave_calendar(db_session):
    c = Calendar(name="휴가", color_hex="#52c41a", scope="COMPANY")
    db_session.add(c)
    db_session.commit()
    return c


@pytest.fixture
def travel_calendar(db_session):
    c = Calendar(name="출장", color_hex="#ff4d4f", scope="COMPANY")
    db_session.add(c)
    db_session.commit()
    return c


# ── Calendar CRUD + permissions ─────────────────────────────


def test_list_calendars_shows_company_for_all(
    db_session, default_calendar, user_alice
):
    result = svc.list_calendars(db_session, user_alice)
    ids = [c.id for c in result]
    assert default_calendar.id in ids


def test_create_company_calendar_requires_admin(db_session, user_alice):
    with pytest.raises(svc.PermissionDenied):
        svc.create_calendar(
            db_session, user_alice, name="신규", scope="COMPANY"
        )


def test_admin_creates_company_calendar(db_session, user_admin):
    cal = svc.create_calendar(
        db_session, user_admin, name="이벤트", scope="COMPANY"
    )
    assert cal.id is not None
    assert cal.scope == "COMPANY"


def test_create_dept_calendar_by_member(db_session, user_alice, dept_a):
    cal = svc.create_calendar(
        db_session,
        user_alice,
        name="A팀 공유",
        scope="DEPT",
        scope_ref=dept_a.id,
    )
    assert cal.scope == "DEPT"


def test_create_dept_calendar_for_foreign_dept_rejected(
    db_session, user_alice, dept_b
):
    with pytest.raises(svc.PermissionDenied):
        svc.create_calendar(
            db_session,
            user_alice,
            name="B팀 공유",
            scope="DEPT",
            scope_ref=dept_b.id,
        )


def test_personal_calendar_autofills_scope_ref(db_session, user_alice):
    cal = svc.create_calendar(
        db_session, user_alice, name="내 일정", scope="PERSONAL"
    )
    assert cal.scope == "PERSONAL"
    assert cal.scope_ref == user_alice.id


def test_cannot_delete_default_calendar(db_session, user_admin, default_calendar):
    with pytest.raises(svc.InvalidInput):
        svc.delete_calendar(db_session, user_admin, default_calendar.id)


def test_update_company_calendar_requires_admin(
    db_session, user_alice, default_calendar
):
    with pytest.raises(svc.PermissionDenied):
        svc.update_calendar(
            db_session, user_alice, default_calendar.id, name="rename"
        )


def test_update_company_calendar_as_admin(
    db_session, user_admin, leave_calendar
):
    cal = svc.update_calendar(
        db_session, user_admin, leave_calendar.id, name="휴가(개정)"
    )
    assert cal.name == "휴가(개정)"


def test_delete_calendar_as_admin(db_session, user_admin, leave_calendar):
    svc.delete_calendar(db_session, user_admin, leave_calendar.id)
    assert db_session.get(Calendar, leave_calendar.id) is None


# ── Events CRUD + range ─────────────────────────────────────


def test_create_event_autoinvites_owner_as_organizer(
    db_session, user_alice, default_calendar
):
    now = datetime(2026, 5, 1, 10, 0)
    out = svc.create_event(
        db_session,
        user_alice,
        calendar_id=default_calendar.id,
        title="회의",
        start_at=now,
        end_at=now + timedelta(hours=1),
    )
    assert out["owner_id"] == user_alice.employee_id
    assert len(out["participants"]) == 1
    assert out["participants"][0]["role"] == "ORGANIZER"
    assert out["participants"][0]["response"] == "ACCEPTED"


def test_create_event_rejects_inverted_range(
    db_session, user_alice, default_calendar
):
    now = datetime(2026, 5, 1, 10, 0)
    with pytest.raises(svc.InvalidInput):
        svc.create_event(
            db_session,
            user_alice,
            calendar_id=default_calendar.id,
            title="bad",
            start_at=now + timedelta(hours=2),
            end_at=now,
        )


def test_list_events_range_inclusive_start_exclusive_end(
    db_session, user_alice, default_calendar
):
    # Event spans 2026-05-10 10:00 -> 11:00
    svc.create_event(
        db_session,
        user_alice,
        calendar_id=default_calendar.id,
        title="A",
        start_at=datetime(2026, 5, 10, 10, 0),
        end_at=datetime(2026, 5, 10, 11, 0),
    )
    # Range that fully contains it
    inside = svc.list_events(
        db_session,
        user_alice,
        start=datetime(2026, 5, 10, 0, 0),
        end=datetime(2026, 5, 11, 0, 0),
    )
    assert len(inside) == 1
    # Range entirely after
    after = svc.list_events(
        db_session,
        user_alice,
        start=datetime(2026, 5, 12, 0, 0),
        end=datetime(2026, 5, 13, 0, 0),
    )
    assert after == []


def test_update_event_owner_only(
    db_session, user_alice, user_bob, default_calendar
):
    now = datetime(2026, 5, 1, 10, 0)
    created = svc.create_event(
        db_session,
        user_alice,
        calendar_id=default_calendar.id,
        title="old",
        start_at=now,
        end_at=now + timedelta(hours=1),
    )
    with pytest.raises(svc.PermissionDenied):
        svc.update_event(
            db_session, user_bob, created["id"], title="hijacked"
        )
    updated = svc.update_event(
        db_session, user_alice, created["id"], title="new title"
    )
    assert updated["title"] == "new title"


def test_admin_can_edit_any_event(
    db_session, user_alice, user_admin, default_calendar
):
    now = datetime(2026, 5, 1, 10, 0)
    created = svc.create_event(
        db_session,
        user_alice,
        calendar_id=default_calendar.id,
        title="t",
        start_at=now,
        end_at=now + timedelta(hours=1),
    )
    out = svc.update_event(
        db_session, user_admin, created["id"], title="edited"
    )
    assert out["title"] == "edited"


def test_delete_event_cascades_participants(
    db_session, user_alice, default_calendar, emp_bob
):
    now = datetime(2026, 5, 1, 10, 0)
    created = svc.create_event(
        db_session,
        user_alice,
        calendar_id=default_calendar.id,
        title="t",
        start_at=now,
        end_at=now + timedelta(hours=1),
        participant_emp_ids=[emp_bob.id],
    )
    svc.delete_event(db_session, user_alice, created["id"])
    assert db_session.get(CalendarEvent, created["id"]) is None


# ── Visibility rules ────────────────────────────────────────


def test_public_event_visible_to_everyone(
    db_session, user_alice, user_carol, default_calendar
):
    now = datetime(2026, 5, 1, 10, 0)
    svc.create_event(
        db_session,
        user_alice,
        calendar_id=default_calendar.id,
        title="public",
        start_at=now,
        end_at=now + timedelta(hours=1),
        visibility="PUBLIC",
    )
    out = svc.list_events(
        db_session,
        user_carol,
        start=now - timedelta(days=1),
        end=now + timedelta(days=1),
    )
    assert len(out) == 1


def test_dept_event_hidden_from_foreign_dept(
    db_session, user_alice, user_carol, default_calendar
):
    now = datetime(2026, 5, 1, 10, 0)
    svc.create_event(
        db_session,
        user_alice,
        calendar_id=default_calendar.id,
        title="dept-only",
        start_at=now,
        end_at=now + timedelta(hours=1),
        visibility="DEPT",
    )
    # Carol is in dept_b, alice in dept_a → carol should not see it.
    out = svc.list_events(
        db_session,
        user_carol,
        start=now - timedelta(days=1),
        end=now + timedelta(days=1),
    )
    assert len(out) == 0
    # Same-dept bob would see it (test separately)


def test_dept_event_visible_to_same_dept_member(
    db_session, user_alice, user_bob, default_calendar
):
    now = datetime(2026, 5, 1, 10, 0)
    svc.create_event(
        db_session,
        user_alice,
        calendar_id=default_calendar.id,
        title="dept-only",
        start_at=now,
        end_at=now + timedelta(hours=1),
        visibility="DEPT",
    )
    out = svc.list_events(
        db_session,
        user_bob,
        start=now - timedelta(days=1),
        end=now + timedelta(days=1),
    )
    assert len(out) == 1


def test_private_event_visible_to_participants_only(
    db_session, user_alice, user_bob, user_carol, emp_bob, default_calendar
):
    now = datetime(2026, 5, 1, 10, 0)
    created = svc.create_event(
        db_session,
        user_alice,
        calendar_id=default_calendar.id,
        title="private",
        start_at=now,
        end_at=now + timedelta(hours=1),
        visibility="PRIVATE",
        participant_emp_ids=[emp_bob.id],
    )
    # Bob is a participant — sees it.
    out_bob = svc.list_events(
        db_session,
        user_bob,
        start=now - timedelta(days=1),
        end=now + timedelta(days=1),
    )
    assert len(out_bob) == 1
    # Carol is neither owner nor participant.
    out_carol = svc.list_events(
        db_session,
        user_carol,
        start=now - timedelta(days=1),
        end=now + timedelta(days=1),
    )
    assert len(out_carol) == 0

    with pytest.raises(svc.PermissionDenied):
        svc.get_event(db_session, user_carol, created["id"])


def test_admin_sees_private_events(
    db_session, user_alice, user_admin, default_calendar
):
    now = datetime(2026, 5, 1, 10, 0)
    svc.create_event(
        db_session,
        user_alice,
        calendar_id=default_calendar.id,
        title="secret",
        start_at=now,
        end_at=now + timedelta(hours=1),
        visibility="PRIVATE",
    )
    out = svc.list_events(
        db_session,
        user_admin,
        start=now - timedelta(days=1),
        end=now + timedelta(days=1),
    )
    assert len(out) == 1


# ── Participants ────────────────────────────────────────────


def test_add_participants_dedups_existing(
    db_session, user_alice, default_calendar, emp_bob, emp_carol
):
    now = datetime(2026, 5, 1, 10, 0)
    created = svc.create_event(
        db_session,
        user_alice,
        calendar_id=default_calendar.id,
        title="t",
        start_at=now,
        end_at=now + timedelta(hours=1),
        participant_emp_ids=[emp_bob.id],
    )
    # Re-add bob + carol → only carol is new.
    added = svc.add_participants(
        db_session,
        user_alice,
        created["id"],
        emp_ids=[emp_bob.id, emp_carol.id],
    )
    assert len(added) == 1
    assert added[0]["emp_id"] == emp_carol.id


def test_add_participants_requires_owner_or_admin(
    db_session, user_alice, user_bob, default_calendar, emp_carol
):
    now = datetime(2026, 5, 1, 10, 0)
    created = svc.create_event(
        db_session,
        user_alice,
        calendar_id=default_calendar.id,
        title="t",
        start_at=now,
        end_at=now + timedelta(hours=1),
    )
    with pytest.raises(svc.PermissionDenied):
        svc.add_participants(
            db_session,
            user_bob,
            created["id"],
            emp_ids=[emp_carol.id],
        )


def test_respond_participant_updates_status(
    db_session, user_alice, user_bob, default_calendar, emp_bob
):
    now = datetime(2026, 5, 1, 10, 0)
    created = svc.create_event(
        db_session,
        user_alice,
        calendar_id=default_calendar.id,
        title="t",
        start_at=now,
        end_at=now + timedelta(hours=1),
        participant_emp_ids=[emp_bob.id],
    )
    out = svc.respond_participant(
        db_session, user_bob, created["id"], response="ACCEPTED"
    )
    assert out["response"] == "ACCEPTED"


def test_respond_participant_only_when_invited(
    db_session, user_alice, user_carol, default_calendar
):
    now = datetime(2026, 5, 1, 10, 0)
    created = svc.create_event(
        db_session,
        user_alice,
        calendar_id=default_calendar.id,
        title="t",
        start_at=now,
        end_at=now + timedelta(hours=1),
    )
    with pytest.raises(svc.NotFound):
        svc.respond_participant(
            db_session, user_carol, created["id"], response="ACCEPTED"
        )


# ── Convenience views ───────────────────────────────────────


def test_get_my_events_owner_or_participant(
    db_session, user_alice, user_bob, default_calendar, emp_bob
):
    now = datetime(2026, 5, 1, 10, 0)
    # Alice owns one, Bob is invited to another
    svc.create_event(
        db_session,
        user_alice,
        calendar_id=default_calendar.id,
        title="mine",
        start_at=now,
        end_at=now + timedelta(hours=1),
    )
    svc.create_event(
        db_session,
        user_alice,
        calendar_id=default_calendar.id,
        title="invited",
        start_at=now + timedelta(hours=2),
        end_at=now + timedelta(hours=3),
        participant_emp_ids=[emp_bob.id],
    )
    mine_bob = svc.get_my_events(
        db_session,
        user_bob,
        start=now - timedelta(days=1),
        end=now + timedelta(days=1),
    )
    titles = {e["title"] for e in mine_bob}
    assert titles == {"invited"}


def test_get_dept_events_filters_to_dept_members(
    db_session, user_alice, user_bob, user_carol, default_calendar
):
    now = datetime(2026, 5, 1, 10, 0)
    svc.create_event(
        db_session,
        user_alice,
        calendar_id=default_calendar.id,
        title="alice-ev",
        start_at=now,
        end_at=now + timedelta(hours=1),
    )
    svc.create_event(
        db_session,
        user_carol,
        calendar_id=default_calendar.id,
        title="carol-ev",
        start_at=now,
        end_at=now + timedelta(hours=1),
    )
    # user_bob in dept_a; should only see alice's event
    out = svc.get_dept_events(
        db_session,
        user_bob,
        start=now - timedelta(days=1),
        end=now + timedelta(days=1),
    )
    titles = {e["title"] for e in out}
    assert "alice-ev" in titles
    assert "carol-ev" not in titles


# ── Approval bridge ─────────────────────────────────────────


def test_create_event_from_approval_picks_leave_calendar(
    db_session, emp_alice, leave_calendar, default_calendar
):
    now = datetime(2026, 5, 1)
    event = svc.create_event_from_approval(
        db_session,
        doc_id=42,
        event_type="LEAVE",
        start_at=now,
        end_at=now + timedelta(days=2),
        owner_id=emp_alice.id,
        title="휴가(연차)",
        all_day=True,
    )
    assert event.calendar_id == leave_calendar.id
    assert event.source_type == "APPROVAL_DOC"
    assert event.source_ref == 42


def test_create_event_from_approval_falls_back_to_default(
    db_session, emp_alice, default_calendar
):
    now = datetime(2026, 5, 1)
    # No travel calendar seeded → fallback to COMPANY default
    event = svc.create_event_from_approval(
        db_session,
        doc_id=7,
        event_type="TRAVEL",
        start_at=now,
        end_at=now + timedelta(days=1),
        owner_id=emp_alice.id,
        title="출장",
    )
    assert event.calendar_id == default_calendar.id


def test_create_event_from_approval_is_idempotent(
    db_session, emp_alice, leave_calendar, default_calendar
):
    now = datetime(2026, 5, 1)
    first = svc.create_event_from_approval(
        db_session,
        doc_id=99,
        event_type="LEAVE",
        start_at=now,
        end_at=now + timedelta(days=1),
        owner_id=emp_alice.id,
        title="v1",
    )
    second = svc.create_event_from_approval(
        db_session,
        doc_id=99,
        event_type="LEAVE",
        start_at=now,
        end_at=now + timedelta(days=1),
        owner_id=emp_alice.id,
        title="v2",
    )
    assert first.id == second.id  # same row, updated in place
    assert second.title == "v2"
    # No duplicates
    matches = (
        db_session.query(CalendarEvent)
        .filter(
            CalendarEvent.source_type == "APPROVAL_DOC",
            CalendarEvent.source_ref == 99,
        )
        .count()
    )
    assert matches == 1


def test_delete_events_from_approval_removes_all(
    db_session, emp_alice, leave_calendar, default_calendar
):
    now = datetime(2026, 5, 1)
    svc.create_event_from_approval(
        db_session,
        doc_id=123,
        event_type="LEAVE",
        start_at=now,
        end_at=now + timedelta(days=1),
        owner_id=emp_alice.id,
        title="t",
    )
    count = svc.delete_events_from_approval(db_session, doc_id=123)
    assert count == 1
    remaining = (
        db_session.query(CalendarEvent)
        .filter(
            CalendarEvent.source_type == "APPROVAL_DOC",
            CalendarEvent.source_ref == 123,
        )
        .count()
    )
    assert remaining == 0


def test_delete_events_from_approval_noop_when_none(db_session):
    count = svc.delete_events_from_approval(db_session, doc_id=999999)
    assert count == 0
