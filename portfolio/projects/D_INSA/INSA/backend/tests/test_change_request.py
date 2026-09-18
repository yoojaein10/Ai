from datetime import date

import pytest

from app.core.security import hash_password
from app.db.models import (
    ChangeRequest,
    Department,
    Employee,
    EmpPersonal,
    User,
)
from app.schemas.change_request import ChangeRequestCreate
from app.services import change_request as svc


@pytest.fixture
def dept(db_session):
    d = Department(code="D-CR", name="개발팀")
    db_session.add(d)
    db_session.commit()
    return d


@pytest.fixture
def emp(db_session, dept):
    e = Employee(
        emp_no="CR001", name_ko="박체인지", hire_date=date(2022, 1, 1),
        dept_id=dept.id, gender="M",
    )
    db_session.add(e)
    db_session.commit()
    return e


@pytest.fixture
def user(db_session, emp):
    u = User(
        login_id="changer", password_hash=hash_password("p"),
        employee_id=emp.id, is_active=True,
    )
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def reviewer(db_session):
    u = User(
        login_id="reviewer", password_hash=hash_password("p"),
        employee_id=None, is_active=True,
    )
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def personal(db_session, emp):
    p = EmpPersonal(employee_id=emp.id, address="서울시 옛주소", phone="010-0000-0000")
    db_session.add(p)
    db_session.commit()
    return p


# ── create ────────────────────────────────────────────────


def test_create_unsupported_field_raises(db_session, user):
    body = ChangeRequestCreate(field_name="invalid_field", new_value="x")
    with pytest.raises(ValueError, match="지원하지 않는 필드"):
        svc.create_change_request(db_session, user, body)


def test_create_user_without_employee_raises(db_session, reviewer):
    body = ChangeRequestCreate(field_name="phone", new_value='010-0000-0000')
    with pytest.raises(ValueError, match="사원 정보가 없습니다"):
        svc.create_change_request(db_session, reviewer, body)


def test_create_captures_old_value_from_personal(db_session, user, personal):
    body = ChangeRequestCreate(
        field_name="address", new_value="서울시 새주소", reason="이사",
    )
    req = svc.create_change_request(db_session, user, body)
    assert req.status == "PENDING"
    assert req.old_value == "서울시 옛주소"
    assert req.new_value == "서울시 새주소"
    assert req.requested_by == user.id


def test_create_old_value_none_when_no_personal(db_session, user):
    body = ChangeRequestCreate(field_name="phone", new_value='010-0000-0000')
    req = svc.create_change_request(db_session, user, body)
    assert req.old_value is None
    assert req.new_value == '010-0000-0000'


# ── list ──────────────────────────────────────────────────


def test_list_all_no_filter(db_session, user):
    svc.create_change_request(db_session, user, ChangeRequestCreate(field_name="phone", new_value="a"))
    svc.create_change_request(db_session, user, ChangeRequestCreate(field_name="email", new_value="b"))
    rows = svc.list_all(db_session)
    assert len(rows) == 2


def test_list_all_with_status_filter(db_session, user, reviewer):
    r1 = svc.create_change_request(db_session, user, ChangeRequestCreate(field_name="phone", new_value="a"))
    svc.create_change_request(db_session, user, ChangeRequestCreate(field_name="email", new_value="b"))
    svc.approve(db_session, r1.id, reviewer)
    pending = svc.list_all(db_session, status_filter="PENDING")
    approved = svc.list_all(db_session, status_filter="APPROVED")
    assert len(pending) == 1
    assert len(approved) == 1


def test_list_mine_filters_by_user(db_session, user, reviewer):
    svc.create_change_request(db_session, user, ChangeRequestCreate(field_name="phone", new_value="a"))
    rows = svc.list_mine(db_session, user)
    assert len(rows) == 1
    assert svc.list_mine(db_session, reviewer) == []


# ── approve ───────────────────────────────────────────────


def test_approve_not_found_raises(db_session, reviewer):
    with pytest.raises(ValueError, match="찾을 수 없습니다"):
        svc.approve(db_session, 9999, reviewer)


def test_approve_already_processed_raises(db_session, user, reviewer):
    req = svc.create_change_request(db_session, user, ChangeRequestCreate(field_name="phone", new_value="a"))
    svc.approve(db_session, req.id, reviewer)
    with pytest.raises(ValueError, match="이미 처리된"):
        svc.approve(db_session, req.id, reviewer)


def test_approve_updates_existing_personal(db_session, user, personal, reviewer):
    req = svc.create_change_request(
        db_session, user, ChangeRequestCreate(field_name="phone", new_value='010-0000-0000'),
    )
    result = svc.approve(db_session, req.id, reviewer, comment="OK")
    assert result.status == "APPROVED"
    assert result.reviewed_by == reviewer.id
    assert result.review_comment == "OK"
    db_session.refresh(personal)
    assert personal.phone == '010-0000-0000'


def test_approve_creates_personal_when_missing(db_session, user, emp, reviewer):
    req = svc.create_change_request(
        db_session, user, ChangeRequestCreate(field_name="address", new_value="새주소"),
    )
    svc.approve(db_session, req.id, reviewer)
    p = db_session.query(EmpPersonal).filter(EmpPersonal.employee_id == emp.id).first()
    assert p is not None
    assert p.address == "새주소"


def test_approve_unsupported_field_raises(db_session, user, reviewer):
    req = svc.create_change_request(db_session, user, ChangeRequestCreate(field_name="phone", new_value="x"))
    req.field_name = "tampered"
    db_session.commit()
    with pytest.raises(ValueError, match="지원하지 않는 필드"):
        svc.approve(db_session, req.id, reviewer)


# ── reject ────────────────────────────────────────────────


def test_reject_not_found_raises(db_session, reviewer):
    with pytest.raises(ValueError, match="찾을 수 없습니다"):
        svc.reject(db_session, 9999, reviewer)


def test_reject_already_processed_raises(db_session, user, reviewer):
    req = svc.create_change_request(db_session, user, ChangeRequestCreate(field_name="phone", new_value="a"))
    svc.reject(db_session, req.id, reviewer, comment="거절")
    with pytest.raises(ValueError, match="이미 처리된"):
        svc.reject(db_session, req.id, reviewer)


def test_reject_does_not_modify_personal(db_session, user, personal, reviewer):
    req = svc.create_change_request(
        db_session, user, ChangeRequestCreate(field_name="phone", new_value='010-0000-0000'),
    )
    result = svc.reject(db_session, req.id, reviewer, comment="사유 부족")
    assert result.status == "REJECTED"
    assert result.review_comment == "사유 부족"
    db_session.refresh(personal)
    assert personal.phone == "010-0000-0000"
