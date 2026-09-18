import json

import pytest
from fastapi import HTTPException

from app.dependencies import resolve_office_scope, scoped_employee_name
from app.models.access_policy import AccessPolicy
from app.services.access_policy import (
    BRANCH_FINANCE_MENU_KEYS,
    MENU_KEYS,
    SHARED_MENU_KEYS,
    available_menu_keys,
    build_access_policy,
    identity_from_row,
)
from app.services.appraisals import _where_clause


def identity(
    *,
    office_id: str,
    seat_dept: str | None = None,
    chrg_biz: str | None = None,
    appraisal_fl: str = "1",
    emp_name: str = "테스트",
    usr_seq: int = 100,
):
    return identity_from_row(
        {
            "usr_seq": usr_seq,
            "usr_id": "tester",
            "emp_name": emp_name,
            "office_id": office_id,
            "seat_dept": seat_dept,
            "chrg_biz": chrg_biz,
            "appraisal_fl": appraisal_fl,
        }
    )


def test_묶음_없으면_본사_재무도_메뉴_0개다():
    """클린 모델(2026-08-18 사용자 요청): 코드 기본값(부서 heuristic) 제거 — 부서 이름
    으로 권한을 추정하지 않는다. 본사 재무팀도 **묶음이 없으면 메뉴 0개**다(권한은
    명시적 묶음에서만). is_operations 라벨은 표시용으로 남고, 스코프 기본도 False 다.
    실제 재무팀은 관리자 묶음을 받아 전체 권한이 된다 — 그건 묶음이 정한다."""
    policy = build_access_policy(identity(office_id="10", seat_dept="jae"))

    assert policy["is_operations"] is True          # 라벨은 남는다
    assert policy["menu_keys"] == []                 # 코드 기본값 없음
    assert policy["view_all_offices"] is False
    assert policy["view_other_users"] is False


def test_묶음_없으면_본사_전산정보팀도_메뉴_0개다():
    """전산정보팀도 코드로 권한을 받지 않는다(클린 모델). 실제로는 관리자 묶음을
    개인·부서로 받아 전체 권한이 된다 — 코드가 아니라 묶음이 정한다."""
    policy = build_access_policy(identity(office_id="10", seat_dept="jun"))

    assert policy["menu_keys"] == []
    assert policy["view_all_offices"] is False


def test_branch_it_team_is_not_head_office_it_team():
    """지사 전산총무팀은 다르다. 이름이 비슷해도 본사 전산정보팀이 아니다."""
    policy = build_access_policy(identity(office_id="13", appraisal_fl="1"))

    assert sum(policy["menu_permissions"].values()) == 0


def test_head_office_executive_is_operations_not_appraiser():
    """라벨(is_operations·is_appraiser)은 그대로 계산된다. 다만 클린 모델에서는 코드
    기본값이 없어 집행부도 묶음 없이는 메뉴 0개·스코프 False 다(2026-08-18)."""
    policy = build_access_policy(identity(office_id="10", seat_dept="jip"))

    assert policy["is_operations"] is True
    assert policy["is_appraiser"] is False
    assert policy["menu_keys"] == []                 # 코드 기본값 없음
    assert policy["view_all_offices"] is False


def test_묶음_없으면_본사_평가사도_메뉴_0개다():
    """평가사 라벨·fail-closed 스코프는 유지하되, 코드 기본값(감정서 3종+내실적)은
    걷어냈다 — 평가사 권한도 이제 묶음이 정한다(클린 모델, 2026-08-18)."""
    policy = build_access_policy(identity(office_id="10", seat_dept="ju"))

    assert policy["is_appraiser"] is True
    assert policy["view_all_offices"] is False
    assert policy["view_other_users"] is False
    assert policy["menu_keys"] == []                 # 코드 기본값 없음


def test_branch_appraiser_does_not_get_my_sales_yet():
    """내 매출실적은 본사 감정서만 다룬다 — 지사 평가사에게 켜면 빈 화면이 된다.

    지사는 유치자 등록률이 무너져 있어(울산 0%, 충남 0.2%, 제주 0.6%) 같은 정의로는
    실적이 안 잡힌다. 배정자 폴백을 넣기 전까지 지사에는 노출하지 않는다.
    """
    policy = build_access_policy(identity(office_id="11", appraisal_fl="0"))

    assert policy["menu_permissions"]["mySales"] is False
    assert "mySales" not in available_menu_keys(
        identity(office_id="11", appraisal_fl="0")
    )


def test_head_office_shows_all_menus_but_keeps_role_defaults_off():
    # 본사는 권한관리 화면 통일을 위해 평가사·일반직원도 재무·집행부와 같은 토글을 보되(available)
    # 기본은 off. 지사는 이 규칙에서 제외한다.
    hq_appraiser = identity(office_id="10", seat_dept="ju")
    hq_general = identity(office_id="10", seat_dept=None)
    avail_appraiser = available_menu_keys(hq_appraiser)
    for key in ("salesInput", "bonus", "salesStats", "workReport"):
        assert key in avail_appraiser  # 토글 노출·개별 부여 가능
        assert key in available_menu_keys(hq_general)
    policy = build_access_policy(hq_appraiser)
    for key in ("salesInput", "bonus", "salesStats", "workReport"):
        assert policy["menu_permissions"][key] is False  # 기본은 off
    # 지사 평가사는 여전히 본사 전용 토글이 노출되지 않는다.
    branch_appraiser = identity(office_id="11", appraisal_fl="0")
    assert "salesInput" not in available_menu_keys(branch_appraiser)


def test_묶음_없으면_지사_평가사도_메뉴_0개다():
    """지사 평가사도 코드 기본값(감정서·입금·미수금 3종)을 더 이상 코드로 받지
    않는다(클린 모델). 실제로는 소속의 '기본 열람' 묶음을 받아 그 3종이 열린다 —
    코드가 아니라 묶음이 정한다. 지사 스코프(전지사·남열람)는 그대로 False."""
    policy = build_access_policy(
        identity(office_id="11", appraisal_fl="0", emp_name="김평가")
    )

    assert policy["view_all_offices"] is False
    assert policy["view_other_users"] is False
    assert policy["menu_keys"] == []                 # 코드 기본값 없음


def test_branch_general_employee_has_no_default_menu():
    policy = build_access_policy(identity(office_id="11", appraisal_fl="1"))

    assert policy["is_appraiser"] is False
    assert policy["menu_keys"] == []


def test_branch_finance_has_no_default_menus():
    # 지사는 재무팀이 없는 경우도 있어 재무 특례를 기본값에 두지 않는다 → 재무여도 기본 권한 0.
    policy = build_access_policy(
        identity(office_id="11", chrg_biz="재무총무팀", appraisal_fl="1")
    )

    assert policy["is_branch_finance"] is True
    assert policy["menu_keys"] == []


def test_지사_재무_2종은_지사_전원에게_열리되_켜지지는_않는다():
    """2026-08-17: 지사 재무담당 usr_seq 18개 하드코딩(BRANCH_FINANCE_HOLDERS)을
    걷어냈다 — 담당자가 바뀔 때마다 배포를 해야 했기 때문이다.

    available(토글을 보여 줄까)은 '구조적으로 가능한가'만 말한다. feeBasis·
    paymentSms 는 전수조사에서 '본·지사 공통'으로 확정돼 지사 전원에게 연다.
    실제로 누가 받을지는 화면에서 '지사 재무담당' 묶음으로 정하고, 기본값은
    꺼져 있다 — 여기가 뒤집히면 전 지사가 재무 화면을 받아 버린다.
    """
    from app.services.access_policy import RoleGrant

    # 종전 담당자였던 usr_seq 를 그대로 써도 이제 특별대우가 없어야 한다.
    branch = identity(office_id="11", chrg_biz="업무팀", usr_seq=1449)
    assert BRANCH_FINANCE_MENU_KEYS <= available_menu_keys(branch), "붙일 수조차 없다"
    assert build_access_policy(branch, None)["menu_keys"] == [], "묶음 없으면 0개(클린 모델)"
    # 이 확장이 본사 메뉴까지 새게 하면 안 된다.
    assert not ({"bonus", "cardVouchers", "reconcile"} & available_menu_keys(branch))
    # 코드 기본값이 아니라 **묶음**이 준다 — 붙이면 그대로 8종이 켜진다.
    grant = RoleGrant(
        role_id=1, name="지사 재무담당",
        menu_keys=frozenset(BRANCH_FINANCE_MENU_KEYS),
        view_all_offices=None, view_other_users=None, source="user",
    )
    granted = build_access_policy(branch, None, grant=grant)
    assert set(granted["menu_keys"]) == set(BRANCH_FINANCE_MENU_KEYS)

def test_묶음_없으면_지사_집행부도_메뉴_0개다():
    # 클린 모델: 지사 집행부의 코드 기본값(감정서·입금·미수금 3종)도 걷어냈다.
    # 실제로는 소속 '기본 열람' 묶음으로 그 3종을 받는다 — 코드가 아니라 묶음이 정한다.
    policy = build_access_policy(
        identity(office_id="11", chrg_biz="집행부", appraisal_fl="1")
    )

    assert policy["menu_keys"] == []


def test_branch_department_uses_chrg_biz_without_changing_appraiser_status():
    user = identity(office_id="11", chrg_biz="평가부", appraisal_fl="0")
    policy = build_access_policy(user)

    assert user.department_name == "평가부"
    assert policy["is_appraiser"] is True
    assert policy["menu_keys"] == []                 # 클린 모델: 코드 기본값 없음


def test_missing_branch_department_is_visible_but_role_still_uses_appraisal_flag():
    user = identity(office_id="11", chrg_biz=None, appraisal_fl="0")
    policy = build_access_policy(user)

    assert user.department_name == "부서 미입력"
    assert policy["is_appraiser"] is True


def test_지사_일반직원은_묶음_없으면_메뉴_0개다():
    """레거시 허용명단 폴백(apply_legacy_branch_finance)은 2026-08-18 걷어냈다 — 실측
    으로 거기 걸리는 사람이 0명이었다. 지사 일반직원은 이제 묶음 없이는 메뉴 0개
    (=로그인 거절)다. 재무 권한은 오직 묶음으로만 준다(클린 모델)."""
    user = identity(office_id="11", appraisal_fl="1")
    policy = build_access_policy(user)

    assert policy["view_all_offices"] is False
    assert policy["menu_keys"] == []


def test_json_overrides_expand_hq_appraiser_without_changing_other_defaults():
    user = identity(office_id="10", seat_dept="ju")
    row = AccessPolicy(
        usr_seq=user.usr_seq,
        usr_id=user.usr_id,
        view_all_offices_override="Y",
        view_other_users_override="N",
        menu_overrides_json=json.dumps({"dataQuality": True}),
        active="Y",
    )

    policy = build_access_policy(user, row)

    assert policy["view_all_offices"] is True
    assert policy["view_other_users"] is False
    assert policy["menu_permissions"]["dataQuality"] is True


def test_branch_can_never_receive_all_office_scope():
    user = identity(office_id="11", appraisal_fl="0")
    row = AccessPolicy(
        usr_seq=user.usr_seq,
        usr_id=user.usr_id,
        view_all_offices_override="Y",
        active="Y",
    )

    assert build_access_policy(user, row)["view_all_offices"] is False


def test_permission_management_is_default_for_hq_finance_and_individually_grantable():
    finance = identity(office_id="10", seat_dept="jae")
    appraiser = identity(office_id="10", seat_dept="ju")
    branch = identity(office_id="11", appraisal_fl="0")
    override = json.dumps({"permissionManage": True})

    finance_policy = build_access_policy(
        finance,
        AccessPolicy(
            usr_seq=finance.usr_seq,
            usr_id=finance.usr_id,
            menu_overrides_json=override,
            active="Y",
        ),
    )
    appraiser_policy = build_access_policy(
        appraiser,
        AccessPolicy(
            usr_seq=appraiser.usr_seq,
            usr_id=appraiser.usr_id,
            menu_overrides_json=override,
            active="Y",
        ),
    )
    branch_policy = build_access_policy(
        branch,
        AccessPolicy(
            usr_seq=branch.usr_seq,
            usr_id=branch.usr_id,
            menu_overrides_json=override,
            active="Y",
        ),
    )

    assert finance_policy["menu_permissions"]["permissionManage"] is True
    assert appraiser_policy["menu_permissions"]["permissionManage"] is True
    assert branch_policy["menu_permissions"]["permissionManage"] is True


def test_hq_finance_can_individually_disable_permission_management():
    finance = identity(office_id="10", seat_dept="jae")
    policy = build_access_policy(
        finance,
        AccessPolicy(
            usr_seq=finance.usr_seq,
            usr_id=finance.usr_id,
            menu_overrides_json=json.dumps({"permissionManage": False}),
            active="Y",
        ),
    )

    assert policy["menu_permissions"]["permissionManage"] is False


def test_office_scope_rejects_cross_branch_and_all():
    access = {
        "office_id": "11",
        "view_all_offices": False,
        "offices": [{"office_code": "11"}],
    }

    assert resolve_office_scope(access, "11") == "11"
    with pytest.raises(HTTPException):
        resolve_office_scope(access, "10")
    with pytest.raises(HTTPException):
        resolve_office_scope(access, "all")


def test_self_scope_uses_login_employee_and_sql_checks_manager_or_charge():
    access = {"emp_name": "김평가", "view_other_users": False}
    assert scoped_employee_name(access) == "김평가"

    where, params = _where_clause(
        None, None, None, None, None, None, None, None, "11",
        scope_person=scoped_employee_name(access),
    )
    assert "Manager LIKE :scope_person OR Charge LIKE :scope_person" in where
    assert params["scope_person"] == "%김평가%"
    # 남을 볼 수 있으면 이름 필터가 사라진다(전체) — 양방향을 못 박는다.
    assert scoped_employee_name({"emp_name": "김평가", "view_other_users": True}) is None


def test_평범한_직원은_기본으로_자기_데이터만_본다():
    """2026-08-17 스코프 토글을 배정 화면에서 걷어내면서, 이제 대다수가 **기본값**에
    기댄다. 그 기본값은 fail-closed 여야 한다 — 운영부서·지사재무가 아니면 남의
    실적을 못 본다. 이 성질이 뒤집히면 토글 없는 화면이 조용히 전원에게 남의
    데이터를 연다. 구멍이 나면 안 되는 바로 그 자리다."""
    # 본사 비운영 직원(주주평가사). 본사 부서는 seat_dept 코드로 정해진다.
    hq_plain = build_access_policy(identity(office_id="10", seat_dept="ju"))
    assert hq_plain["view_other_users"] is False, "본사 비운영이 남을 본다"
    assert hq_plain["view_all_offices"] is False

    # 지사 비재무 일반 직원
    branch_plain = build_access_policy(
        identity(office_id="11", chrg_biz="업무팀", appraisal_fl="1"))
    assert branch_plain["view_other_users"] is False, "지사 비재무가 남을 본다"
    assert branch_plain["view_all_offices"] is False, "지사가 전지사를 본다"

    # 클린 모델(2026-08-18): 재무팀도 묶음 없이는 남을 못 본다 — 스코프는 코드가
    # 아니라 묶음이 정한다. fail-closed 가 더 철저해졌다(운영부서 특례도 제거).
    ops = build_access_policy(identity(office_id="10", seat_dept="jae"))
    assert ops["view_other_users"] is False and ops["view_all_offices"] is False


def test_묶음은_부여가능_범위를_넘지_못한다():
    """묶음에 실수로 넣은 권한이 그 사람에게 열리면 안 된다 (2026-08-16).

    이 성질이 시드 SQL 의 안전장치다 — 부서 57개에 한꺼번에 묶음을 붙일 때,
    묶음 하나만 잘못 적어도 269명에게 잘못된 권한이 퍼지기 때문이다.
    교집합이 걸려 있으면 그런 사고가 '안 열림' 으로 끝난다.
    """
    from app.services.access_policy import (
        PolicyIdentity, RoleGrant, available_menu_keys, build_access_policy,
    )

    branch = PolicyIdentity(
        usr_seq=1, usr_id="x", emp_name="지사업무", office_id="21",
        department_code=None, department_name="업무팀",
        employee_type="일반직원", is_appraiser=False)
    # 지사 일반직원에게는 bonus·mySales 가 available 이 아니다.
    assert "bonus" not in available_menu_keys(branch)

    grant = RoleGrant(
        role_id=1, name="넉넉한묶음",
        menu_keys=frozenset({"appraisals", "payments", "bonus", "mySales"}),
        view_all_offices=None, view_other_users=None, source="dept")
    policy = build_access_policy(branch, None, grant=grant)
    on = {k for k, v in policy["menu_permissions"].items() if v}
    assert "bonus" not in on and "mySales" not in on
    # 줄 수 있는 것은 그대로 열린다 — 막는 게 목적이 아니다.
    assert {"appraisals", "payments"} <= on


def test_시드가_주는_3종은_어디서든_부여가능하다():
    """감정서·입금·미수금 3종은 본사·지사 모두 available 안에 있어야 한다.

    seed(20260816_seed_general_role.sql)가 이걸 전제로 부서 57개에 한 번에
    붙인다. 하나라도 available 밖이면 그 부서는 열린 줄 알았는데 안 열린다.
    """
    from app.services.access_policy import (
        PolicyIdentity, available_menu_keys,
    )

    seed_keys = {"appraisals", "payments", "receivables"}
    for office_id, dept in (("10", "업무1팀"), ("21", "업무팀"), ("13", "부서 미입력")):
        identity = PolicyIdentity(
            usr_seq=1, usr_id="x", emp_name="아무개", office_id=office_id,
            department_code=None, department_name=dept,
            employee_type="일반직원", is_appraiser=False)
        assert seed_keys <= available_menu_keys(identity), (office_id, dept)
