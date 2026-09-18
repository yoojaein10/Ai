from datetime import date

import pytest

from app.core.security import hash_password
from app.db.models import (
    ChangeRequest,
    Department,
    Employee,
    EmpPersonal,
    EvalApprover,
    EvalRound,
    Notification,
    PerfTarget,
    Role,
    User,
    UserRole,
)
from app.schemas.change_request import ChangeRequestCreate
from app.schemas.perf_target import PerfTargetCreate
from app.services import change_request as cr_svc
from app.services import eval_objection as obj_svc
from app.services import notification as svc
from app.services import perf_target as pt_svc


# ── Service unit tests ───────────────────────────────────


@pytest.fixture
def user(db_session):
    u = User(login_id="notify_user", password_hash=hash_password("p"), is_active=True)
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def other_user(db_session):
    u = User(login_id="other_user", password_hash=hash_password("p"), is_active=True)
    db_session.add(u)
    db_session.commit()
    return u


def test_create_persists_notification(db_session, user):
    note = svc.create(
        db_session,
        user_id=user.id,
        type="TEST_TYPE",
        title="hello",
        message="world",
        link="/x",
    )
    assert note.id is not None
    assert note.is_read is False
    db_session.commit()
    assert db_session.query(Notification).count() == 1


def test_create_many_with_empty_list_is_noop(db_session):
    result = svc.create_many(
        db_session, user_ids=[], type="T", title="t"
    )
    assert result == []
    assert db_session.query(Notification).count() == 0


def test_create_many_inserts_one_per_user(db_session, user, other_user):
    notes = svc.create_many(
        db_session,
        user_ids=[user.id, other_user.id],
        type="BULK",
        title="공지",
    )
    assert len(notes) == 2
    assert {n.user_id for n in notes} == {user.id, other_user.id}


def test_list_mine_returns_only_my_notifications(db_session, user, other_user):
    svc.create(db_session, user_id=user.id, type="A", title="my1")
    svc.create(db_session, user_id=user.id, type="A", title="my2")
    svc.create(db_session, user_id=other_user.id, type="A", title="theirs")
    db_session.commit()

    result = svc.list_mine(db_session, user.id)
    assert result["total"] == 2
    assert result["unread"] == 2
    assert {n.title for n in result["items"]} == {"my1", "my2"}


def test_list_mine_orders_by_created_desc(db_session, user):
    svc.create(db_session, user_id=user.id, type="A", title="first")
    svc.create(db_session, user_id=user.id, type="A", title="second")
    db_session.commit()

    result = svc.list_mine(db_session, user.id)
    titles = [n.title for n in result["items"]]
    assert titles == ["second", "first"]


def test_list_mine_only_unread_filter(db_session, user):
    n1 = svc.create(db_session, user_id=user.id, type="A", title="unread")
    n2 = svc.create(db_session, user_id=user.id, type="A", title="read")
    n2.is_read = True
    db_session.commit()

    result = svc.list_mine(db_session, user.id, only_unread=True)
    assert result["total"] == 1
    assert result["items"][0].title == "unread"
    assert result["unread"] == 1


def test_list_mine_respects_limit(db_session, user):
    for i in range(5):
        svc.create(db_session, user_id=user.id, type="A", title=f"n{i}")
    db_session.commit()

    result = svc.list_mine(db_session, user.id, limit=3)
    assert len(result["items"]) == 3
    assert result["total"] == 5


def test_unread_count(db_session, user):
    svc.create(db_session, user_id=user.id, type="A", title="a")
    n2 = svc.create(db_session, user_id=user.id, type="A", title="b")
    n2.is_read = True
    db_session.commit()

    assert svc.unread_count(db_session, user.id) == 1


def test_mark_read_returns_updated_row(db_session, user):
    n = svc.create(db_session, user_id=user.id, type="A", title="a")
    db_session.commit()

    out = svc.mark_read(db_session, user.id, n.id)
    assert out is not None
    assert out.is_read is True


def test_mark_read_other_users_notification_returns_none(db_session, user, other_user):
    n = svc.create(db_session, user_id=other_user.id, type="A", title="a")
    db_session.commit()

    out = svc.mark_read(db_session, user.id, n.id)
    assert out is None
    db_session.refresh(n)
    assert n.is_read is False


def test_mark_read_missing_returns_none(db_session, user):
    assert svc.mark_read(db_session, user.id, 99999) is None


def test_mark_all_read_only_affects_my_unread(db_session, user, other_user):
    svc.create(db_session, user_id=user.id, type="A", title="mine1")
    svc.create(db_session, user_id=user.id, type="A", title="mine2")
    svc.create(db_session, user_id=other_user.id, type="A", title="theirs")
    db_session.commit()

    updated = svc.mark_all_read(db_session, user.id)
    assert updated == 2
    assert svc.unread_count(db_session, user.id) == 0
    assert svc.unread_count(db_session, other_user.id) == 1


# ── Router tests ─────────────────────────────────────────


def test_router_my_notifications(client, auth_headers, db_session, admin_user):
    svc.create(db_session, user_id=admin_user.id, type="A", title="hi")
    db_session.commit()

    res = client.get("/api/v1/notifications/me", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert body["unread"] == 1
    assert body["items"][0]["title"] == "hi"


def test_router_unread_count(client, auth_headers, db_session, admin_user):
    svc.create(db_session, user_id=admin_user.id, type="A", title="hi")
    db_session.commit()

    res = client.get("/api/v1/notifications/unread-count", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == {"unread": 1}


def test_router_mark_read(client, auth_headers, db_session, admin_user):
    n = svc.create(db_session, user_id=admin_user.id, type="A", title="hi")
    db_session.commit()

    res = client.post(f"/api/v1/notifications/{n.id}/read", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["is_read"] is True


def test_router_mark_read_missing_returns_404(client, auth_headers):
    res = client.post("/api/v1/notifications/99999/read", headers=auth_headers)
    assert res.status_code == 404


def test_router_mark_all_read(client, auth_headers, db_session, admin_user):
    svc.create(db_session, user_id=admin_user.id, type="A", title="a")
    svc.create(db_session, user_id=admin_user.id, type="A", title="b")
    db_session.commit()

    res = client.post("/api/v1/notifications/read-all", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == {"unread": 0}
    assert svc.unread_count(db_session, admin_user.id) == 0


# ── Trigger tests ────────────────────────────────────────


@pytest.fixture
def dept(db_session):
    d = Department(code="DEPT-NOTIF", name="알림팀")
    db_session.add(d)
    db_session.commit()
    return d


@pytest.fixture
def emp(db_session, dept):
    e = Employee(
        emp_no="N001", name_ko="홍알림", hire_date=date(2024, 1, 1),
        dept_id=dept.id, gender="M",
    )
    db_session.add(e)
    db_session.commit()
    return e


@pytest.fixture
def emp_user(db_session, emp):
    u = User(
        login_id="emp_notif", password_hash=hash_password("p"),
        employee_id=emp.id, is_active=True,
    )
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def reviewer(db_session):
    u = User(
        login_id="reviewer_notif", password_hash=hash_password("p"),
        employee_id=None, is_active=True,
    )
    db_session.add(u)
    db_session.commit()
    return u


def test_change_request_approve_creates_notification(db_session, emp_user, reviewer):
    body = ChangeRequestCreate(field_name="phone", new_value='010-0000-0000', reason="이사")
    req = cr_svc.create_change_request(db_session, emp_user, body)
    cr_svc.approve(db_session, req.id, reviewer, "확인")

    notes = (
        db_session.query(Notification)
        .filter(Notification.user_id == emp_user.id)
        .all()
    )
    assert len(notes) == 1
    assert notes[0].type == "CHANGE_REQUEST_APPROVED"
    assert "연락처" in notes[0].title
    assert notes[0].message == "확인"
    assert notes[0].is_read is False


def test_change_request_reject_creates_notification(db_session, emp_user, reviewer):
    body = ChangeRequestCreate(field_name="address", new_value="서울시 강남구")
    req = cr_svc.create_change_request(db_session, emp_user, body)
    cr_svc.reject(db_session, req.id, reviewer, "근거 부족")

    notes = db_session.query(Notification).filter(Notification.user_id == emp_user.id).all()
    assert len(notes) == 1
    assert notes[0].type == "CHANGE_REQUEST_REJECTED"
    assert "주소" in notes[0].title


@pytest.fixture
def hr_admin_user(db_session):
    role = (
        db_session.query(Role).filter(Role.code == "HR_ADMIN").first()
    )
    if role is None:
        role = Role(code="HR_ADMIN", name="인사담당자")
        db_session.add(role)
        db_session.flush()
    u = User(login_id="hradm", password_hash=hash_password("p"), is_active=True)
    db_session.add(u)
    db_session.flush()
    db_session.add(UserRole(user_id=u.id, role_id=role.id))
    db_session.commit()
    return u


@pytest.fixture
def round_obj(db_session):
    r = EvalRound(year=2026, name="2026 정기", status="IN_PROGRESS")
    db_session.add(r)
    db_session.commit()
    return r


def test_eval_objection_create_notifies_hr_admin(
    db_session, emp, hr_admin_user, round_obj
):
    obj_svc.create_objection(db_session, emp.id, round_obj.id, "재심의 요청합니다")

    notes = (
        db_session.query(Notification)
        .filter(Notification.user_id == hr_admin_user.id)
        .all()
    )
    assert len(notes) == 1
    assert notes[0].type == "EVAL_OBJECTION_CREATED"


def test_eval_objection_review_notifies_employee(
    db_session, emp, emp_user, hr_admin_user, round_obj
):
    obj = obj_svc.create_objection(db_session, emp.id, round_obj.id, "이의있음")
    obj_svc.review_objection(
        db_session, obj.id, "ACCEPTED", "수용", reviewer_id=hr_admin_user.id
    )

    notes = (
        db_session.query(Notification)
        .filter(
            Notification.user_id == emp_user.id,
            Notification.type == "EVAL_OBJECTION_REVIEWED",
        )
        .all()
    )
    assert len(notes) == 1
    assert "수용" in notes[0].title


def test_eval_objection_review_no_user_for_employee_does_not_crash(
    db_session, emp, hr_admin_user, round_obj
):
    obj = obj_svc.create_objection(db_session, emp.id, round_obj.id, "이의있음")
    obj_svc.review_objection(
        db_session, obj.id, "REJECTED", None, reviewer_id=hr_admin_user.id
    )

    notes = (
        db_session.query(Notification)
        .filter(Notification.type == "EVAL_OBJECTION_REVIEWED")
        .all()
    )
    assert notes == []


@pytest.fixture
def evaluator_emp(db_session, dept):
    e = Employee(
        emp_no="N002", name_ko="박상사", hire_date=date(2020, 1, 1),
        dept_id=dept.id, gender="M",
    )
    db_session.add(e)
    db_session.commit()
    return e


@pytest.fixture
def evaluator_user(db_session, evaluator_emp):
    u = User(
        login_id="evaluator_notif", password_hash=hash_password("p"),
        employee_id=evaluator_emp.id, is_active=True,
    )
    db_session.add(u)
    db_session.commit()
    return u


def test_perf_target_submit_notifies_evaluators(
    db_session, emp, evaluator_user, evaluator_emp, round_obj
):
    db_session.add(
        EvalApprover(
            round_id=round_obj.id,
            evaluatee_id=emp.id,
            evaluator_id=evaluator_emp.id,
            eval_type="PERF",
        )
    )
    db_session.commit()

    target = pt_svc.create_target(
        db_session,
        PerfTargetCreate(
            emp_id=emp.id,
            round_id=round_obj.id,
            target_value="매출 10% 증대",
            weight_percent=50,
        ),
    )
    pt_svc.submit_target(db_session, target.id)

    notes = (
        db_session.query(Notification)
        .filter(Notification.user_id == evaluator_user.id)
        .all()
    )
    assert len(notes) == 1
    assert notes[0].type == "PERF_TARGET_SUBMITTED"
    assert "홍알림" in notes[0].title


def test_perf_target_submit_with_no_evaluators_does_not_crash(
    db_session, emp, round_obj
):
    target = pt_svc.create_target(
        db_session,
        PerfTargetCreate(
            emp_id=emp.id,
            round_id=round_obj.id,
            target_value="목표",
            weight_percent=10,
        ),
    )
    pt_svc.submit_target(db_session, target.id)

    notes = (
        db_session.query(Notification)
        .filter(Notification.type == "PERF_TARGET_SUBMITTED")
        .all()
    )
    assert notes == []
