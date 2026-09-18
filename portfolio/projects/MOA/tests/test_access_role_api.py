"""일괄권한 — API 를 끝까지 돌려 본다 (인메모리 SQLite).

왜 이렇게 하나: 운영 DB 에 표를 만들기 전에도 '만들고 → 부서에 붙이고 → 그 사람
권한이 실제로 바뀌는' 흐름 전체가 도는지 확인해야 한다. 서비스 함수만 따로 부르면
라우터의 관문·검증·커밋 경로가 빠진다.

여기서 확인하는 계약
  · 일괄권한 CRUD 가 실제 표에 저장된다
  · 같은 이름을 두 번 만들 수 없다
  · **쓰는 곳이 있는 일괄권한은 못 지운다** (지우면 말없이 기본값으로 돌아간다)
  · 부서에 붙이면 그 부서 사람 전부가 받는다
  · **개인이 부서를 이긴다**
  · 지사 사용자는 남의 지사 부서를 못 건드린다
  · 모든 엔드포인트가 permissionManage 관문을 지난다
"""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.dependencies import get_current_access
from app.main import app
from app.services.auth_token import issue as issue_token
from app.models.access_role import AccessDeptRole, AccessRole, AccessUserRole
from app.services import access_policy as ap


@pytest.fixture()
def db_session():
    """세 표만 만든 인메모리 DB. 운영 표는 건드리지 않는다.

    StaticPool 이 꼭 필요하다 — sqlite 인메모리는 **연결마다 빈 DB 가 새로 생긴다.**
    이걸 빼면 표를 만든 연결과 라우터가 쓰는 연결이 갈려 'no such table' 이 난다
    (2026-08-13 실제로 겪었다).
    """
    engine = create_engine(
        "sqlite://", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[AccessRole.__table__, AccessDeptRole.__table__, AccessUserRole.__table__],
    )
    session = sessionmaker(bind=engine, future=True)()
    try:
        yield session
    finally:
        session.close()


_ACCESS_USR_SEQ = 2012


def _signed(client):
    """이 시험 클라이언트에 로그인 증표를 붙인다.

    권한을 바꾸는 API 는 증표를 요구한다(require_menu_write) — 헤더의 숫자
    하나만 믿던 것을 막은 관문이다. 픽스처를 안 쓰고 직접 만든 클라이언트도
    실제 화면과 같은 조건이 되도록 여기서 붙인다.
    """
    client.headers["X-MOA-AUTH"] = issue_token(_ACCESS_USR_SEQ)
    return client


def _access(*, menu=True, office="10", usr_seq=_ACCESS_USR_SEQ):
    return {
        "usr_seq": usr_seq, "usr_id": "tester", "emp_name": "원동하",
        "office_id": office, "office_name": "본사",
        "view_all_offices": True, "view_other_users": True,
        "menu_permissions": {"permissionManage": menu},
        "offices": [{"office_code": office}],
    }


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_access] = lambda: _access()
    try:
        # 권한을 바꾸는 API 는 로그인 증표를 요구한다(require_menu_write).
        # 헤더 숫자 하나만 믿던 것을 막은 것이라, 시험도 실제 화면처럼 증표를
        # 함께 보낸다 — 여기서 우회하면 그 관문이 시험에서 사라진다.
        client = _signed(TestClient(app))
        client.headers["X-MOA-AUTH"] = issue_token(_ACCESS_USR_SEQ)
        yield client
    finally:
        app.dependency_overrides.clear()


def _make(client, name, keys, **kw):
    body = {"name": name, "menu_keys": keys}
    body.update(kw)
    res = client.post("/api/permissions/roles", json=body)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["success"] is True, data
    return data["data"]


def test_일괄권한을_만들고_목록에_뜬다(client):
    role = _make(client, "집행부", ["appraisals", "bonus"], view_other_users=True)
    assert role["role_id"] > 0
    assert role["menu_keys"] == ["appraisals", "bonus"]
    assert role["view_other_users"] is True
    assert role["used_by"] == {"departments": 0, "users": 0}

    items = client.get("/api/permissions/roles").json()["data"]["items"]
    assert [r["name"] for r in items] == ["집행부"]


def test_같은_이름은_두_번_못_만든다(client):
    _make(client, "일반", ["appraisals"])
    res = client.post("/api/permissions/roles", json={"name": "일반", "menu_keys": []})
    assert res.json()["success"] is False
    assert "이미 있는" in res.json()["message"]


def test_일괄권한은_로그인_소속의_것이고_소속마다_따로_본다(db_session):
    """2026-08-18 공용 없는 지사별 일괄권한: **소속은 로그인 계정으로 강제**(요청값 무시).
    각 소속(본사·지사)은 자기 일괄권한만 만들고 본다 — 21지사·13지사가 '평가사 기본'을 따로.
    (get_current_access 오버라이드는 앱 전역이라, 클라이언트 하나로 소속만 바꿔 부른다.)"""
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)
    client.headers["X-MOA-AUTH"] = issue_token(_ACCESS_USR_SEQ)

    def office(o):
        app.dependency_overrides[get_current_access] = lambda: _access(office=o)

    try:
        office("21")
        a = client.post("/api/permissions/roles", json={
            "name": "평가사 기본", "menu_keys": ["appraisals"], "office_id": "99"}).json()
        # 요청에 office_id=99 를 줘도 로그인 소속(21)으로 강제된다.
        assert a["success"] is True and a["data"]["office_id"] == "21"
        # 같은 소속(21)·같은 이름 → 거절
        dup = client.post("/api/permissions/roles", json={
            "name": "평가사 기본", "menu_keys": []}).json()
        assert dup["success"] is False and "이 소속에 이미" in dup["message"]
        # 13지사 로그인 → 같은 이름 허용(다른 소속)
        office("13")
        b = client.post("/api/permissions/roles", json={
            "name": "평가사 기본", "menu_keys": ["appraisals"]}).json()
        assert b["success"] is True and b["data"]["office_id"] == "13"
        # 13지사는 자기 것만 본다.
        data13 = client.get("/api/permissions/roles").json()["data"]
        assert {r["office_id"] for r in data13["items"]} == {"13"}
        assert data13["office_id"] == "13"
        b_id = b["data"]["role_id"]
        # 21지사로 돌아가면 자기 것만 보이고, 13지사 것은 못 고치고 못 지운다.
        office("21")
        items21 = client.get("/api/permissions/roles").json()["data"]["items"]
        assert {r["office_id"] for r in items21} == {"21"}
        edit = client.post("/api/permissions/roles", json={
            "role_id": b_id, "name": "훔치기", "menu_keys": []}).json()
        assert edit["success"] is False and "다른 소속" in edit["message"]
        rm = client.post(f"/api/permissions/roles/{b_id}/delete").json()
        assert rm["success"] is False and "다른 소속" in rm["message"]
    finally:
        app.dependency_overrides.clear()


def test_모르는_메뉴_키는_거절한다(client):
    res = client.post(
        "/api/permissions/roles", json={"name": "이상", "menu_keys": ["nope"]})
    assert res.json()["success"] is False
    assert "모르는 메뉴" in res.json()["message"]


def test_부서에_붙이면_쓰는_곳으로_세고_삭제를_막는다(client):
    role = _make(client, "평가사", ["appraisals", "mySales"])
    res = client.post("/api/permissions/departments", json={
        "office_id": "10", "department_name": "주주평가사", "role_id": role["role_id"]})
    assert res.json()["success"] is True

    items = client.get("/api/permissions/roles").json()["data"]["items"]
    assert items[0]["used_by"]["departments"] == 1

    # 쓰는 곳이 있으면 삭제를 막는다 — 지우면 말없이 코드 기본값으로 돌아간다.
    res = client.post(f"/api/permissions/roles/{role['role_id']}/delete")
    assert res.json()["success"] is False
    assert "쓰는 곳" in res.json()["message"]

    # 해제하면 지울 수 있다.
    client.post("/api/permissions/departments", json={
        "office_id": "10", "department_name": "주주평가사", "role_id": None})
    assert client.post(f"/api/permissions/roles/{role['role_id']}/delete").json()["success"]


def test_detach로_부서를_복사본으로_떼고_지운다_권한불변(client, db_session):
    """2026-08-18 사용자 결정 '삭제 시 자동 분리'. 쓰는 부서가 있어도 detach=True 면
    그 부서를 이 일괄권한의 복사본으로 옮긴 뒤 지운다 — 부서 권한은 그대로다."""
    role = _make(client, "집행부세트", ["appraisals", "bonus"], view_other_users=True)
    client.post("/api/permissions/departments", json={
        "office_id": "10", "department_name": "집행부", "role_id": role["role_id"]})

    ident = ap.PolicyIdentity(
        usr_seq=777, usr_id="x", emp_name="아무개", office_id="10",
        department_code=None, department_name="집행부", employee_type="집행부",
        is_appraiser=False)
    before = ap.build_access_policy(ident, None, grant=ap.resolve_role(db_session, ident))
    assert set(before["menu_keys"]) == {"appraisals", "bonus"}
    assert before["view_other_users"] is True

    # detach 없이 = 여전히 막힌다.
    blocked = client.post(f"/api/permissions/roles/{role['role_id']}/delete")
    assert blocked.json()["success"] is False and "쓰는 곳" in blocked.json()["message"]

    # detach = 복사본으로 떼어낸 뒤 지운다.
    res = client.post(f"/api/permissions/roles/{role['role_id']}/delete",
                      json={"detach": True})
    body = res.json()
    assert body["success"] is True, body
    assert body["data"]["detached"] == {"departments": 1, "users": 0}

    # 원본은 비활성이 되고, 화면 목록(자동일괄권한은 숨김이지만 서버는 다 준다)에서
    # 원본 이름이 사라진다. 부서는 복사본을 가리켜 권한이 그대로다.
    db_session.expire_all()
    from app.models.access_role import AccessRole as AR
    assert db_session.get(AR, role["role_id"]).active == "N"
    after = ap.build_access_policy(ident, None, grant=ap.resolve_role(db_session, ident))
    assert set(after["menu_keys"]) == {"appraisals", "bonus"}, "부서 권한이 바뀌었다"
    assert after["view_other_users"] is True


def test_자기부서를_강등해_본인이_권한관리를_잃으면_확인받는다(client, monkeypatch):
    """2026-08-18 원동하 실측: 자기 부서(전산정보팀)에 '권한 관리' 없는 일괄권한을 걸어
    본인이 권한관리 권한을 잃었다(자기잠금). 전원 잠금(guard_permission_managers)이
    아니어도 — 본인이 담당자였다가 잃으면 409 로 한 번 되묻는다. 확인하면 저장된다."""
    from app.services import access_roles as ar
    from app.services import access_policy as apmod
    from app.services import permissions as perm

    role = _make(client, "집행부강등", ["appraisals", "bonus"])   # 권한관리 없음
    # 저장자(2012)가 지금 담당자라고 둔다(before 에 든다).
    monkeypatch.setattr(ar, "permission_manager_holders", lambda db, org=None: {2012})
    # 저장 뒤 본인 정책엔 permissionManage 가 없다(강등됐다).
    fake_me = apmod.PolicyIdentity(
        usr_seq=2012, usr_id="x", emp_name="원동하", office_id="10",
        department_code=None, department_name="전산정보팀",
        employee_type="전산정보팀", is_appraiser=False)
    monkeypatch.setattr(perm, "_policy_target", lambda _db, seq: ("dept", fake_me))
    monkeypatch.setattr(apmod, "load_access_policy", lambda _db, _id: {
        "menu_permissions": {"permissionManage": False, "appraisals": True}})

    res = client.post("/api/permissions/departments", json={
        "office_id": "10", "department_name": "전산정보팀", "role_id": role["role_id"]})
    assert res.status_code == 409, res.text
    body = res.json()
    assert body["code"] == "ROLE_LOCKOUT_CONFIRM"
    assert "권한 관리" in body["message"] and "당신" in body["message"]

    # 확인하면 저장된다.
    ok = client.post("/api/permissions/departments", json={
        "office_id": "10", "department_name": "전산정보팀", "role_id": role["role_id"],
        "confirm_lockout": True})
    assert ok.json()["success"] is True, ok.text


def test_detach는_개인을_현재권한_그대로_개인예외로_박제한다(monkeypatch):
    """개인 참조는 각자 '개인 예외'로 지금 유효한 권한을 그대로 박제하고 개인 일괄권한을
    뗀다(지사 재무담당처럼 옛 개인 일괄권한을 쓰는 세트도 이 길로 지워진다).

    개인 예외는 절대값이라 아래 층(부서·코드 기본값)이 무엇이든 결과가 같다."""
    from app.models.access_policy import AccessPolicy
    from app.services import access_roles as ar
    from app.services import permissions as perm
    from app.services import access_policy as apmod

    engine = create_engine(
        "sqlite://", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[
        AccessRole.__table__, AccessDeptRole.__table__,
        AccessUserRole.__table__, AccessPolicy.__table__])
    db = sessionmaker(bind=engine, future=True)()

    role = AccessRole(
        name="지사재무", menu_keys_json=json.dumps(["payments", "receivables"]),
        view_all_offices="N", view_other_users="Y", active="Y")
    db.add(role)
    db.flush()
    db.add(AccessUserRole(usr_seq=9001, role_id=role.role_id, active="Y"))
    db.commit()

    fake_ident = apmod.PolicyIdentity(
        usr_seq=9001, usr_id="u9001", emp_name="김재무", office_id="21",
        department_code=None, department_name="재무팀",
        employee_type="일반직원", is_appraiser=False)
    monkeypatch.setattr(perm, "_policy_target", lambda _db, seq: ("user", fake_ident))
    monkeypatch.setattr(apmod, "load_access_policy", lambda _db, _id: {
        "view_all_offices": False, "view_other_users": True,
        "menu_permissions": {k: k in {"payments", "receivables"} for k in ar.MENU_KEYS},
    })

    out = ar.delete_role(db, role.role_id, detach=True, updated_by=2012)
    assert out["deleted"] is True
    assert out["detached"] == {"departments": 0, "users": 1}

    # 개인 일괄권한은 해제되고, 개인 예외로 지금 권한이 박제됐다.
    assert db.get(AccessUserRole, 9001).active == "N"
    pol = db.get(AccessPolicy, 9001)
    assert pol is not None and pol.active == "Y"
    over = json.loads(pol.menu_overrides_json)
    assert over["payments"] is True and over["receivables"] is True
    assert over["appraisals"] is False, "안 켜진 메뉴는 꺼진 채 박제돼야 한다"
    assert pol.view_other_users_override == "Y"
    assert pol.view_all_offices_override == "N"
    assert pol.usr_id == "u9001"
    # 원본 일괄권한은 비활성.
    assert db.get(AccessRole, role.role_id).active == "N"
    db.close()


def test_부서에_붙인_일괄권한이_그_부서_사람에게_적용된다(client, db_session):
    role = _make(client, "집행부", ["appraisals", "bonus"])
    client.post("/api/permissions/departments", json={
        "office_id": "10", "department_name": "집행부", "role_id": role["role_id"]})

    identity = ap.PolicyIdentity(
        usr_seq=555, usr_id="x", emp_name="아무개", office_id="10",
        department_code=None, department_name="집행부", employee_type="집행부",
        is_appraiser=False)
    grant = ap.resolve_role(db_session, identity)
    assert grant is not None and grant.source == "dept"
    policy = ap.build_access_policy(identity, grant=grant)
    assert policy["menu_permissions"]["bonus"] is True
    # 코드 기본값(집행부 7종)에 있던 것이 일괄권한에 없으면 꺼져야 한다 — 대체이므로.
    assert policy["menu_permissions"]["salesInput"] is False
    assert policy["role"]["name"] == "집행부"


def test_개인_일괄권한이_부서_일괄권한을_이긴다(client, db_session):
    dept_role = _make(client, "부서용", ["appraisals"])
    user_role = _make(client, "개인용", ["mySales"])
    client.post("/api/permissions/departments", json={
        "office_id": "10", "department_name": "집행부", "role_id": dept_role["role_id"]})
    client.post("/api/permissions/users/role", json={
        "usr_seq": 555, "role_id": user_role["role_id"]})

    identity = ap.PolicyIdentity(
        usr_seq=555, usr_id="x", emp_name="아무개", office_id="10",
        department_code=None, department_name="집행부", employee_type="집행부",
        is_appraiser=False)
    grant = ap.resolve_role(db_session, identity)
    assert grant.source == "user" and grant.name == "개인용"
    policy = ap.build_access_policy(identity, grant=grant)
    assert policy["menu_permissions"]["mySales"] is True
    assert policy["menu_permissions"]["appraisals"] is False


def test_개인_일괄권한을_풀면_부서로_되돌아간다(client, db_session):
    dept_role = _make(client, "부서용", ["appraisals"])
    user_role = _make(client, "개인용", ["mySales"])
    client.post("/api/permissions/departments", json={
        "office_id": "10", "department_name": "집행부", "role_id": dept_role["role_id"]})
    client.post("/api/permissions/users/role", json={"usr_seq": 555, "role_id": user_role["role_id"]})
    client.post("/api/permissions/users/role", json={"usr_seq": 555, "role_id": None})

    identity = ap.PolicyIdentity(
        usr_seq=555, usr_id="x", emp_name="아무개", office_id="10",
        department_code=None, department_name="집행부", employee_type="집행부",
        is_appraiser=False)
    grant = ap.resolve_role(db_session, identity)
    assert grant.source == "dept"


def test_부서를_옮기면_새_부서_일괄권한으로_갈아탄다(client, db_session):
    """사용자 질문(2026-08-17): "부서 바뀌면 자동으로 권한 따라가나?"

    개인 배정이 없는 사람은 (office_id, department_name) 으로만 일괄권한을 찾으므로,
    부서명이 바뀌면 그 부서의 일괄권한을 그대로 받는다 — 조직을 따라간다.
    resolve_role 이 부서 조회를 매번 새로 하기에 재로그인만으로 반영된다(캐시 없음).
    """
    a = _make(client, "가부서용", ["appraisals"])
    b = _make(client, "나부서용", ["mySales", "payments"])
    client.post("/api/permissions/departments", json={
        "office_id": "10", "department_name": "가부서", "role_id": a["role_id"]})
    client.post("/api/permissions/departments", json={
        "office_id": "10", "department_name": "나부서", "role_id": b["role_id"]})

    def resolve(dept):
        ident = ap.PolicyIdentity(
            usr_seq=7001, usr_id="m", emp_name="이동", office_id="10",
            department_code=None, department_name=dept, employee_type="일반직원",
            is_appraiser=False)
        return ap.resolve_role(db_session, ident)

    # 같은 사람, 부서만 바꾼다 — 인사이동을 그대로 흉내낸다.
    assert resolve("가부서").menu_keys == frozenset({"appraisals"})
    assert resolve("나부서").menu_keys == frozenset({"mySales", "payments"})
    # 일괄권한 없는 부서로 가면 부서 일괄권한이 사라진다(코드 기본값으로 떨어짐).
    assert resolve("무배정부서") is None


def test_개인_일괄권한이_있으면_부서를_옮겨도_안_바뀐다(client, db_session):
    """실측(지인자 95): 개인일괄권한 '지사 재무담당'을 든 사람은 재무팀→감사부→계약직
    어디로 옮겨도 8종 그대로였다. 그래서 화면이 '개인' 표시로 담당자에게 알린다 —
    부서 권한을 고쳐도 이 사람은 안 따라온다는 사실을."""
    dept_a = _make(client, "가부서일괄권한", ["appraisals"])
    personal = _make(client, "개인고정", ["bonus", "salesStats"])
    client.post("/api/permissions/departments", json={
        "office_id": "10", "department_name": "가부서", "role_id": dept_a["role_id"]})
    client.post("/api/permissions/users/role", json={
        "usr_seq": 7002, "role_id": personal["role_id"]})

    def resolve(dept):
        ident = ap.PolicyIdentity(
            usr_seq=7002, usr_id="p", emp_name="고정", office_id="10",
            department_code=None, department_name=dept, employee_type="일반직원",
            is_appraiser=False)
        return ap.resolve_role(db_session, ident)

    # 어느 부서로 옮겨도 개인 일괄권한이 이긴다.
    for dept in ("가부서", "나부서", "아무부서"):
        g = resolve(dept)
        assert g.source == "user", f"{dept} 에서 부서가 개인을 이겼다"
        assert g.menu_keys == frozenset({"bonus", "salesStats"})


def test_일괄권한을_고치면_쓰는_곳이_따라_바뀐다(client, db_session):
    """참조라서 복사가 아니다 — 사용자가 고른 방식(2026-08-13)."""
    role = _make(client, "집행부", ["appraisals"])
    client.post("/api/permissions/departments", json={
        "office_id": "10", "department_name": "집행부", "role_id": role["role_id"]})
    identity = ap.PolicyIdentity(
        usr_seq=555, usr_id="x", emp_name="아무개", office_id="10",
        department_code=None, department_name="집행부", employee_type="집행부",
        is_appraiser=False)
    assert ap.resolve_role(db_session, identity).menu_keys == frozenset({"appraisals"})

    _make(client, "집행부", ["appraisals", "bonus"], role_id=role["role_id"])
    db_session.expire_all()
    assert ap.resolve_role(db_session, identity).menu_keys == frozenset({"appraisals", "bonus"})


def test_지사_사용자는_남의_지사_부서를_못_건드린다(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_access] = lambda: _access(office="21")
    try:
        client = _signed(TestClient(app))
        res = client.post("/api/permissions/departments", json={
            "office_id": "10", "department_name": "집행부", "role_id": 1})
        assert res.status_code == 403
        assert res.json()["code"] == "NOT_MY_OFFICE"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(("method", "path", "body"), [
    ("get", "/api/permissions/roles", None),
    ("post", "/api/permissions/roles", {"name": "x", "menu_keys": []}),
    ("post", "/api/permissions/roles/1/delete", {}),
    ("get", "/api/permissions/departments", None),
    ("post", "/api/permissions/departments",
     {"office_id": "10", "department_name": "집행부", "role_id": None}),
    ("post", "/api/permissions/users/role", {"usr_seq": 1, "role_id": None}),
])
def test_메뉴_권한이_없으면_전부_막힌다(db_session, method, path, body):
    """권한을 바꾸는 화면이라 조회조차 아무나 열면 안 된다 —
    누가 무슨 권한을 갖는지가 그대로 드러난다."""
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_access] = lambda: _access(menu=False)
    try:
        client = _signed(TestClient(app))
        res = getattr(client, method)(path, **({"json": body} if body is not None else {}))
        assert res.status_code == 403, f"{method} {path} 가 열려 있다"
    finally:
        app.dependency_overrides.clear()


# ── 마지막 권한관리자 잠금 ──────────────────────────────────────────────────
#
# 종전 자물쇠(_guard_last_permission_manager)는 a10_access_policy 한 갈래만 봤다.
# 일괄권한이 생기면서 권한관리를 일괄권한으로 줄 수 있게 됐는데, 그 경로에는 검사가
# **하나도 없었다**(2026-08-13 검수에서 발견). 부서 일괄권한에서 permissionManage 를
# 빼는 것만으로 전원이 잠기고, 그러면 SQL 을 직접 고치는 수밖에 없다.

def test_일괄권한에서_권한관리를_빼면_아무도_못_들어올_때_막는다(client):
    role = _make(client, "관리자", ["permissionManage", "appraisals"])
    client.post("/api/permissions/users/role", json={
        "usr_seq": 555, "role_id": role["role_id"]})

    # 대상은 요청자(2012)가 아닌 남이어야 한다 — 자기 권한은 자기가 못 바꾼다.
    # 이 사람이 유일한 보유자다 — 일괄권한에서 permissionManage 를 빼면 0명이 된다.
    res = client.post("/api/permissions/roles", json={
        "role_id": role["role_id"], "name": "관리자", "menu_keys": ["appraisals"]})
    assert res.json()["success"] is False
    assert "0명" in res.json()["message"]

    # 막혔으면 **저장도 안 돼 있어야** 한다(되돌아갔는지).
    items = client.get("/api/permissions/roles").json()["data"]["items"]
    assert "permissionManage" in items[0]["menu_keys"], "막고서 저장돼 있으면 헛일이다"


def test_유일한_관리자의_일괄권한을_풀면_막는다(client):
    role = _make(client, "관리자", ["permissionManage"])
    client.post("/api/permissions/users/role", json={"usr_seq": 555, "role_id": role["role_id"]})
    res = client.post("/api/permissions/users/role", json={"usr_seq": 555, "role_id": None})
    assert res.json()["success"] is False
    assert "0명" in res.json()["message"]


def test_다른_관리자가_있으면_풀_수_있다(client):
    role = _make(client, "관리자", ["permissionManage"])
    client.post("/api/permissions/users/role", json={"usr_seq": 555, "role_id": role["role_id"]})
    client.post("/api/permissions/users/role", json={"usr_seq": 999, "role_id": role["role_id"]})
    res = client.post("/api/permissions/users/role", json={"usr_seq": 555, "role_id": None})
    assert res.json()["success"] is True, res.text


def test_권한관리를_아무도_안_가진_상태에서는_막지_않는다(client):
    """표를 막 만들었을 때(일괄권한 0개)는 기존 a10_access_policy 가 관리자를 갖고 있다.
    그 갈래를 못 보는 인메모리 시험에서는 홀더가 0이지만, 일괄권한과 무관한 저장까지
    막으면 아무것도 못 만든다 — permissionManage 를 건드리지 않는 변경은 통과해야 한다."""
    role = _make(client, "일반", ["appraisals"])
    assert role["role_id"] > 0
    res = client.post("/api/permissions/departments", json={
        "office_id": "10", "department_name": "총무팀", "role_id": role["role_id"]})
    assert res.json()["success"] is True, res.text


# ── 2026-08-13 전수 검수에서 막은 것들 ────────────────────────────────────
# 넷 다 '운영에 올리면 되돌릴 수 없는' 쪽이라 시험으로 박아 둔다.


def test_지사_관리자는_다른_소속_일괄권한을_못_고친다(db_session):
    """공용 없는 지사별 일괄권한(2026-08-18): 지사 관리자는 **자기 소속 일괄권한은 만들 수 있지만**,
    다른 소속(본사 등) 일괄권한은 고치거나 지울 수 없다 — 안 그러면 본사 재무팀·전산정보팀을
    묶은 일괄권한의 체크를 지사에서 풀어 본사 권한을 통째로 바꿀 수 있다. (종전엔 일괄권한이 전사
    공용이라 본사만 만졌다 — 그 잠금을 소속 소유 검사로 대체했다.)"""
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_access] = lambda: _access(office="10")
    try:
        head = _signed(TestClient(app))
        role = _make(head, "본사 전체메뉴", ["appraisals"])   # 본사 일괄권한(office 10)
        # 지사(21) 관리자로 전환
        app.dependency_overrides[get_current_access] = lambda: _access(office="21")
        branch = _signed(TestClient(app))
        # 자기 소속 새 일괄권한은 만들 수 있다(더는 403 아님).
        mine = branch.post("/api/permissions/roles",
                           json={"name": "지사 일괄권한", "menu_keys": []}).json()
        assert mine["success"] is True and mine["data"]["office_id"] == "21"
        # 하지만 본사 일괄권한은 고치거나 지울 수 없다(소속 소유 검사).
        edit = branch.post("/api/permissions/roles",
                           json={"role_id": role["role_id"], "name": "훔치기",
                                 "menu_keys": []}).json()
        assert edit["success"] is False and "다른 소속" in edit["message"]
        rm = branch.post(f"/api/permissions/roles/{role['role_id']}/delete",
                         json={}).json()
        assert rm["success"] is False and "다른 소속" in rm["message"]
    finally:
        app.dependency_overrides.clear()


def test_지사_관리자는_남의_지사_사람에게_일괄권한을_못_준다(db_session, monkeypatch):
    """이 엔드포인트만 지사 확인이 빠져 있었다 — 나머지는 전부 막는데 여기만 뚫렸다."""
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_access] = lambda: _access(office="10")
    try:
        head = _signed(TestClient(app))
        role = _make(head, "일반", ["appraisals"])

        from app.services import access_roles as ar_mod
        from app.services import permissions as perm_mod

        def fake_target(db, usr_seq):
            return "본사", ap.PolicyIdentity(
                usr_seq=usr_seq, usr_id="x", emp_name="본사사람", office_id="10",
                department_code=None, department_name="집행부",
                employee_type="집행부", is_appraiser=False)

        monkeypatch.setattr(perm_mod, "_policy_target", fake_target)
        app.dependency_overrides[get_current_access] = lambda: _access(office="21")
        res = _signed(TestClient(app)).post("/api/permissions/users/role",
                                   json={"usr_seq": 9001, "role_id": role["role_id"]})
        assert res.json()["success"] is False, res.text
        assert "다른 지사" in res.json()["message"]
        assert ar_mod is not None
    finally:
        app.dependency_overrides.clear()


def test_개인배정_일괄권한을_0메뉴로_고치면_확인받는다(client, monkeypatch):
    """부서만이 아니라 **개인에게 붙은 일괄권한**을 0메뉴로 편집해도 그 보유자들이 잠기므로
    확인을 받아야 한다(2026-08-18 적대검증: save_role 이 부서(AccessDeptRole)만 세고
    개인(AccessUserRole) 보유자는 안 세서, 개인배정 일괄권한을 비우면 조용히 잠겼다)."""
    from app.services import access_roles as ar
    role = _make(client, "개인용", ["appraisals"])
    # 배정 시엔 메뉴가 있어 통과(테스트 DB엔 원천표 없어 locks_out_user 는 원래 False).
    client.post("/api/permissions/users/role",
                json={"usr_seq": 555, "role_id": role["role_id"]})
    # 이제 '이 사람은 0메뉴가 된다'로 본다.
    monkeypatch.setattr(ar, "locks_out_user", lambda db, seq, rid: True)
    # 0메뉴로 편집 → 개인 보유자 잠금이라 확인 요구(부서 부착 0이어도).
    res = client.post("/api/permissions/roles", json={
        "role_id": role["role_id"], "name": "개인용", "menu_keys": []})
    assert res.status_code == 409, res.text
    assert res.json()["code"] == "ROLE_LOCKOUT_CONFIRM"
    # 확인하면 진행한다 — 막는 게 아니라 묻는 것이다.
    res = client.post("/api/permissions/roles", json={
        "role_id": role["role_id"], "name": "개인용", "menu_keys": [],
        "confirm_lockout": True})
    assert res.json()["success"] is True, res.text


def test_부서권한은_부서원의_개인설정을_덮어_리셋한다(client, db_session, monkeypatch):
    """부서 일괄권한 = **복사/덮어쓰기** (2026-08-18 사용자). 부서에 일괄권한을 걸면 그 부서
    사람들의 개인 일괄권한·개인 예외를 내려 부서값으로 리셋한다 — 개인이 나중에 바꾸면
    개인이 이기지만, 부서권한을 다시 걸면 다시 부서값으로 덮인다."""
    from app.models.access_role import AccessUserRole
    from app.models.access_policy import AccessPolicy
    import app.routers.permissions as rp
    from app.services import permissions as perm
    # 부서 리셋은 개인 예외(a10_access_policy)도 내린다 — 기본 3표 DB엔 없으니 만든다.
    AccessPolicy.__table__.create(db_session.get_bind(), checkfirst=True)
    fake_org = {"offices": [{"id": "10", "departments": [
        {"name": "감사부", "employees": [{"usr_seq": 555}]}]}]}
    monkeypatch.setattr(rp, "organization_preview",
                        lambda db, visible_office_id=None: fake_org)
    monkeypatch.setattr(perm, "organization_preview",
                        lambda db, visible_office_id=None: fake_org)

    dept_role = _make(client, "부서기본", ["appraisals"])
    person_role = _make(client, "개인특별", ["appraisals", "payments"])
    # 555 에게 개인 일괄권한을 준다 — 지금은 개인이 부서를 이긴다.
    client.post("/api/permissions/users/role",
                json={"usr_seq": 555, "role_id": person_role["role_id"]})
    assert db_session.get(AccessUserRole, 555).active == "Y"

    # 감사부에 부서권한을 건다 → 555 의 개인 일괄권한이 내려가 부서값으로 리셋된다.
    res = client.post("/api/permissions/departments", json={
        "office_id": "10", "department_name": "감사부", "role_id": dept_role["role_id"]})
    assert res.json()["success"] is True, res.text
    db_session.expire_all()
    ur = db_session.get(AccessUserRole, 555)
    assert ur is None or ur.active == "N", "부서권한 재적용이 개인 일괄권한을 안 덮었다"


def test_같은_부서일괄권한_재적용도_개인설정을_다시_리셋한다(client, db_session, monkeypatch):
    """2026-08-19 신고: 40명 부서에 일괄권한을 걸고 → 3명이 개인적으로 바꾼 뒤 → '헷갈리니
    그냥 다시 부서로 초기화' 하려는데 막혔다. 원인은 **같은 일괄권한 재적용을 무조건 멱등
    skip** 해서 _reset_dept_individuals 가 아예 안 돌던 것. 일괄권한이 그대로여도 되돌릴 개인
    설정이 남아 있으면 리셋해야 하고, 되돌릴 게 없을 때만 skip 이어야 한다."""
    from app.models.access_role import AccessUserRole
    from app.models.access_policy import AccessPolicy
    import app.routers.permissions as rp
    from app.services import permissions as perm
    AccessPolicy.__table__.create(db_session.get_bind(), checkfirst=True)
    fake_org = {"offices": [{"id": "10", "departments": [
        {"name": "감사부", "employees": [{"usr_seq": 555}]}]}]}
    monkeypatch.setattr(rp, "organization_preview",
                        lambda db, visible_office_id=None: fake_org)
    monkeypatch.setattr(perm, "organization_preview",
                        lambda db, visible_office_id=None: fake_org)

    dept_role = _make(client, "부서기본", ["appraisals"])
    person_role = _make(client, "개인특별", ["appraisals", "payments"])
    body = {"office_id": "10", "department_name": "감사부", "role_id": dept_role["role_id"]}

    # ① 부서에 한 번 건다.
    assert client.post("/api/permissions/departments", json=body).json()["success"]
    # ② 555 가 개인적으로 바꾼다 — 개인 일괄권한이 부서를 이긴다.
    client.post("/api/permissions/users/role",
                json={"usr_seq": 555, "role_id": person_role["role_id"]})
    db_session.expire_all()
    assert db_session.get(AccessUserRole, 555).active == "Y"

    # ③ '그냥 다시 부서로 초기화' — 같은 일괄권한을 다시 건다. 막히지 않고 개인 일괄권한이 내려간다.
    res = client.post("/api/permissions/departments", json=body)
    data = res.json()
    assert data["success"] is True, res.text
    assert data["data"].get("skipped") is not True, "같은 일괄권한이라고 건너뛰면 초기화가 막힌다"
    assert data["data"].get("reset_count") == 1, res.text
    db_session.expire_all()
    ur = db_session.get(AccessUserRole, 555)
    assert ur is None or ur.active == "N", "재적용이 개인 일괄권한을 안 덮었다"

    # ④ 이제 되돌릴 개인 설정이 없다 → 같은 일괄권한 재적용은 진짜 no-op(skip) 이어야 감사 깨끗.
    res = client.post("/api/permissions/departments", json=body)
    assert res.json()["data"].get("skipped") is True, "되돌릴 게 없으면 멱등 skip 이어야 한다"


def test_권한관리가_든_일괄권한은_비관리_부서엔_못_붙인다(client):
    """부서에 붙이면 그 부서 사람이 전부 권한관리자가 되고, 인원이 늘면 따라 는다.
    예외는 본사 재무팀·전산정보팀(관리팀)뿐 — 그 외 부서는 여전히 막는다."""
    role = _make(client, "관리자", ["appraisals", "permissionManage"])
    # 비관리 부서(본사 집행부)엔 못 붙인다.
    res = client.post("/api/permissions/departments", json={
        "office_id": "10", "department_name": "집행부", "role_id": role["role_id"]})
    assert res.json()["success"] is False, res.text
    assert "권한 관리" in res.json()["message"]

    # 개인에게는 줄 수 있어야 한다 — 관리자는 사람을 보고 지정한다.
    ok = _make(client, "일반", ["appraisals"])
    assert ok["role_id"] > 0


def test_본사_관리팀은_권한관리를_부서로_줄_수_있다(client):
    """재무팀·전산정보팀은 이 시스템 운영팀이라 부서 단위 관리자를 허용한다
    (2026-08-18 사용자 지정) — 새 입사자도 자동으로 관리자가 된다."""
    role = _make(client, "관리팀전체", ["appraisals", "permissionManage"])
    for dept in ("재무팀", "전산정보팀"):
        res = client.post("/api/permissions/departments", json={
            "office_id": "10", "department_name": dept, "role_id": role["role_id"]})
        assert res.json()["success"] is True, (dept, res.text)
    # 붙어 있는 관리팀 일괄권한에 권한관리를 더 끼워 넣는 것도 허용(가드가 안 걸린다).
    res = client.post("/api/permissions/roles", json={
        "role_id": role["role_id"], "name": "관리팀전체",
        "menu_keys": ["appraisals", "receivables", "permissionManage"]})
    assert res.json()["success"] is True, res.text


def test_부서를_빈_일괄권한으로_바꾸면_확인을_받는다(client, db_session, monkeypatch):
    """메뉴 0개는 빈 화면이 아니라 **로그인 거절**이다(users.py ACCESS_DENIED)."""
    from app.services import access_roles as ar

    empty = _make(client, "권한없음", [])
    body = {"office_id": "10", "department_name": "업무1팀", "role_id": empty["role_id"]}

    monkeypatch.setattr(ar, "locked_out_count", lambda db, **kw: 7)
    res = client.post("/api/permissions/departments", json=body)
    assert res.status_code == 409, res.text
    assert res.json()["code"] == "ROLE_LOCKOUT_CONFIRM"
    assert "7명" in res.json()["message"]

    # 확인을 받으면 진행한다 — 막는 게 아니라 묻는 것이다.
    res = client.post("/api/permissions/departments",
                      json={**body, "confirm_lockout": True})
    assert res.json()["success"] is True, res.text


def test_조회범위_끔은_켬을_덮고_정하지않음은_그대로_둔다(client, db_session):
    """'정하지 않음'(null)과 '끔'(false)은 다른 값이다.

    클린 모델(2026-08-18)에는 코드 기본값의 '켬'이 없다. 그래서 이 구별은 **일괄권한이
    남열람을 켠 위에서** 본다 — 개인 예외의 null 은 일괄권한의 켬을 그대로 두고, false 는
    덮어 끈다. 체크박스만 있던 시절엔 체크를 풀어도 null 이 가서 안 꺼졌다(원래 검수 취지).
    """
    identity = ap.PolicyIdentity(
        usr_seq=777, usr_id="y", emp_name="재무", office_id="10",
        department_code=None, department_name="재무팀", employee_type="일반직",
        is_appraiser=False)
    # 부서 일괄권한이 남열람을 켠다(밑층 True).
    on = _make(client, "재무기본", ["appraisals"], view_other_users=True)
    client.post("/api/permissions/departments", json={
        "office_id": "10", "department_name": "재무팀", "role_id": on["role_id"]})
    grant = ap.resolve_role(db_session, identity)
    assert ap.build_access_policy(identity, grant=grant)["view_other_users"] is True

    # 개인 예외 '끔'(N)은 일괄권한의 켬을 덮어 끈다.
    row_off = ap.AccessPolicy(usr_seq=777, view_other_users_override="N", active="Y")
    assert ap.build_access_policy(
        identity, row_off, grant=grant)["view_other_users"] is False
    # 개인 예외 '정하지 않음'(null)은 일괄권한의 켬을 그대로 둔다.
    row_null = ap.AccessPolicy(usr_seq=777, view_other_users_override=None, active="Y")
    assert ap.build_access_policy(
        identity, row_null, grant=grant)["view_other_users"] is True


# ── 2026-08-16 진단: 8/13 가드 두 개가 두 번에 나누면 우회됐다 ─────────────


def test_붙인_뒤에_권한관리를_끼워_넣는_길을_막는다(client):
    """가드가 '붙일 때' 만 봐서, 순서를 바꾸면 그냥 통과했다.

    깨끗한 일괄권한을 부서에 붙여 두고 나중에 permissionManage 를 끼워 넣으면
    그 부서 사람 전부가 권한관리자가 된다 — 붙일 때 막은 것과 결과가 같다.
    """
    role = _make(client, "관리자후보", ["appraisals"])
    res = client.post("/api/permissions/departments", json={
        "office_id": "10", "department_name": "집행부", "role_id": role["role_id"]})
    assert res.json()["success"] is True, res.text

    # 이제 같은 일괄권한에 권한관리를 끼워 넣는다 — (집행부는 비관리 부서라) 막혀야 한다.
    res = client.post("/api/permissions/roles", json={
        "role_id": role["role_id"], "name": "관리자후보",
        "menu_keys": ["appraisals", "permissionManage"]})
    assert res.json()["success"] is False, res.text
    assert "권한 관리" in res.json()["message"]

    # 부서에서 떼면 고칠 수 있어야 한다 — 막는 게 목적이 아니다.
    client.post("/api/permissions/departments", json={
        "office_id": "10", "department_name": "집행부", "role_id": None})
    res = client.post("/api/permissions/roles", json={
        "role_id": role["role_id"], "name": "관리자후보",
        "menu_keys": ["appraisals", "permissionManage"]})
    assert res.json()["success"] is True, res.text


def test_붙어_있는_일괄권한을_빈_메뉴로_저장하면_확인을_받는다(client, monkeypatch):
    """메뉴 0개는 로그인 거절이다. 붙일 때만 세고 고칠 때는 안 셌다."""
    from app.services import access_roles as ar

    role = _make(client, "업무팀", ["appraisals", "payments"])
    client.post("/api/permissions/departments", json={
        "office_id": "10", "department_name": "업무1팀", "role_id": role["role_id"]})

    monkeypatch.setattr(ar, "locked_out_count", lambda db, **kw: 9)
    body = {"role_id": role["role_id"], "name": "업무팀", "menu_keys": []}
    res = client.post("/api/permissions/roles", json=body)
    assert res.status_code == 409, res.text
    assert res.json()["code"] == "ROLE_LOCKOUT_CONFIRM"
    assert "9명" in res.json()["message"]

    res = client.post("/api/permissions/roles", json={**body, "confirm_lockout": True})
    assert res.json()["success"] is True, res.text


def test_자기_권한은_자기가_바꿀_수_있되_권한관리는_못_뗀다(client, monkeypatch):
    """2026-08-19 사용자: 관리자 1명뿐인 지사는 자기 권한을 자기가 바꿔야 한다.
    그래서 자기부여를 연다 — 단 자기 '권한 관리'는 스스로 못 뗀다(자기잠금 방지).

    옛날엔 '요청자≠대상'을 하드로 막았는데, 지사 관리자가 하나뿐이면 자기 권한을
    영영 못 고치는 막다른 길이 됐다. 이제 붙인 뒤 본인 유효권한을 보고, 권한관리가
    남으면 허용하고 사라지면 되돌린다.
    """
    role = _make(client, "관리자", ["permissionManage", "appraisals"])
    # 자기(2012)에게 붙이기 — 권한관리를 유지하므로 허용된다.
    res = client.post("/api/permissions/users/role", json={
        "usr_seq": 2012, "role_id": role["role_id"]})
    assert res.json()["success"] is True, res.text

    # 붙인 결과 본인이 권한관리를 잃으면(자기잠금) 막고 되돌린다.
    # (같은 일괄권한 재전송은 멱등 no-op 이라 자기검사 전에 빠져나간다 — 다른 일괄권한으로 바꿔야
    #  실제로 검사에 닿는다.)
    role2 = _make(client, "제한", ["appraisals"])
    from app.services import access_policy as _ap
    from app.services import permissions as _perm
    _me = _ap.PolicyIdentity(
        usr_seq=2012, usr_id="me", emp_name="나", office_id="10",
        department_code=None, department_name="전산정보팀",
        employee_type="전산정보팀", is_appraiser=False)
    monkeypatch.setattr(_perm, "_policy_target", lambda db, seq: ("src", _me))
    monkeypatch.setattr(
        _ap, "load_access_policy",
        lambda db, ident: {"menu_permissions": {"permissionManage": False}})
    res = client.post("/api/permissions/users/role", json={
        "usr_seq": 2012, "role_id": role2["role_id"]})
    assert res.json()["success"] is False, res.text
    assert "권한 관리" in res.json()["message"]

    # 남에게는 당연히 줄 수 있다.
    res = client.post("/api/permissions/users/role", json={
        "usr_seq": 555, "role_id": role["role_id"]})
    assert res.json()["success"] is True, res.text


# ── 일괄 적용 (2026-08-17 요청) — 부서 여러 개·사람 여러 명에 한 번에 ────────
# 원칙: 일괄이라는 지름길에서 기존 가드가 하나도 빠지면 안 된다. 그래서 아래
# 시험들은 "되는가"보다 "막을 것을 대상마다 막는가"를 본다.


def test_부서_여러_개에_한_번에_붙는다(client):
    role = _make(client, "일반", ["appraisals", "payments"])
    res = client.post("/api/permissions/departments/bulk", json={
        "role_id": role["role_id"],
        "targets": [
            {"office_id": "10", "department_name": "업무1팀"},
            {"office_id": "10", "department_name": "업무2팀"},
            {"office_id": "21", "department_name": "업무팀"},
        ]})
    data = res.json()["data"]
    assert len(data["applied"]) == 3, res.text
    assert data["blocked"] == [] and data["needs_confirm"] == []
    items = client.get("/api/permissions/roles").json()["data"]["items"]
    assert items[0]["used_by"]["departments"] == 3


def test_일괄에서도_권한관리_부서_금지가_대상마다_걸린다(client):
    """일괄이 우회로가 되면 부서 인원이 늘 때마다 관리자가 따라 는다."""
    role = _make(client, "관리자", ["permissionManage", "appraisals"])
    res = client.post("/api/permissions/departments/bulk", json={
        "role_id": role["role_id"],
        "targets": [
            {"office_id": "10", "department_name": "업무1팀"},
            {"office_id": "10", "department_name": "총무팀"},
        ]})
    data = res.json()["data"]
    assert data["applied"] == []
    assert len(data["blocked"]) == 2
    assert all("권한 관리" in b["reason"] for b in data["blocked"])


def test_일괄_잠금은_모아서_확인받는다(client, monkeypatch):
    """메뉴 0개는 로그인 거절이다 — 일괄이라고 조용히 잠그면 부서 수십 개가
    한 번에 잠긴다. 1차에서 모아 돌려주고, 확인 후 그 대상만 다시 보낸다."""
    from app.services import access_roles as ar

    empty = _make(client, "권한없음", [])
    monkeypatch.setattr(ar, "locked_out_count", lambda db, **kw: 4)
    body = {"role_id": empty["role_id"], "targets": [
        {"office_id": "10", "department_name": "업무1팀"},
        {"office_id": "10", "department_name": "업무2팀"},
    ]}
    res = client.post("/api/permissions/departments/bulk", json=body)
    data = res.json()["data"]
    assert data["applied"] == []
    assert [n["locked"] for n in data["needs_confirm"]] == [4, 4]

    res = client.post("/api/permissions/departments/bulk",
                      json={**body, "confirm_lockout": True})
    assert len(res.json()["data"]["applied"]) == 2


def test_사람_여러_명에_한_번에_붙고_자기부여도_된다(client):
    """2026-08-19: 자기부여를 연다 — 관리자 1명 지사가 자기를 관리해야 하므로.
    (테스트 DB는 원천표가 없어 유효권한을 못 풀므로 자기잠금 검사는 통과시킨다 —
    자기잠금 차단 자체는 test_자기_권한은_자기가_바꿀_수_있되_권한관리는_못_뗀다 가 지킨다.)"""
    role = _make(client, "일반", ["appraisals"])
    res = client.post("/api/permissions/users/role/bulk", json={
        "role_id": role["role_id"],
        "usr_seqs": [555, 777, 2012]})   # 2012 = 로그인 사용자 자신
    data = res.json()["data"]
    assert sorted(data["applied"]) == [555, 777, 2012], res.text
    assert data["blocked"] == []

    # 배정 조회로 미리 체크를 그릴 수 있어야 한다.
    items = client.get("/api/permissions/roles/user-assignments").json()["data"]["items"]
    assert {(i["usr_seq"], i["role_id"]) for i in items} == {
        (555, role["role_id"]), (777, role["role_id"]), (2012, role["role_id"])}


def test_지사_관리자는_일괄로도_남의_지사를_못_바꾼다(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_access] = lambda: _access(office="10")
    try:
        head = _signed(TestClient(app))
        role = _make(head, "일반", ["appraisals"])
        app.dependency_overrides[get_current_access] = lambda: _access(office="21")
        branch = _signed(TestClient(app))
        res = branch.post("/api/permissions/departments/bulk", json={
            "role_id": role["role_id"],
            "targets": [
                {"office_id": "10", "department_name": "업무1팀"},   # 남의 지사
                {"office_id": "21", "department_name": "업무팀"},    # 자기 지사
            ]})
        data = res.json()["data"]
        assert [a["office_id"] for a in data["applied"]] == ["21"]
        assert data["blocked"][0]["office_id"] == "10"
        assert "다른 지사" in data["blocked"][0]["reason"]
    finally:
        app.dependency_overrides.clear()


def test_일괄도_증표_없이는_막힌다(db_session):
    """일괄은 단건보다 파급이 크다 — 헤더 숫자만으로 열리면 더 위험하다."""
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_access] = lambda: _access()
    try:
        bare = TestClient(app)          # 증표 없음
        res = bare.post("/api/permissions/departments/bulk", json={
            "role_id": None,
            "targets": [{"office_id": "10", "department_name": "업무1팀"}]})
        assert res.status_code == 401, res.text
        assert res.json()["code"] == "AUTH_TOKEN_REQUIRED"
    finally:
        app.dependency_overrides.clear()


def test_개인_예외_저장도_증표_없이는_막힌다(db_session):
    """PUT /users/{usr_seq} 는 개인 예외를 저장하는 **주 저장 버튼**이 부르는
    엔드포인트다. 2026-08-16 증표 관문을 8개에 달 때 여기만 require_menu(읽기
    가드)로 남아, 헤더 숫자 하나만으로 남의 개인 예외를 갈아치울 수 있었다
    (2026-08-17 로그인 진단 중 발견). 나머지 쓰기와 같은 잣대를 건다.

    서비스층(save_access_policy)에 자기부여·마지막관리자 가드가 있어 최악은
    막혔지만, 관문 자체가 뚫려 있으면 그 가드에 안 걸리는 변경(남의 view 범위
    끄기 등)은 증표 없이 통과했다."""
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_access] = lambda: _access()
    try:
        bare = TestClient(app)          # 증표 없음
        res = bare.put("/api/permissions/users/555", json={
            "requester_usr_seq": _ACCESS_USR_SEQ, "menu_overrides": {"bonus": True}})
        # 관문에서 잘려야 한다. 관문이 require_menu(읽기)로 되돌아가면 여기를
        # 통과해 _policy_target 이 실 DB 를 때리고 다른 오류가 난다 — 그때 이
        # 단언이 깨지므로, 관문이 쓰기용인지를 정확히 지킨다.
        assert res.status_code == 401, res.text
        assert res.json()["code"] == "AUTH_TOKEN_REQUIRED"
    finally:
        app.dependency_overrides.clear()


# ── 2026-08-17 적대 검증에서 잡힌 결함들 ─────────────────────────────────


def test_일괄_혼합에서_잠금_부서가_뒤_커밋에_묻지_않는다(client, db_session, monkeypatch):
    """가장 나쁜 조합이었다: LockoutError 가 rollback 을 안 타서, flush 된 잠금
    부서 배정이 **다음 성공 대상의 commit 에 묻어** 확인 없이·이력 없이
    커밋됐다. 응답은 '미적용(needs_confirm)'이라고 거짓말까지 했다."""
    from app.services import access_roles as ar

    empty = _make(client, "권한없음", [])
    monkeypatch.setattr(
        ar, "locked_out_count",
        lambda db, *, office_id, department_name, org=None:
            7 if department_name == "잠금팀" else 0)
    res = client.post("/api/permissions/departments/bulk", json={
        "role_id": empty["role_id"],
        "targets": [
            {"office_id": "10", "department_name": "잠금팀"},   # 먼저 잠금
            {"office_id": "10", "department_name": "깨끗팀"},   # 뒤에 성공 → 커밋
        ]})
    data = res.json()["data"]
    assert [a["department_name"] for a in data["applied"]] == ["깨끗팀"]
    assert [n["department_name"] for n in data["needs_confirm"]] == ["잠금팀"]
    # 응답이 '미적용'이라 했으면 DB 에도 정말 없어야 한다.
    assert db_session.get(AccessDeptRole, ("10", "잠금팀")) is None, \
        "잠금 부서가 뒤 커밋에 묻어 몰래 커밋됐다"
    row = db_session.get(AccessDeptRole, ("10", "깨끗팀"))
    assert row is not None and row.active == "Y"


def test_같은_배정_재전송은_또_적용하지_않는다(client):
    """확인 재전송·중복 클릭이 같은 내용의 이력을 또 쌓으면 감사 추적이
    오염된다 — 같은 값이면 no-op(멱등)이어야 한다."""
    role = _make(client, "일반", ["appraisals"])
    body = {"role_id": role["role_id"],
            "targets": [{"office_id": "10", "department_name": "업무1팀"}]}
    assert len(client.post("/api/permissions/departments/bulk", json=body)
               .json()["data"]["applied"]) == 1
    # 같은 내용 재전송 — 서비스가 skipped 로 접고, 값은 그대로다.
    assert len(client.post("/api/permissions/departments/bulk", json=body)
               .json()["data"]["applied"]) == 1
    items = client.get("/api/permissions/roles").json()["data"]["items"]
    assert items[0]["used_by"]["departments"] == 1


def test_개인_일괄의_중복과_비양수는_걸러진다(client):
    """아무 숫자나 넣으면 유령 행이 커밋되고 '성공'으로 보고됐다."""
    role = _make(client, "일반", ["appraisals"])
    res = client.post("/api/permissions/users/role/bulk", json={
        "role_id": role["role_id"], "usr_seqs": [555, 555, 0, -3, 777]})
    data = res.json()["data"]
    assert sorted(data["applied"]) == [555, 777], res.text     # 중복은 한 번으로
    assert {b["usr_seq"] for b in data["blocked"]} == {0, -3}
    assert all("올바르지 않은" in b["reason"] for b in data["blocked"])


def test_부서_일괄이_조직도를_한_번만_읽는다(client, monkeypatch):
    """대상마다 전사 스캔을 다시 하면 부서 수십 개 일괄이 수십 초짜리 요청이
    된다(실측 20개=20회). 조직도는 루프 동안 불변이라 한 번이면 된다."""
    import app.routers.permissions as rp
    from app.services import access_roles as ar

    calls = []
    monkeypatch.setattr(rp, "organization_preview",
                        lambda db, visible_office_id=None: calls.append(1) or {"offices": []})
    # locked_out_count 안의 지연 임포트 경로도 막는다 — org 가 전달되면 안 불린다.
    import app.services.permissions as perm
    monkeypatch.setattr(perm, "organization_preview",
                        lambda db, visible_office_id=None: calls.append(1) or {"offices": []})
    role = _make(client, "일반", ["appraisals"])
    client.post("/api/permissions/departments/bulk", json={
        "role_id": role["role_id"],
        "targets": [{"office_id": "10", "department_name": f"팀{n}"} for n in range(5)]})
    assert len(calls) == 1, f"조직도를 {len(calls)}번 읽었다 — 대상 5개에 1번이어야 한다"


def test_지사는_개인배정_조회가_자기_지사로_좁혀진다(db_session, monkeypatch):
    """같은 라우터의 GET /departments 는 자기 지사로 좁히는데 여기만 전사가
    보였다 — 지사 관리자는 어차피 남의 지사를 못 바꾼다, 볼 이유도 없다."""
    import app.routers.permissions as rp

    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_access] = lambda: _access(office="10")
    try:
        head = _signed(TestClient(app))
        role = _make(head, "일반", ["appraisals"])
        for seq in (555, 808):
            head.post("/api/permissions/users/role",
                      json={"usr_seq": seq, "role_id": role["role_id"]})
        monkeypatch.setattr(
            rp, "organization_preview",
            lambda db, visible_office_id=None: {"offices": [{
                "id": "21", "departments": [{"name": "업무팀", "employees": [
                    {"usr_seq": 808}]}]}]})
        app.dependency_overrides[get_current_access] = lambda: _access(office="21")
        branch = _signed(TestClient(app))
        items = branch.get("/api/permissions/roles/user-assignments").json()["data"]["items"]
        assert [i["usr_seq"] for i in items] == [808], items
    finally:
        app.dependency_overrides.clear()

_BRANCH_USER = 9101
_HEAD_USER = 9102


@pytest.fixture()
def branch_person(monkeypatch):
    """usr_seq 9101 은 지사(21) 업무팀 사람이다 — 인메모리 DB 에는 조직 표가
    없으므로 신원만 붙여 준다. 잠금 판정 자체는 흉내내지 않는다."""
    from app.services import permissions as perm_mod

    def fake_target(db, usr_seq):
        # 9102 는 본사 사람 — 같은 일괄에 섞어 '한 사람이 거절돼도 나머지는
        # 그대로 간다'와 '거절된 사람이 묻어가지 않는다'를 함께 볼 수 있다.
        if int(usr_seq) == _HEAD_USER:
            return "본사", ap.PolicyIdentity(
                usr_seq=usr_seq, usr_id="h", emp_name="본사사람", office_id="10",
                department_code=None, department_name="집행부",
                employee_type="집행부", is_appraiser=False)
        return "지사", ap.PolicyIdentity(
            usr_seq=usr_seq, usr_id="b", emp_name="지사사람", office_id="21",
            department_code=None, department_name="업무팀",
            employee_type="일반직원", is_appraiser=False)

    monkeypatch.setattr(perm_mod, "_policy_target", fake_target)
    return _BRANCH_USER


def test_지사_사람에게_본사전용_일괄권한을_걸면_한_번_묻는다(client, branch_person):
    """사용자 지적(2026-08-17): "지사에서 본사쪽 세트권한 넣으면 안 되는 거 아냐?"

    권한이 새지는 않는다 — available 교집합이 본사 전용을 전부 잘라낸다. 문제는
    반대쪽이다: 다 잘리면 **0개**가 되고, 0개는 빈 화면이 아니라 로그인 거절이다.
    부서 경로에는 409 확인이 있었는데 개인 경로에는 없어서 조용히 잠겼다.
    """
    role = _make(client, "본사전용만", ["bonus", "cardVouchers"])
    body = {"usr_seq": branch_person, "role_id": role["role_id"]}

    res = client.post("/api/permissions/users/role", json=body)
    assert res.status_code == 409, f"확인 없이 그냥 들어갔다: {res.text}"
    assert res.json()["code"] == "ROLE_LOCKOUT_CONFIRM"

    # 막는 게 아니라 묻는 것이다 — 확인하면 그대로 한다.
    res = client.post("/api/permissions/users/role",
                      json={**body, "confirm_lockout": True})
    assert res.json()["success"] is True, res.text


def test_지사에_본사_전체일괄권한은_잘려서_들어갈_뿐_막지_않는다(client, branch_person):
    """같은 질문의 반대편. '본사 전체메뉴' 처럼 지사에도 열리는 메뉴가 섞여 있으면
    교집합이 남는 것만 켜 준다 — 이건 정상 동작이라 묻지 않고 그냥 통과해야 한다.
    여기서 409 가 나면 쓸 만한 일괄 부여가 전부 막힌다."""
    role = _make(client, "섞인일괄권한", ["bonus", "appraisals"])
    res = client.post("/api/permissions/users/role",
                      json={"usr_seq": branch_person, "role_id": role["role_id"]})
    assert res.json()["success"] is True, res.text


def test_거절된_개인_부여는_흔적을_남기지_않는다(client, db_session, branch_person):
    """409 를 돌려주고도 행이 남아 있으면 다음 요청의 commit 에 묻어 들어간다 —
    부서 경로에서 실제로 났던 사고다(LockoutError 가 RoleError 가 아니라 롤백을
    안 탔다). 개인 경로에도 같은 시험을 건다."""
    role = _make(client, "본사전용만2", ["bonus"])
    client.post("/api/permissions/users/role",
                json={"usr_seq": branch_person, "role_id": role["role_id"]})
    db_session.expire_all()
    assert db_session.get(AccessUserRole, branch_person) is None, "거절해 놓고 행이 남았다"


def test_개인_일괄도_잠기는_사람을_모아_되돌린다(client, branch_person):
    """일괄이라는 지름길에서 확인이 빠지면 안 된다. 부서 일괄과 같은 흐름:
    잠기는 사람은 적용하지 않고 needs_confirm 으로 돌려준다."""
    role = _make(client, "본사전용만3", ["bonus"])
    body = {"role_id": role["role_id"], "usr_seqs": [branch_person]}

    data = client.post("/api/permissions/users/role/bulk", json=body).json()["data"]
    assert data["applied"] == [], "잠기는 사람이 그대로 적용됐다"
    assert [x["usr_seq"] for x in data["needs_confirm"]] == [branch_person]
    assert data["blocked"] == [], "확인받을 일을 실패로 처리했다"

    data = client.post("/api/permissions/users/role/bulk",
                       json={**body, "confirm_lockout": True}).json()["data"]
    assert data["applied"] == [branch_person]


def test_거절된_사람은_다음_사람의_commit_에_묻어가지_않는다(client, db_session,
                                                            branch_person):
    """부서 경로에서 실제로 났던 사고를 개인 경로에 박아 둔다.

    LockoutError 가 RoleError 의 자식이 아니어서 `except RoleError: rollback()` 을
    그냥 지나쳤고, flush 된 행이 세션에 남아 **다음 대상이 commit 할 때 함께**
    들어갔다 — 응답은 '미적용'이라고 말하면서 DB 에는 들어가 있었다. 이력도 없이.

    지금은 잠금 검사가 쓰기 앞에 있어 더럽힐 것 자체가 없다. 그 배치가 계약이다.
    """
    role = _make(client, "본사전용만4", ["bonus"])
    res = client.post("/api/permissions/users/role/bulk", json={
        "role_id": role["role_id"], "usr_seqs": [branch_person, _HEAD_USER]})
    data = res.json()["data"]

    assert data["applied"] == [_HEAD_USER], "멀쩡한 사람까지 막혔다"
    assert [x["usr_seq"] for x in data["needs_confirm"]] == [branch_person]

    db_session.expire_all()
    assert db_session.get(AccessUserRole, _HEAD_USER) is not None
    assert db_session.get(AccessUserRole, branch_person) is None, \
        "거절해 놓고 다음 사람의 commit 에 묻어 들어갔다"


def test_빈_예외행은_개인_설정으로_세지_않는다(db_session):
    """행이 있다고 다 예외는 아니다. 세 칸이 다 비면 아무것도 안 바꾸는 빈 행인데,
    이걸 세면 '개인 설정' 표가 아무 데나 붙어 의미를 잃는다."""
    from app.models.access_policy import AccessPolicy
    from app.services.access_roles import personal_override_usr_seqs

    AccessPolicy.__table__.create(db_session.get_bind(), checkfirst=True)
    db_session.add_all([
        AccessPolicy(usr_seq=1, usr_id="a", active="Y"),                       # 빈 행
        AccessPolicy(usr_seq=2, usr_id="b", active="Y", menu_overrides_json="{}"),
        AccessPolicy(usr_seq=3, usr_id="c", active="Y",
                     menu_overrides_json='{"bonus": true}'),                   # 진짜 예외
        AccessPolicy(usr_seq=4, usr_id="d", active="Y",
                     view_all_offices_override="N"),                           # 이것도 예외
        AccessPolicy(usr_seq=5, usr_id="e", active="N",
                     menu_overrides_json='{"bonus": true}'),                   # 죽은 행
    ])
    db_session.commit()

    assert sorted(personal_override_usr_seqs(db_session)) == [3, 4]


def test_개인_설정_목록이_배정과_같은_응답으로_온다(client, db_session):
    """따로 받으면 한쪽만 늦게 도착해 표가 깜빡인다 — 늘 같이 쓰이는 둘이다."""
    from app.models.access_policy import AccessPolicy

    AccessPolicy.__table__.create(db_session.get_bind(), checkfirst=True)
    db_session.add(AccessPolicy(usr_seq=777, usr_id="z", active="Y",
                                menu_overrides_json='{"bonus": true}'))
    db_session.commit()

    data = client.get("/api/permissions/roles/user-assignments").json()["data"]
    assert data["personal_overrides"] == [777]
