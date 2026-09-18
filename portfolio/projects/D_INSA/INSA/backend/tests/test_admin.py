"""admin.py services 단위 테스트 (User/Role/Code/Setting CRUD).

라우터를 거치지 않고 service 함수를 직접 호출하여 핵심 분기 커버.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.core.security import hash_password, verify_password
from app.db.models import (
    Code,
    Department,
    Employee,
    Menu,
    Role,
    RoleMenu,
    Setting,
    User,
    UserRole,
)
from app.schemas.admin import (
    AdminCodeCreate,
    AdminCodeUpdate,
    AdminRoleCreate,
    AdminRoleUpdate,
    AdminSettingCreate,
    AdminSettingUpdate,
    AdminUserCreate,
    AdminUserUpdate,
)
from app.services import admin as svc


# ── Fixtures ─────────────────────────────────────────────


@pytest.fixture
def hr_role(db_session):
    role = Role(code="HR_ADMIN", name="인사")
    db_session.add(role)
    db_session.commit()
    db_session.refresh(role)
    return role


@pytest.fixture
def emp_role(db_session):
    role = Role(code="EMPLOYEE", name="직원")
    db_session.add(role)
    db_session.commit()
    db_session.refresh(role)
    return role


@pytest.fixture
def dept(db_session):
    d = Department(code="D01", name="개발팀")
    db_session.add(d)
    db_session.commit()
    db_session.refresh(d)
    return d


@pytest.fixture
def emp(db_session, dept):
    e = Employee(emp_no="E0001", name_ko="홍길동", hire_date=date(2024, 1, 1), dept_id=dept.id)
    db_session.add(e)
    db_session.commit()
    db_session.refresh(e)
    return e


@pytest.fixture
def existing_user(db_session, hr_role, emp):
    u = User(
        login_id="alice",
        password_hash=hash_password("init"),
        employee_id=emp.id,
        is_active=True,
    )
    db_session.add(u)
    db_session.flush()
    db_session.add(UserRole(user_id=u.id, role_id=hr_role.id))
    db_session.commit()
    db_session.refresh(u)
    return u


# ── Users ────────────────────────────────────────────────


def test_list_users_returns_all(db_session, existing_user):
    rows = svc.list_users(db_session)
    assert any(r["login_id"] == "alice" for r in rows)


def test_list_users_filter_by_active(db_session, existing_user, hr_role):
    inactive = User(
        login_id="bob", password_hash=hash_password("x"), is_active=False
    )
    db_session.add(inactive)
    db_session.commit()

    actives = svc.list_users(db_session, is_active=True)
    inactives = svc.list_users(db_session, is_active=False)
    assert all(r["is_active"] for r in actives)
    assert all(not r["is_active"] for r in inactives)
    assert any(r["login_id"] == "bob" for r in inactives)


def test_list_users_keyword_search_login_id(db_session, existing_user):
    rows = svc.list_users(db_session, keyword="ali")
    assert len(rows) == 1
    assert rows[0]["login_id"] == "alice"


def test_list_users_keyword_search_emp_no(db_session, existing_user):
    rows = svc.list_users(db_session, keyword="E0001")
    assert len(rows) == 1
    assert rows[0]["emp_no"] == "E0001"


def test_list_users_keyword_search_name(db_session, existing_user):
    rows = svc.list_users(db_session, keyword="홍길동")
    assert len(rows) == 1
    assert rows[0]["name_ko"] == "홍길동"


def test_get_user_includes_dept_and_roles(db_session, existing_user, dept):
    user = svc.get_user(db_session, existing_user.id)
    assert user is not None
    row = svc._user_to_row(user)
    assert row["dept_name"] == dept.name
    assert "HR_ADMIN" in row["role_codes"]


def test_get_user_not_found(db_session):
    assert svc.get_user(db_session, 99999) is None


def test_create_user_hashes_password_and_assigns_roles(db_session, hr_role, emp_role, emp):
    data = AdminUserCreate(
        login_id="carol",
        password='REDACTED_CONFIGURE_LOCALLY',
        employee_id=emp.id,
        is_active=True,
        role_ids=[hr_role.id, emp_role.id],
    )
    user = svc.create_user(db_session, data)
    assert user.id is not None
    assert user.password_hash != 'REDACTED_CONFIGURE_LOCALLY'
    assert verify_password('REDACTED_CONFIGURE_LOCALLY', user.password_hash)
    assert sorted(ur.role_id for ur in user.roles) == sorted([hr_role.id, emp_role.id])


def test_update_user_replaces_role_set(db_session, existing_user, emp_role):
    data = AdminUserUpdate(role_ids=[emp_role.id])
    updated = svc.update_user(db_session, existing_user.id, data)
    assert updated is not None
    assert [ur.role_id for ur in updated.roles] == [emp_role.id]


def test_update_user_partial_only_active(db_session, existing_user):
    data = AdminUserUpdate(is_active=False)
    updated = svc.update_user(db_session, existing_user.id, data)
    assert updated.is_active is False
    # roles untouched
    assert len(updated.roles) == 1


def test_update_user_not_found(db_session):
    assert svc.update_user(db_session, 99999, AdminUserUpdate(is_active=False)) is None


def test_reset_password_changes_hash(db_session, existing_user):
    old_hash = existing_user.password_hash
    ok = svc.reset_password(db_session, existing_user.id, "newpw")
    assert ok is True
    db_session.refresh(existing_user)
    assert existing_user.password_hash != old_hash
    assert verify_password("newpw", existing_user.password_hash)


def test_reset_password_user_not_found(db_session):
    assert svc.reset_password(db_session, 99999, "x") is False


def test_delete_user_removes_role_links(db_session, existing_user):
    uid = existing_user.id
    ok, msg = svc.delete_user(db_session, uid)
    assert ok is True
    assert "삭제" in msg
    assert db_session.query(User).filter_by(id=uid).first() is None
    assert db_session.query(UserRole).filter_by(user_id=uid).count() == 0


def test_delete_user_not_found(db_session):
    ok, msg = svc.delete_user(db_session, 99999)
    assert ok is False
    assert "찾을 수 없" in msg


# ── Roles ────────────────────────────────────────────────


def test_list_roles_includes_user_count(db_session, existing_user, hr_role):
    rows = svc.list_roles(db_session)
    target = next(r for r in rows if r["code"] == "HR_ADMIN")
    assert target["user_count"] == 1


def test_get_role_returns_menus(db_session, hr_role):
    menu = Menu(code="M1", name="메뉴1", path="/m1")
    db_session.add(menu)
    db_session.flush()
    db_session.add(RoleMenu(role_id=hr_role.id, menu_id=menu.id))
    db_session.commit()

    role = svc.get_role(db_session, hr_role.id)
    assert role is not None
    assert any(rm.menu_id == menu.id for rm in role.menus)


def test_create_role_with_menus(db_session):
    m1 = Menu(code="MA", name="A", path="/a")
    m2 = Menu(code="MB", name="B", path="/b")
    db_session.add_all([m1, m2])
    db_session.commit()

    data = AdminRoleCreate(
        code="DEPT_HEAD", name="부서장", description="head", menu_ids=[m1.id, m2.id]
    )
    role = svc.create_role(db_session, data)
    assert role.id is not None
    assert sorted(rm.menu_id for rm in role.menus) == sorted([m1.id, m2.id])


def test_update_role_replaces_menus(db_session, hr_role):
    m1 = Menu(code="MX", name="X", path="/x")
    m2 = Menu(code="MY", name="Y", path="/y")
    db_session.add_all([m1, m2])
    db_session.flush()
    db_session.add(RoleMenu(role_id=hr_role.id, menu_id=m1.id))
    db_session.commit()

    data = AdminRoleUpdate(menu_ids=[m2.id])
    updated = svc.update_role(db_session, hr_role.id, data)
    assert [rm.menu_id for rm in updated.menus] == [m2.id]


def test_update_role_partial_name_only(db_session, hr_role):
    data = AdminRoleUpdate(name="새이름")
    updated = svc.update_role(db_session, hr_role.id, data)
    assert updated.name == "새이름"


def test_update_role_not_found(db_session):
    assert svc.update_role(db_session, 99999, AdminRoleUpdate(name="x")) is None


def test_delete_role_blocked_when_assigned(db_session, existing_user, hr_role):
    ok, msg = svc.delete_role(db_session, hr_role.id)
    assert ok is False
    assert "1명" in msg or "사용자" in msg


def test_delete_role_success_when_unused(db_session, emp_role):
    ok, msg = svc.delete_role(db_session, emp_role.id)
    assert ok is True
    assert db_session.query(Role).filter_by(id=emp_role.id).first() is None


def test_delete_role_not_found(db_session):
    ok, msg = svc.delete_role(db_session, 99999)
    assert ok is False


def test_list_menus_ordered_by_sort_order(db_session):
    db_session.add_all(
        [
            Menu(code="A", name="A", path="/a", sort_order=2),
            Menu(code="B", name="B", path="/b", sort_order=1),
            Menu(code="C", name="C", path="/c", sort_order=3),
        ]
    )
    db_session.commit()
    rows = svc.list_menus(db_session)
    assert [m.code for m in rows] == ["B", "A", "C"]


# ── Codes ────────────────────────────────────────────────


def test_list_code_groups_aggregates_by_group(db_session):
    db_session.add_all(
        [
            Code(group_code="EMP_STATUS", group_name="재직상태", code="A", name="재직"),
            Code(group_code="EMP_STATUS", group_name="재직상태", code="L", name="휴직"),
            Code(group_code="JOB_RANK", group_name="직급", code="J1", name="사원"),
        ]
    )
    db_session.commit()
    groups = {g["group_code"]: g for g in svc.list_code_groups(db_session)}
    assert groups["EMP_STATUS"]["count"] == 2
    assert groups["JOB_RANK"]["count"] == 1


def test_list_codes_filter_by_group(db_session):
    db_session.add_all(
        [
            Code(group_code="A", code="A1", name="a1"),
            Code(group_code="A", code="A2", name="a2"),
            Code(group_code="B", code="B1", name="b1"),
        ]
    )
    db_session.commit()
    a_only = svc.list_codes(db_session, group_code="A")
    assert {c.code for c in a_only} == {"A1", "A2"}


def test_list_codes_keyword_search(db_session):
    db_session.add_all(
        [
            Code(group_code="X", code="X1", name="apple"),
            Code(group_code="X", code="X2", name="banana"),
        ]
    )
    db_session.commit()
    results = svc.list_codes(db_session, keyword="app")
    assert len(results) == 1
    assert results[0].name == "apple"


def test_list_codes_filter_by_active(db_session):
    db_session.add_all(
        [
            Code(group_code="X", code="X1", name="on", is_active=True),
            Code(group_code="X", code="X2", name="off", is_active=False),
        ]
    )
    db_session.commit()
    actives = svc.list_codes(db_session, is_active=True)
    assert all(c.is_active for c in actives)


def test_create_code(db_session):
    data = AdminCodeCreate(
        group_code="G", group_name="그룹", code="C1", name="첫번째"
    )
    code = svc.create_code(db_session, data)
    assert code.id is not None
    assert code.code == "C1"


def test_update_code_partial(db_session):
    c = Code(group_code="G", code="C1", name="old")
    db_session.add(c)
    db_session.commit()

    updated = svc.update_code(db_session, c.id, AdminCodeUpdate(name="new"))
    assert updated.name == "new"


def test_update_code_not_found(db_session):
    assert svc.update_code(db_session, 99999, AdminCodeUpdate(name="x")) is None


def test_delete_code(db_session):
    c = Code(group_code="G", code="C1", name="x")
    db_session.add(c)
    db_session.commit()
    ok, _ = svc.delete_code(db_session, c.id)
    assert ok is True
    assert db_session.query(Code).filter_by(id=c.id).first() is None


def test_delete_code_not_found(db_session):
    ok, _ = svc.delete_code(db_session, 99999)
    assert ok is False


# ── Settings ─────────────────────────────────────────────


def test_list_settings_filter_by_category(db_session):
    db_session.add_all(
        [
            Setting(key="k1", value="v1", category="company"),
            Setting(key="k2", value="v2", category="security"),
        ]
    )
    db_session.commit()
    rows = svc.list_settings(db_session, category="company")
    assert [s.key for s in rows] == ["k1"]


def test_create_setting(db_session):
    data = AdminSettingCreate(key="k", value="v", category="c", name="이름")
    s = svc.create_setting(db_session, data)
    assert s.id is not None


def test_update_setting_blocks_non_editable(db_session):
    s = Setting(key="readonly", value="v", is_editable=False)
    db_session.add(s)
    db_session.commit()
    result = svc.update_setting(db_session, s.id, AdminSettingUpdate(value="new"))
    assert result is None
    db_session.refresh(s)
    assert s.value == "v"


def test_update_setting_editable(db_session):
    s = Setting(key="ok", value="v", is_editable=True)
    db_session.add(s)
    db_session.commit()
    result = svc.update_setting(db_session, s.id, AdminSettingUpdate(value="new"))
    assert result.value == "new"


def test_update_setting_not_found(db_session):
    assert svc.update_setting(db_session, 99999, AdminSettingUpdate(value="x")) is None


def test_delete_setting_blocks_non_editable(db_session):
    s = Setting(key="readonly", value="v", is_editable=False)
    db_session.add(s)
    db_session.commit()
    ok, msg = svc.delete_setting(db_session, s.id)
    assert ok is False
    assert "편집할 수 없" in msg


def test_delete_setting_editable(db_session):
    s = Setting(key="ok", value="v", is_editable=True)
    db_session.add(s)
    db_session.commit()
    ok, _ = svc.delete_setting(db_session, s.id)
    assert ok is True


def test_delete_setting_not_found(db_session):
    ok, _ = svc.delete_setting(db_session, 99999)
    assert ok is False
