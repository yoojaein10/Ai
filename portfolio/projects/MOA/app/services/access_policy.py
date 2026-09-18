"""MOA 메뉴·지사·직원 데이터 범위의 단일 정책 원본."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.access_policy import AccessPolicy
from app.models.access_role import AccessDeptRole, AccessRole, AccessUserRole

HEAD_OFFICE_ID = "10"

MENU_KEYS = (
    "appraisals",
    "workReport",
    "payments",
    "receivables",
    "salesInput",
    "salesStats",
    "bonus",
    "allocation",
    "dataQuality",
    "reconcile",
    "receivableReconcile",
    "advanceReconcile",
    "permissionManage",
    "paymentSms",
    "cardVouchers",
    "feeBasis",
    "mySales",
    # 상류(main)가 2026-08 에 추가한 화면. 통장 입금에 감정서를 붙이는 대사라
    # 화면 이름은 '감정서 조회'(→ '입금 대사')이고 주소는 /desktop/gamjun-chat 이다.
    "depositMatch",
    # 계정별원장 (2026-08-21) — 지사 계정(141 계열) 원장을 뽑아 지사에 메일로 보낸다.
    # 지금은 팩스로 출력해 보내던 일이다. 본사 전용.
    "accountLedger",
    # 일계표 대사 (2026-08-26) — 사이버브랜치 입·출금과 아마란스 보통예금 전표를 계좌·일자로
    # 대사한다. 어떤 묶음에도 넣지 않고 개인 예외로만 켠다(이일우·장세희).
    "bankReconcile",
    # 계산서 일괄발급 (2026-08-27) — 입금 건을 일반·대주단·국민약식으로 골라 팝빌 일괄 발행. 본사 재무·집행부.
    "taxBulk",
    # 신한은행 발송기한 관리 (2026-09-02) — MOA 메뉴에 없는 독립 화면(/desktop/shinhan-delay).
    # 어떤 묶음에도 넣지 않고 개인 예외로만 켠다(이일우·유재인·원동하·엄기원).
    "shinhanDelay",
    # 출장비 (2026-09-10) — APWorks 델파이 출장비프로그램 이식. 본사 전 직원(작성자)·결재자 명단은 APWorks 테이블.
    "travelExpense",
)

# 본·지사 모두에게 available한 공용 메뉴(office 스코프로 자기 지사만).
# 개인 거래 메뉴(appraisals/payments/receivables/allocation)는 scope_person으로 자기 것만 —
# view_other_users=OFF면 본인 유치/조사 건만 본다.
# 단 workReport/salesStats(집계·통계)는 개인 귀속이 아니라 재무·관리자용이므로 person-scope를
# 걸지 않는다(2026-08-19 확정) — office 스코프(자기 지사)만 적용. 재발 방지: 여기에 scope_person을
# 다시 붙이지 말 것. 기본 ON은 재무·관리자(본사 재무·집행부, 지사 재무담당자)만 — default_menu_keys에서 갈린다.
SHARED_MENU_KEYS = {
    "appraisals",
    "payments",
    "receivables",
    "allocation",
    "workReport",
    "salesStats",
}
# 지사 재무·관리자용. workReport(업무실적보고)·salesStats(기간별매출실적)는 개인 거래가 아니라
# 지사 집계/통계라 평가사에게는 감추고 재무·관리자만 본다(지사는 resolve_office_scope로 자기 지사만).
BRANCH_FINANCE_MENU_KEYS = {
    "appraisals",
    "payments",
    "receivables",
    "workReport",
    "salesStats",
    "allocation",
    # 입금발송내역: 본·지사 모두 다루는 화면이라 지사 재무담당자도 본다.
    # 단 조회 범위는 resolve_office_scope 로 자기 지사에 강제된다.
    "paymentSms",
    # 보수기준 점검 — 지사 재무도 자기 지사 건은 본다 (2026-08-07 확정).
    # 화면·API 가 로그인 지사로 범위를 강제하므로 남의 지사는 못 본다.
    "feeBasis",
}
# 지사 재무권한 담당자(부서가 아니라 지정된 개인). 재무팀이 없는 지사도 있어 usr_seq로 지정한다.
# 이 사람들은 BRANCH_FINANCE_MENU_KEYS(감정서·입금·미수금·기간별매출실적·업무실적보고·배분수금진행,
# BRANCH_FINANCE_HOLDERS(지사 재무담당 usr_seq 18개)는 2026-08-17 에 걷어냈다.
# 명단은 이제 a10_access_user_role 의 '지사 재무담당' 묶음이 들고 있고,
# 붙이고 떼는 일은 권한 관리 화면에서 한다 — 담당자 교체에 배포가 필요 없다.
# 최초 18명은 scripts/sql/20260813_seed_access_role.sql 에 기록돼 있다.
# 본사 전 직원 기본 노출(지사 미노출) 메뉴. 소스상 본사 데이터만 조회한다.
#  - receivable/advanceReconcile(반제리스트): 본사 재무 관리 화면(banje.py 독스트링).
#    (매출입력·상여와 달리 아직 재무·집행부로 좁히지 않고 본사 전체 노출을 유지한다.)
HEAD_OFFICE_MENU_KEYS = {
    "receivableReconcile", "advanceReconcile",
    # 출장비: 본사 조사자 54명이 적고 결재자 10명이 결재한다 — 본사 전 직원 기본 노출.
    "travelExpense",
}
HEAD_OFFICE_PRIVILEGED_MENU_KEYS = {"dataQuality", "reconcile", "accountLedger", "bankReconcile", "shinhanDelay"}
# 본사 재무·집행부 전용. 본사 평가사·일반직원에게는 부여하지 않는다.
#  - salesInput(매출입력/배분)·bonus(상여): 본사 감정서(01-%)만 다루는 입력 화면 → 재무·집행부만.
#  - workReport/salesStats(업무실적보고·기간별매출실적): 집계·통계.
#    지사 재무에게는 BRANCH_FINANCE_MENU_KEYS로 별도 부여(자기 지사만).
#  - paymentSms(입금발송내역): 본·지사 데이터를 다루지만 발송 처리는 본사만.
#    지사 재무담당자는 BRANCH_FINANCE_MENU_KEYS 로 따로 받는다(자기 지사만).
#  - cardVouchers(카드전표): 카드 명세서로 전표를 만드는 본사 재무 전용 화면.
#  - feeBasis(보수기준 점검): 청구서 보수기준과 감정서 내용을 대조한다.
#    종전에는 office_id=='10' 만 봐서 본사 227명 전원이 열 수 있었다.
#    2026-08-07 부터 지사 재무도 자기 지사 건을 본다(BRANCH_FINANCE_MENU_KEYS).
#  - depositMatch(입금 대사): 통장 입금에 감정서를 붙이는 본사 재무 화면.
#    라우터도 전체조회 권한(can_view_all)으로 막고 있다 — 같은 대상이다.
HEAD_OFFICE_FINANCE_MENU_KEYS = {
    "workReport", "salesStats", "salesInput", "bonus",
    "paymentSms", "cardVouchers", "feeBasis", "depositMatch",
    # 본사 재무는 평가사 실적을 확인할 수 있어야 한다(usr_seq 지정 조회).
    "mySales",
    # 계산서 일괄발급 — 실제 국세청 전송이라 카드전표와 같은 본사 재무·집행부 묶음.
    "taxBulk",
}
# 코드 기본값(default_menu_keys)·레거시(apply_legacy_branch_finance)는 2026-08-18
# 걷어냈다("심플하지만 정확한" 클린 모델 — 권한은 명시적 묶음에서만). 그때 이 함수들만
# 쓰던 상수(HEAD_OFFICE_EXECUTIVE_MENU_KEYS·APPRAISER_DEFAULT_MENU_KEYS)도 함께 지웠다.

HEAD_OFFICE_DEPARTMENTS = {
    "yj": "예비주주평가사",
    "ju": "주주평가사",
    "so": "소속평가사",
    "su": "수습평가사",
    "sim": "심사부",
    "jip": "집행부",
    "gam": "감사부",
    "p1": "평가1부",
    "pg1": "평가1부",
    "p2": "평가2부",
    "pg2": "평가2부",
    "j2": "전산정보팀",
    "jun": "전산정보팀",
    "ch": "총무팀",
    "pu1": "업무1팀",
    "pu2": "업무2팀",
    "mp": "명예평가사",
    "jae": "재무팀",
    "gy": "계약직",
}
HEAD_OFFICE_APPRAISER_DEPARTMENTS = {
    "예비주주평가사",
    "주주평가사",
    "소속평가사",
    "수습평가사",
    "명예평가사",
    "심사부",
    "감사부",
}
OPERATIONS_DEPARTMENTS = {"집행부", "재무팀", "전산정보팀"}

# 본사에서 메뉴 전체를 기본으로 받는 부서.
#  - 재무팀: 이 시스템의 주 사용자. 19종 전부가 업무 화면이다.
#  - 전산정보팀: 이 시스템을 만들고 운영하는 팀(2026-08-08 확정). 장애를 보려면
#    화면이 열려 있어야 하고, 권한관리 화면 자체도 이 팀이 운영한다.
HEAD_OFFICE_FULL_ACCESS_DEPARTMENTS = {"재무팀", "전산정보팀"}


@dataclass(frozen=True)
class PolicyIdentity:
    usr_seq: int
    usr_id: str
    emp_name: str
    office_id: str
    department_code: str | None
    department_name: str
    employee_type: str
    is_appraiser: bool


def identity_from_row(row: Mapping[str, Any]) -> PolicyIdentity:
    office_id = str(row["office_id"]).strip()
    seat_code = str(row.get("seat_dept") or "").strip().lower() or None
    branch_department = str(row.get("chrg_biz") or "").strip() or "부서 미입력"
    department_name = (
        HEAD_OFFICE_DEPARTMENTS.get(seat_code or "", "부서 미지정")
        if office_id == HEAD_OFFICE_ID
        else branch_department
    )
    is_operations = office_id == HEAD_OFFICE_ID and department_name in OPERATIONS_DEPARTMENTS
    is_appraiser = (
        not is_operations
        and (
            (office_id == HEAD_OFFICE_ID and department_name in HEAD_OFFICE_APPRAISER_DEPARTMENTS)
            or (
                office_id != HEAD_OFFICE_ID
                and str(row.get("appraisal_fl") or "").strip() == "0"
            )
        )
    )
    employee_type = (
        department_name
        if office_id == HEAD_OFFICE_ID
        else ("평가사" if is_appraiser else "일반직원")
    )
    return PolicyIdentity(
        usr_seq=int(row["usr_seq"]),
        usr_id=str(row["usr_id"]).strip(),
        emp_name=str(row["emp_name"]).strip(),
        office_id=office_id,
        department_code=seat_code,
        department_name=department_name,
        employee_type=employee_type,
        is_appraiser=is_appraiser,
    )


def _yn(value: str | None) -> bool | None:
    if value == "Y":
        return True
    if value == "N":
        return False
    return None


def _menu_overrides(raw: str | None) -> dict[str, bool]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(key): value
        for key, value in data.items()
        if key in MENU_KEYS and isinstance(value, bool)
    }


def available_menu_keys(identity: PolicyIdentity) -> set[str]:
    # 지사에게 무엇이 열리나 — 2026-08-17 메뉴 19개 전수조사로 확정한 목록이다.
    #   · SHARED 6종: 감정서·입금·미수금·배분수금·기간별매출실적·업무실적보고
    #     (전부 SQL 에 지사 축이 있고 실측으로 지사 자료가 나온다)
    #   · 개인 지정된 지사 재무담당 18명에게 BRANCH_FINANCE 8종(feeBasis·paymentSms 포함)
    #   · permissionManage — 지사 관리자는 자기 지사 사람만 보고 고친다
    # 나머지 8종은 **지사에 열지 않는다**(본사 전용):
    #   salesInput·bonus·cardVouchers·receivableReconcile·advanceReconcile·
    #   dataQuality·reconcile·depositMatch — tests/test_branch_scope.py 가 지킨다.
    # 그중 반제 2종·dataQuality·reconcile 은 '데이터가 본사뿐'이어서가 아니라
    # **업무 소관이 본사 재무**라서다(SQL 은 지사 파라미터화돼 있다). 훗날 열자는
    # 요구가 오면 서비스는 손댈 게 없고 화면 게이트만 풀면 된다.
    # 실제 조직 조회 범위는 API에서 로그인 사용자의 지사로 다시 강제한다.
    return office_available_menus(identity.office_id)


def office_available_menus(office_id: str) -> set[str]:
    """이 소속에서 **부여 가능한** 메뉴(상한) — identity 없이 소속만으로. 본사는 전 메뉴,
    지사는 지사 노출분 9종(SHARED 6 + 권한관리 + 지사재무 2). available_menu_keys 가
    이걸 부른다. **묶음 편집기가 소속에 맞는 토글만 보이게** 할 때도 쓴다(2026-08-19)."""
    result = set(SHARED_MENU_KEYS) | {"permissionManage"}
    if str(office_id) != HEAD_OFFICE_ID:
        # 지사 재무 2종(paymentSms·feeBasis)은 지사 전원에게 토글을 연다(자기 지사만).
        result.update(BRANCH_FINANCE_MENU_KEYS)
    else:
        # 본사는 전 직원에게 모든 본사 메뉴를 토글 노출(기본 on/off 는 묶음이 정한다).
        result.update(HEAD_OFFICE_MENU_KEYS)
        result.update(HEAD_OFFICE_PRIVILEGED_MENU_KEYS)
        result.update(HEAD_OFFICE_FINANCE_MENU_KEYS)
    return result


@dataclass(frozen=True)
class RoleGrant:
    """부서 또는 개인에 붙은 권한 묶음이 정하는 것.

    menu_keys 는 **대체**다 — 아래 층(코드 기본값)을 더하는 게 아니라 갈아치운다.
    두 플래그는 None 이면 '이 묶음은 정하지 않는다'라 아래 층이 그대로 산다.
    """

    role_id: int
    name: str
    menu_keys: frozenset[str]
    view_all_offices: bool | None
    view_other_users: bool | None
    source: str          # 'dept' | 'user'


def build_access_policy(
    identity: PolicyIdentity,
    row: AccessPolicy | None = None,
    *,
    grant: "RoleGrant | None" = None,
) -> dict[str, Any]:
    # is_operations·is_branch_finance 는 화면 표시(라벨)용으로만 계산한다. 권한 기본값에는
    # 더 이상 쓰지 않는다 — 2026-08-18 사용자 요청으로 코드 기본값(부서 heuristic)을
    # 걷어냈다("심플하지만 정확한" 클린 모델). 권한은 **명시적 묶음(부서·개인)과 개인
    # 예외에서만** 온다. 묶음 없는 사람은 메뉴 0개(=로그인 거절)이고, 새 입사자도 지정
    # 전엔 0이다(코드가 부서 이름으로 추정해 주지 않는다). 보안 상한(available_menu_keys)
    # 과 지사 전지사조회 강제 차단은 그대로 유지한다.
    is_operations = (
        identity.office_id == HEAD_OFFICE_ID
        and identity.department_name in OPERATIONS_DEPARTMENTS
    )
    is_branch_finance = (
        identity.office_id != HEAD_OFFICE_ID
        and "재무" in identity.department_name
    )
    menu_keys: set[str] = set()
    view_all_default = False
    view_others_default = False

    # 권한 묶음(부서 또는 개인)이 정하는 값. 개인 묶음이 부서 묶음을 이기는 것은
    # load_access_policy 에서 고른다. 두 플래그가 None 이면 이 묶음은 정하지 않는다.
    if grant is not None:
        menu_keys = set(grant.menu_keys)
        if grant.view_all_offices is not None:
            view_all_default = grant.view_all_offices
        if grant.view_other_users is not None:
            view_others_default = grant.view_other_users

    if row and row.active == "Y":
        view_all_override = _yn(row.view_all_offices_override)
        view_others_override = _yn(row.view_other_users_override)
        if view_all_override is not None:
            view_all_default = view_all_override
        if view_others_override is not None:
            view_others_default = view_others_override
        for key, allowed in _menu_overrides(row.menu_overrides_json).items():
            if allowed:
                menu_keys.add(key)
            else:
                menu_keys.discard(key)

    # 지사는 어떤 예외가 있어도 다른 지사를 볼 수 없다.
    view_all = identity.office_id == HEAD_OFFICE_ID and view_all_default
    menu_keys.intersection_update(available_menu_keys(identity))
    return {
        "view_all_offices": view_all,
        "view_other_users": bool(view_others_default),
        "menu_permissions": {key: key in menu_keys for key in MENU_KEYS},
        "menu_keys": [key for key in MENU_KEYS if key in menu_keys],
        "is_appraiser": identity.is_appraiser,
        "is_operations": is_operations,
        "is_branch_finance": is_branch_finance,
        "policy_source": (
            "override" if row and row.active == "Y"
            else f"role:{grant.source}" if grant is not None
            else "default"
        ),
        # 화면이 '이 사람 권한이 어디서 왔나'를 설명할 수 있게 붙인다.
        "role": (
            {"role_id": grant.role_id, "name": grant.name, "source": grant.source}
            if grant is not None else None
        ),
    }


def _role_of(db: Session, role_id: int, source: str) -> "RoleGrant | None":
    row = db.get(AccessRole, role_id)
    if row is None or row.active != "Y":
        return None
    try:
        keys = json.loads(row.menu_keys_json) if row.menu_keys_json else []
    except (TypeError, ValueError):
        keys = []
    return RoleGrant(
        role_id=row.role_id,
        name=row.name,
        menu_keys=frozenset(str(k) for k in keys if k in MENU_KEYS),
        view_all_offices=_yn(row.view_all_offices),
        view_other_users=_yn(row.view_other_users),
        source=source,
    )


def resolve_role(db: Session, identity: PolicyIdentity) -> "RoleGrant | None":
    """이 사람에게 붙은 권한 묶음. **개인이 부서를 이긴다** (2026-08-13 확정).

    표가 아직 없는 환경(운영 반영 전)에서는 조용히 None 을 돌려준다 — 그러면
    지금까지처럼 코드 기본값으로 동작하므로 아무것도 깨지지 않는다.
    """
    try:
        mine = db.get(AccessUserRole, identity.usr_seq)
        if mine is not None and mine.active == "Y":
            grant = _role_of(db, mine.role_id, "user")
            if grant is not None:
                return grant
        dept = db.get(
            AccessDeptRole, (identity.office_id, identity.department_name)
        )
        if dept is not None and dept.active == "Y":
            return _role_of(db, dept.role_id, "dept")
    except SQLAlchemyError:
        db.rollback()      # 표 미생성 등 — 코드 기본값으로 떨어진다
    return None


def load_access_policy(db: Session, identity: PolicyIdentity) -> dict[str, Any]:
    """유효 권한 = 개인 예외(row) + 묶음(grant). 코드 기본값·레거시는 없다(클린 모델).

    2026-08-18 사용자 요청으로 레거시(UserPermission 전지사 폴백)를 걷어냈다 — 실측
    으로 여기 걸리는 사람이 0명이었다. 권한은 이제 명시적 묶음·개인 예외에서만 온다.
    """
    row: AccessPolicy | None = None
    try:
        row = db.get(AccessPolicy, identity.usr_seq)
    except SQLAlchemyError:
        db.rollback()
    grant = resolve_role(db, identity)
    return build_access_policy(identity, row, grant=grant)


def encode_menu_overrides(overrides: Mapping[str, bool] | None) -> str | None:
    if not overrides:
        return None
    sanitized = {
        key: bool(value)
        for key, value in overrides.items()
        if key in MENU_KEYS and isinstance(value, bool)
    }
    return json.dumps(sanitized, ensure_ascii=False, sort_keys=True) if sanitized else None
