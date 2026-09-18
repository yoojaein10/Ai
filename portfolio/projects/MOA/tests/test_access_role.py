"""일괄권한(역할) — 부서·개인 적용과 해석 순서.

2026-08-13 사용자 확정 사항을 계약으로 박는다.
  ① 코드 기본값(과도기)  ② 부서 일괄권한이 ①을 **대체**  ③ 개인 일괄권한이 ②를 **대체**
  ④ 개인 예외(a10_access_policy)가 그 위에 얹힌다
즉 **개인이 부서를 이긴다.** 그리고 일괄권한은 **참조**라 고치면 쓰는 곳이 따라간다.

왜 '더하기'가 아니라 '대체'인가: 화면에서 체크를 푼 메뉴가 코드 기본값 때문에 다시
켜지면, 사람이 끈 것을 시스템이 되살리는 꼴이라 설명할 수 없다.
"""

import json

from app.models.access_policy import AccessPolicy
from app.models.access_role import AccessDeptRole, AccessRole, AccessUserRole
from app.services import access_policy as ap


def _identity(dept="재무팀", office=ap.HEAD_OFFICE_ID, appraiser=False, usr_seq=999999):
    return ap.PolicyIdentity(
        usr_seq=usr_seq, usr_id="tester", emp_name="홍길동", office_id=office,
        department_code=None, department_name=dept, employee_type=dept,
        is_appraiser=appraiser,
    )


def _grant(keys, *, view_all=None, view_others=None, source="dept", name="일괄권한"):
    return ap.RoleGrant(
        role_id=1, name=name, menu_keys=frozenset(keys),
        view_all_offices=view_all, view_other_users=view_others, source=source,
    )


class _FakeDb:
    """db.get(Model, key) 만 흉내 낸다."""

    def __init__(self, **rows):
        self.rows = rows          # {'user': AccessUserRole, 'dept': ..., 'role': {id: AccessRole}}

    def get(self, model, key):
        if model is AccessUserRole:
            return self.rows.get("user")
        if model is AccessDeptRole:
            return self.rows.get("dept")
        if model is AccessRole:
            return (self.rows.get("roles") or {}).get(key)
        if model is AccessPolicy:
            return self.rows.get("policy")
        return None

    def rollback(self):
        pass


def _role(role_id, name, keys, view_all=None, view_others=None, active="Y"):
    row = AccessRole()
    row.role_id, row.name, row.active = role_id, name, active
    row.menu_keys_json = json.dumps(list(keys), ensure_ascii=False)
    row.view_all_offices, row.view_other_users = view_all, view_others
    return row


def test_일괄권한이_없으면_메뉴_0개다():
    """클린 모델(2026-08-18): 코드 기본값 제거 — 부서 이름으로 권한을 추정하지 않는다.
    일괄권한도 개인 예외도 없으면 메뉴 0개(= 로그인 거절). 그래서 배포 전 표준 일괄권한 시드가
    필수고, 시드 후엔 부서 일괄권한이 채운다. policy_source 는 아무것도 없으니 'default'."""
    policy = ap.build_access_policy(_identity("재무팀"))
    assert policy["menu_keys"] == []
    assert policy["policy_source"] == "default"
    assert policy["role"] is None


def test_부서_일괄권한이_코드_기본값을_대체한다():
    """더하는 게 아니라 갈아치운다. 재무팀은 코드 기본값이 전체 메뉴인데,
    일괄권한이 두 개만 주면 두 개만 남아야 한다."""
    grant = _grant({"appraisals", "payments"}, source="dept")
    policy = ap.build_access_policy(_identity("재무팀"), grant=grant)
    assert policy["menu_keys"] == ["appraisals", "payments"]
    assert policy["menu_permissions"]["bonus"] is False, "기본값이 되살아나면 안 된다"
    assert policy["policy_source"] == "role:dept"
    assert policy["role"]["name"] == "일괄권한"


def test_개인_일괄권한이_부서_일괄권한을_이긴다():
    """resolve_role 이 개인을 먼저 본다. 부서로 깔고 예외인 사람만 개인으로 덮는
    운용을 하려면 이 순서여야 한다."""
    db = _FakeDb(
        user=_user_role(7), dept=_dept_role(8),
        roles={7: _role(7, "개인", {"mySales"}), 8: _role(8, "부서", {"appraisals"})},
    )
    grant = ap.resolve_role(db, _identity())
    assert grant.source == "user" and grant.name == "개인"
    assert grant.menu_keys == frozenset({"mySales"})


def test_개인_일괄권한이_없으면_부서_일괄권한을_쓴다():
    db = _FakeDb(dept=_dept_role(8), roles={8: _role(8, "부서", {"appraisals"})})
    grant = ap.resolve_role(db, _identity())
    assert grant.source == "dept" and grant.menu_keys == frozenset({"appraisals"})


def test_지운_일괄권한은_안_쓴다():
    """active='N' 이면 없는 것으로 본다. 개인 일괄권한이 지워졌으면 부서로 내려간다."""
    db = _FakeDb(
        user=_user_role(7), dept=_dept_role(8),
        roles={7: _role(7, "개인", {"mySales"}, active="N"),
               8: _role(8, "부서", {"appraisals"})},
    )
    grant = ap.resolve_role(db, _identity())
    assert grant is not None and grant.source == "dept"


def test_개인_예외가_일괄권한_위에_얹힌다():
    """일괄권한으로 부서를 깔고, 그 사람만 한 칸 더 주거나 뺄 수 있어야 한다."""
    row = AccessPolicy()
    row.active = "Y"
    row.view_all_offices_override = None
    row.view_other_users_override = None
    row.menu_overrides_json = json.dumps({"bonus": True, "appraisals": False})
    grant = _grant({"appraisals", "payments"}, source="dept")
    policy = ap.build_access_policy(_identity("재무팀"), row, grant=grant)
    assert policy["menu_permissions"]["bonus"] is True, "개인이 더한 것"
    assert policy["menu_permissions"]["appraisals"] is False, "개인이 뺀 것"
    assert policy["menu_permissions"]["payments"] is True, "일괄권한이 준 것은 남는다"
    assert policy["policy_source"] == "override"


def test_일괄권한이_두_플래그를_정할_수도_안_정할_수도_있다():
    """None 은 '이 일괄권한은 안 정한다' — 아래 층(코드 기본값)이 그대로 산다.
    평가사에게 남 열람을 주려면 일괄권한에서 'Y' 로 명시해야 한다."""
    ident = _identity("주주평가사", appraiser=True)
    base = ap.build_access_policy(ident, grant=_grant({"appraisals"}))
    assert base["view_other_users"] is False, "안 정하면 기본값(평가사=거짓)"
    on = ap.build_access_policy(
        ident, grant=_grant({"appraisals"}, view_others=True))
    assert on["view_other_users"] is True


def test_지사는_일괄권한으로도_전지사를_못_연다():
    """일괄권한이 'Y' 라고 해도 지사 사용자는 다른 지사를 못 본다 — 이 방어선은
    일괄권한보다 아래에 있다(build_access_policy 마지막 줄)."""
    ident = _identity("재무팀", office="21")
    policy = ap.build_access_policy(ident, grant=_grant({"appraisals"}, view_all=True))
    assert policy["view_all_offices"] is False


def test_표가_없으면_조용히_기본값으로_떨어진다():
    """운영에 표를 만들기 전에도 화면이 죽으면 안 된다."""
    class _Broken:
        def get(self, *a, **k):
            from sqlalchemy.exc import SQLAlchemyError
            raise SQLAlchemyError("no such table")

        def rollback(self):
            pass

    assert ap.resolve_role(_Broken(), _identity()) is None


def test_일괄권한은_available_을_넘지_못한다():
    """일괄권한에 본사 전용 메뉴를 담아 지사 사람에게 붙여도 열리면 안 된다."""
    ident = _identity("재무팀", office="21")
    policy = ap.build_access_policy(ident, grant=_grant({"bonus", "appraisals"}))
    assert policy["menu_permissions"]["bonus"] is False
    assert policy["menu_permissions"]["appraisals"] is True


def _user_role(role_id):
    row = AccessUserRole()
    row.usr_seq, row.role_id, row.active = 999999, role_id, "Y"
    return row


def _dept_role(role_id):
    row = AccessDeptRole()
    row.office_id, row.department_name = ap.HEAD_OFFICE_ID, "재무팀"
    row.role_id, row.active = role_id, "Y"
    return row
