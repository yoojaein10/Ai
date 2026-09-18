"""MOA 조직도와 사용자별 권한 관리.

기존 a10_user_permission API는 호환용으로 유지하고, 신규 메뉴·지사·직원 범위는
a10_access_policy의 한 사람 한 행 구조를 사용한다.
"""

from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.access_policy import AccessPolicy
from app.models.user_permission import UserPermission
from app.services.access_policy import (
    resolve_role,
    HEAD_OFFICE_APPRAISER_DEPARTMENTS,
    HEAD_OFFICE_ID,
    MENU_KEYS,
    available_menu_keys,
    build_access_policy,
    encode_menu_overrides,
    identity_from_row,
)
from app.services.access_policy import _menu_overrides  # noqa: PLC2701
from app.services.access_history import record as record_change
from app.services.office_lookup import get_office


# 동일 이름 중 HWP 재직자와 일치하지 않는 것으로 확인된 계정.
PERMISSION_PREVIEW_EXCLUDED_USER_IDS = {"JSKB010", "JSDK090"}


def _source_database() -> str:
    database = get_settings().mssql_source_db
    if not database.replace("_", "").isalnum():
        raise RuntimeError("MSSQL_SOURCE_DB 이름이 올바르지 않습니다.")
    return database


def search_employees(db: Session, keyword: str, limit: int = 20) -> "list[dict[str, Any]]":
    """권한 부여 대상 재직자 검색 (이름 부분 일치). USR_ID가 권한 테이블의 키다."""
    database = _source_database()
    rows = db.execute(
        text(
            f"""
            SELECT TOP {int(limit)}
                RTRIM(USR_ID) AS usr_id, RTRIM(EMP) AS emp_name, RTRIM(OFFICE_ID) AS office_id
            FROM [{database}].dbo.TMWCMN_USR_BAC_INFO
            WHERE USE_YN = 'Y' AND RTRM_FL = '0'
              AND EMP LIKE CAST(:pattern AS varchar(60))
            ORDER BY EMP
            """
        ),
        {"pattern": f"%{keyword.strip()}%"},
    ).mappings().all()
    return [
        {**dict(row), "office_name": _office_name(db, row["office_id"])}
        for row in rows
    ]


def organization_preview(
    db: Session,
    visible_office_id: str | None = None,
) -> "dict[str, Any]":
    """권한관리 시안용 실제 조직도.

    본사는 Seat_userinfo 한 테이블만 조직 원본으로 사용한다. 지사는 APWorks
    재직 계정을 원본으로 사용하고 TMWCMN_EMPT_DTL.CHRG_BIZ로 부서를 표시한다.
    지사 직원은 CHRG_BIZ가 입력된 계정만 표시하며 매 요청마다 원본 DB를 조회한다.
    APPRAISAL_FL=0은 평가사 여부 판정에만 사용한다.
    권한 저장이나 감사로그 기록은 하지 않는다.
    """
    database = _source_database()
    office_rows = db.execute(
        text(
            f"""
            SELECT RTRIM(OfficeID) AS office_id, RTRIM(Name) AS office_name, SEQ
            FROM [{database}].dbo.apw_office
            WHERE Active = 'Y'
            ORDER BY SEQ
            """
        )
    ).mappings().all()
    head_office_rows = db.execute(
        text(
            f"""
            SELECT
                u.USR_SEQ AS usr_seq,
                RTRIM(s.APWID) AS usr_id,
                RTRIM(s.Uname) AS emp_name,
                RTRIM(s.Ugrade) AS position_name,
                LOWER(RTRIM(s.Dept_Nm)) AS seat_dept
            FROM [{database}].dbo.Seat_userinfo s
            OUTER APPLY (
                SELECT TOP 1 u.USR_SEQ
                FROM [{database}].dbo.TMWCMN_USR_BAC_INFO u
                WHERE RTRIM(u.USR_ID) = RTRIM(s.APWID)
                  AND RTRIM(u.OFFICE_ID) = '10'
                  AND u.USE_YN = 'Y' AND u.RTRM_FL = '0'
                ORDER BY u.USR_SEQ DESC
            ) u
            WHERE NULLIF(RTRIM(s.APWID), '') IS NOT NULL
              AND NULLIF(RTRIM(s.Uname), '') IS NOT NULL
              AND NULLIF(RTRIM(s.Dept_Nm), '') IS NOT NULL
              -- 퇴사자(RTRM_FL='1') 좌석은 조직도에서 뺀다. 본사는 좌석(Seat_userinfo)이
              -- 뼈대라 활성계정 연결이 실패(u.USR_SEQ IS NULL)해도 좌석 행이 남는데, 그 사람이
              -- 퇴사로 등록돼 있으면 유령으로 뜬다(예: 고정은 USR_ID 4467). 재입사로 활성
              -- 계정이 있으면 u.USR_SEQ 가 채워지므로 이 조건에 안 걸린다.
              AND NOT (
                  u.USR_SEQ IS NULL
                  AND EXISTS (
                      SELECT 1 FROM [{database}].dbo.TMWCMN_USR_BAC_INFO r
                      WHERE RTRIM(r.USR_ID) = RTRIM(s.APWID)
                        AND RTRIM(r.RTRM_FL) = '1'
                  )
              )
            ORDER BY s.Uname, s.APWID
            """
        )
    ).mappings().all()
    branch_employee_rows = db.execute(
        text(
            f"""
            SELECT
                u.USR_SEQ AS usr_seq,
                RTRIM(u.USR_ID) AS usr_id,
                RTRIM(u.EMP) AS emp_name,
                RTRIM(u.OFFICE_ID) AS office_id,
                RTRIM(p.PSTN) AS position_name,
                RTRIM(u.APPRAISAL_FL) AS appraisal_fl,
                NULLIF(LTRIM(RTRIM(d.CHRG_BIZ)), '') AS chrg_biz
            FROM [{database}].dbo.TMWCMN_USR_BAC_INFO u
            INNER JOIN [{database}].dbo.apw_office o
                ON RTRIM(o.OfficeID) = RTRIM(u.OFFICE_ID)
               AND o.Active = 'Y'
            LEFT JOIN [{database}].dbo.TMWCMN_EMPT_DTL d
                ON d.USR_SEQ = u.USR_SEQ
            LEFT JOIN [{database}].dbo.TMWCMN_PSTN p
                ON p.PSTN_SEQ = u.PSTN_SEQ
            WHERE u.USE_YN = 'Y'
              AND u.RTRM_FL = '0'
              AND RTRIM(u.OFFICE_ID) <> '10'
              AND NULLIF(LTRIM(RTRIM(d.CHRG_BIZ)), '') IS NOT NULL
              AND LTRIM(RTRIM(u.EMP)) NOT LIKE '공(%'
            ORDER BY o.SEQ, u.EMP, u.USR_SEQ
            """
        )
    ).mappings().all()

    head_office_seat_departments = {
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
        # 현재 Seat_userinfo에 존재하는 추가 본사 구분.
        "mp": "명예평가사",
        "jae": "재무팀",
        "gy": "계약직",
    }
    department_order = {
        "집행부": 10,
        "감사부": 20,
        "심사부": 30,
        "주주평가사": 40,
        "명예평가사": 50,
        "예비주주평가사": 60,
        "소속평가사": 70,
        "수습평가사": 80,
        "평가1부": 90,
        "평가2부": 100,
        "평가1,2부": 105,
        "업무1팀": 110,
        "업무2팀": 120,
        "총무팀": 140,
        "재무팀": 150,
        "전산정보팀": 160,
        "계약직": 170,
        "평가사": 920,
        "일반직원": 930,
        "부서 미입력": 9999,
    }
    offices: "dict[str, dict[str, Any]]" = {
        row["office_id"]: {
            "id": row["office_id"],
            "name": row["office_name"],
            "sort_order": row["SEQ"],
            "_departments": {},
        }
        for row in office_rows
        if visible_office_id is None or row["office_id"] == visible_office_id
    }

    head_office = offices.get("10")
    if head_office is not None:
        for row in head_office_rows:
            department_name = head_office_seat_departments.get(row["seat_dept"])
            if not department_name:
                continue
            department = head_office["_departments"].setdefault(
                department_name,
                {
                    "name": department_name,
                    "category": department_name,
                    "employees": [],
                },
            )
            department["employees"].append(
                {
                    "id": str(row["usr_seq"] or row["usr_id"]),
                    "usr_seq": row["usr_seq"],
                    "usr_id": row["usr_id"],
                    "account_linked": row["usr_seq"] is not None,
                    "name": row["emp_name"],
                    "title": row["position_name"] or department_name,
                    "viewAll": True,
                    "is_appraiser": department_name in HEAD_OFFICE_APPRAISER_DEPARTMENTS,
                }
            )

    for row in branch_employee_rows:
        if row["usr_id"] in PERMISSION_PREVIEW_EXCLUDED_USER_IDS:
            continue
        if not row["chrg_biz"]:
            continue
        office = offices.get(row["office_id"])
        if office is None:
            continue
        department_name = row["chrg_biz"]
        category = department_name
        is_appraiser = row["appraisal_fl"] == "0"
        department = office["_departments"].setdefault(
            department_name,
            {"name": department_name, "category": category, "employees": []},
        )
        department["employees"].append(
            {
                "id": str(row["usr_seq"]),
                "usr_seq": row["usr_seq"],
                "usr_id": row["usr_id"],
                "account_linked": True,
                "name": row["emp_name"],
                "title": "",
                "viewAll": False,
                "is_appraiser": is_appraiser,
            }
        )

    items: "list[dict[str, Any]]" = []
    employee_count = 0
    missing_department_count = 0
    for office in offices.values():
        departments = sorted(
            office.pop("_departments").values(),
            key=lambda item: (department_order.get(item["name"], 999), item["name"]),
        )
        for department in departments:
            department["employees"].sort(key=lambda item: (item["name"], item["usr_seq"]))
            employee_count += len(department["employees"])
        office["departments"] = departments
        office["employee_count"] = sum(len(item["employees"]) for item in departments)
        office["missing_department_count"] = sum(
            len(item["employees"])
            for item in departments
            if item["name"] == "부서 미입력"
        )
        missing_department_count += office["missing_department_count"]
        items.append(office)

    return {
        "offices": items,
        "office_count": len(items),
        "employee_count": employee_count,
        "missing_department_count": missing_department_count,
    }


def _office_name(db: Session, office_id: str) -> str:
    office = get_office(db, office_id)
    return office.office_name if office else office_id


def list_offices(db: Session) -> "list[dict[str, str]]":
    """소속 목록(본사·지사) — id·이름만. 일괄권한 편집기의 '소속' 선택칸에서 쓴다.
    organization_preview 는 전 직원을 훑어 무거우므로, 여기선 apw_office 만 가볍게
    읽는다. 표가 없으면 빈 목록(화면이 죽지 않게)."""
    database = _source_database()
    try:
        rows = db.execute(
            text(
                f"""SELECT RTRIM(OfficeID) AS office_id, RTRIM(Name) AS office_name, SEQ
                    FROM [{database}].dbo.apw_office WHERE Active = 'Y' ORDER BY SEQ"""
            )
        ).mappings().all()
    except SQLAlchemyError:
        db.rollback()
        return []
    return [
        {"office_id": str(r["office_id"]), "office_name": str(r["office_name"])}
        for r in rows
    ]


def list_permissions(db: Session) -> "list[dict[str, Any]]":
    """권한 목록 (활성·비활성 모두, 직원 이름 보강)."""
    rows = db.scalars(
        select(UserPermission).order_by(UserPermission.updated_at.desc())
    ).all()
    if not rows:
        return []
    database = _source_database()
    names: "dict[str, dict[str, Any]]" = {}
    usr_ids = [row.usr_id for row in rows]
    params = {f"u_{index}": usr_id for index, usr_id in enumerate(usr_ids)}
    placeholders = ",".join(f"CAST(:{name} AS varchar(50))" for name in params)
    for m in db.execute(
        text(
            f"""
            SELECT RTRIM(USR_ID) AS usr_id, RTRIM(EMP) AS emp_name,
                   RTRIM(OFFICE_ID) AS office_id, RTRIM(RTRM_FL) AS rtrm_fl
            FROM [{database}].dbo.TMWCMN_USR_BAC_INFO
            WHERE USR_ID IN ({placeholders})
            """
        ),
        params,
    ).mappings():
        names[m["usr_id"]] = m
    return [
        {
            "id": row.id,
            "usr_id": row.usr_id,
            "emp_name": (names.get(row.usr_id) or {}).get("emp_name"),
            "office_name": _office_name(
                db, (names.get(row.usr_id) or {}).get("office_id") or ""
            ),
            "retired": (names.get(row.usr_id) or {}).get("rtrm_fl") not in (None, "0"),
            "view_all_offices": row.view_all_offices == "Y",
            "memo": row.memo,
            "active": row.active == "Y",
            "updated_at": row.updated_at.isoformat(sep=" ", timespec="minutes")
            if row.updated_at else None,
        }
        for row in rows
    ]


class PermissionError_(ValueError):
    pass


def grant_permission(
    db: Session, usr_id: str, memo: "str | None",
    *, requester_usr_seq: int | None = None, visible_office_id: str | None = None,
) -> UserPermission:
    """전체지사 조회 권한 부여 (기존 행이 있으면 재활성화).

    2026-08-16 진단: 이 함수는 usr_id 문자열만 받고 **그 사람이 실재하는지, 재직
    중인지, 내 지사 사람인지 아무것도 안 봤다.** 옆칸 /users/role 은 8/13 에
    지사 경계를 붙였는데 여기만 빠져 있어, 지사 권한관리자가 본사 직원에게
    전체지사 조회를 붙일 수 있었다. a10_user_permission 이 지금 0행이라 조용할 뿐,
    load_access_policy 는 이 표를 계속 읽는다.
    """
    usr_id = usr_id.strip()
    if not usr_id:
        raise PermissionError_("사용자 ID가 비어 있습니다.")
    target = _identity_by_usr_id(db, usr_id)
    if target is None:
        raise PermissionError_(f"'{usr_id}' 사용자를 찾을 수 없습니다.")
    if requester_usr_seq and int(requester_usr_seq) == int(target.usr_seq):
        raise PermissionError_(
            "자기 권한은 자기가 바꿀 수 없습니다. 다른 권한관리자에게 요청하세요."
        )
    if visible_office_id is not None and target.office_id != visible_office_id:
        raise PermissionError_("다른 지사 사용자의 권한은 바꿀 수 없습니다.")
    if target.office_id != "10":
        # save_access_policy 와 같은 잣대다 — 지사 직원에게 전체지사 조회는 없다.
        raise PermissionError_("지사 직원에게는 전체지사 조회권한을 부여할 수 없습니다.")
    row = db.scalars(
        select(UserPermission).where(UserPermission.usr_id == usr_id)
    ).first()
    if row is None:
        row = UserPermission(usr_id=usr_id)
        db.add(row)
    was = {"view_all_offices": row.view_all_offices, "active": row.active}         if row.usr_id and row.active else None
    row.view_all_offices = "Y"
    row.active = "Y"
    if memo is not None:
        row.memo = memo.strip()[:200] or None
    record_change(
        db, target_kind="grant", target_key=usr_id, target_label=target.emp_name,
        action="assign", before=was, after={"view_all_offices": "Y", "active": "Y"},
        actor_usr_seq=requester_usr_seq, reason=(memo or "").strip() or None,
    )
    db.commit()
    return row


def revoke_permission(
    db: Session, permission_id: int, *, visible_office_id: str | None = None,
) -> UserPermission:
    """권한 회수 (행은 남기고 비활성화 — 이력 유지).

    visible_office_id 가 있으면(=지사 관리자) **그 지사 사람의 권한만** 회수할 수 있다 —
    grant_permission 과 같은 경계다. 안 그러면 지사 관리자가 permission_id 를 훑어
    본사 사용자의 전체지사 grant 를 회수할 수 있었다(2026-08-19 감사).
    """
    row = db.get(UserPermission, permission_id)
    if row is None:
        raise PermissionError_("해당 권한이 없습니다.")
    if visible_office_id is not None:
        ident = _identity_by_usr_id(db, row.usr_id)
        if ident is None or str(ident.office_id) != str(visible_office_id):
            raise PermissionError_("다른 지사 사용자의 권한은 회수할 수 없습니다.")
    row.active = "N"
    record_change(
        db, target_kind="grant", target_key=row.usr_id, action="unassign",
        before={"active": "Y"}, after={"active": "N"},
    )
    db.commit()
    return row


def _identity_by_usr_id(db: Session, usr_id: str) -> "Any | None":
    """usr_id 문자열로 재직자를 찾아 identity 를 돌려준다. 없으면 None.

    a10_user_permission 이 usr_seq 가 아니라 usr_id 를 키로 쓰기 때문에 필요하다.
    _policy_target 과 **같은 재직 조건**(USE_YN='Y', RTRM_FL='0')을 쓴다 —
    조건이 갈리면 한쪽에서 막힌 사람이 다른 쪽에서 통과한다.
    """
    database = _source_database()
    row = db.execute(
        text(
            f"""
            SELECT TOP 1 u.USR_SEQ AS usr_seq
            FROM [{database}].dbo.TMWCMN_USR_BAC_INFO u
            WHERE RTRIM(u.USR_ID) = :usr_id
              AND u.USE_YN = 'Y' AND u.RTRM_FL = '0'
            ORDER BY u.USR_SEQ DESC
            """
        ),
        {"usr_id": usr_id},
    ).mappings().first()
    if row is None:
        return None
    try:
        _source, identity = _policy_target(db, int(row["usr_seq"]))
    except PermissionError_:
        return None
    return identity


def _policy_target(db: Session, usr_seq: int) -> "tuple[dict[str, Any], Any]":
    database = _source_database()
    row = db.execute(
        text(
            f"""
            SELECT TOP 1
                u.USR_SEQ AS usr_seq,
                RTRIM(u.USR_ID) AS usr_id,
                RTRIM(u.EMP) AS emp_name,
                RTRIM(u.OFFICE_ID) AS office_id,
                RTRIM(u.APPRAISAL_FL) AS appraisal_fl,
                LOWER(RTRIM(s.Dept_Nm)) AS seat_dept,
                NULLIF(LTRIM(RTRIM(d.CHRG_BIZ)), '') AS chrg_biz
            FROM [{database}].dbo.TMWCMN_USR_BAC_INFO u
            LEFT JOIN [{database}].dbo.TMWCMN_EMPT_DTL d
                ON d.USR_SEQ = u.USR_SEQ
            OUTER APPLY (
                SELECT TOP 1 s.Dept_Nm
                FROM [{database}].dbo.Seat_userinfo s
                WHERE RTRIM(s.APWID) = RTRIM(u.USR_ID)
                  AND RTRIM(u.OFFICE_ID) = '10'
            ) s
            WHERE u.USR_SEQ = :usr_seq
              AND u.USE_YN = 'Y' AND u.RTRM_FL = '0'
            """
        ),
        {"usr_seq": usr_seq},
    ).mappings().first()
    if row is None:
        raise PermissionError_("재직 중인 사용자를 찾을 수 없습니다.")
    return dict(row), identity_from_row(row)


def get_user_policy(
    db: Session,
    *,
    usr_seq: int,
    visible_office_id: str | None = None,
) -> dict[str, Any]:
    """단건 사용자 정책 — 화면 토글 초기화용.

    기본값(부서 정책), 현재 적용값(예외 반영), 부여 가능 메뉴를 함께 돌려준다.
    화면은 effective로 토글을 켜고, 저장 시 default와 다른 항목만 override로 보낸다.
    """
    _source, identity = _policy_target(db, usr_seq)
    if visible_office_id is not None and identity.office_id != visible_office_id:
        raise PermissionError_("다른 지사 사용자의 권한을 조회할 수 없습니다.")
    row: "AccessPolicy | None" = None
    try:
        row = db.get(AccessPolicy, usr_seq)
    except SQLAlchemyError:
        db.rollback()
    # 일괄권한(부서·개인)을 **반드시** 함께 푼다. 안 그러면 화면은 코드 기본값을
    # 보여 주는데 실제 로그인은 일괄권한값으로 돌아, 화면과 현실이 어긋난다. 더 나쁜
    # 것은 저장이다 — 화면은 'default 와 다른 것만 override 로' 보내므로, 기준이
    # 틀리면 일괄권한으로 준 권한이 통째로 개인 예외로 굳어 버린다(2026-08-13 검수).
    grant = resolve_role(db, identity)
    defaults = build_access_policy(identity, None, grant=grant)
    effective = build_access_policy(identity, row, grant=grant)
    available = available_menu_keys(identity)
    return {
        "role": effective.get("role"),
        "policy_source": effective.get("policy_source"),
        "identity": {
            "usr_seq": identity.usr_seq,
            "usr_id": identity.usr_id,
            "emp_name": identity.emp_name,
            "office_id": identity.office_id,
            "department_name": identity.department_name,
            "employee_type": identity.employee_type,
            "is_appraiser": identity.is_appraiser,
        },
        "can_view_all_offices": identity.office_id == HEAD_OFFICE_ID,
        "menus": [
            {
                "key": key,
                "available": key in available,
                "default": defaults["menu_permissions"][key],
                "effective": effective["menu_permissions"][key],
            }
            for key in MENU_KEYS
        ],
        "defaults": {
            "view_all_offices": defaults["view_all_offices"],
            "view_other_users": defaults["view_other_users"],
        },
        "effective": {
            "view_all_offices": effective["view_all_offices"],
            "view_other_users": effective["view_other_users"],
        },
        "stored": {
            "has_row": row is not None,
            "active": (row.active == "Y") if row is not None else False,
            "memo": row.memo if row is not None else None,
        },
    }


def _permission_managers(db: Session) -> "set[int]":
    """지금 권한관리(permissionManage)가 켜진 활성 사용자."""
    holders: "set[int]" = set()
    try:
        rows = db.query(AccessPolicy).filter(AccessPolicy.active == "Y").all()
    except SQLAlchemyError:
        return holders
    for row in rows:
        if _menu_overrides(row.menu_overrides_json).get("permissionManage"):
            holders.add(int(row.usr_seq))
    return holders


def _guard_last_permission_manager(
    db: Session, *, usr_seq: int, identity: Any,
    menu_overrides: "dict[str, bool] | None", active: bool
) -> None:
    """마지막 권한관리자를 끄면 아무도 권한을 되돌릴 수 없다.

    permissionManage 는 어느 기본값 집합에도 없다(fail-closed 라 옳다).
    그래서 이 권한은 **DB 예외로만** 존재하고, 지금 실제 보유자는 한 명뿐이다
    (2026-08-07 실측). 그 한 행을 끄거나 비활성화하면 권한관리 화면에 들어갈
    사람이 0명이 되어 SQL 을 직접 고치는 수밖에 없다. 그 자물쇠를 막는다.
    """
    # 보유자 집계는 **일괄권한까지 세는 쪽**을 쓴다. 옛 _permission_managers 는
    # a10_access_policy 예외만 세어, 일괄권한으로 권한관리를 받은 사람이 있어도
    # '마지막 한 명' 이라며 저장을 막았다(2026-08-13 검수).
    from app.services.access_roles import permission_manager_holders  # noqa: PLC0415
    try:
        holders = permission_manager_holders(db)
    except SQLAlchemyError:
        holders = _permission_managers(db)      # 일괄권한 표가 아직 없는 환경
    if int(usr_seq) not in holders:
        return          # 원래 보유자가 아니면 줄어들 일이 없다
    # permissionManage 는 묶음(일괄권한)으로도 온다 — raw menu_overrides 만 보면, 묶음으로
    # 권한관리를 받은 사람이 스코프(전지사·남열람)만 바꿔도 그 키가 override 에 없어서
    # '권한관리를 잃는다'고 오판해 저장을 막았다(2026-08-19 감사). 형제 _self_keeps_manage
    # 처럼 build_access_policy 로 최종 유효권한을 본다(스코프는 permissionManage 와 무관).
    if _self_keeps_manage(db, identity, view_all=None, view_other=None,
                          menu_overrides=menu_overrides, active=active):
        return
    if len(holders) <= 1:
        raise PermissionError_(
            "마지막 권한관리자입니다. 다른 사람에게 권한관리를 먼저 부여한 뒤에 "
            "이 사용자의 권한을 내려 주세요."
        )


def _self_keeps_manage(
    db: Session, identity: Any, *, view_all: "bool | None",
    view_other: "bool | None", menu_overrides: "dict[str, bool] | None", active: bool,
) -> bool:
    """이 개인 예외를 저장한 뒤에도 이 사람이 '권한 관리'를 유지하나.

    자기 수정을 허용하되 자기잠금만 막을 때 쓴다 — 일괄권한(부서·개인)까지 함께 풀어
    최종값을 본다(개인 예외로 permissionManage 를 끄거나, 예외로만 갖고 있다가 예외를
    내리면 잃는다)."""
    from app.services.access_policy import (  # noqa: PLC0415
        build_access_policy, encode_menu_overrides, resolve_role,
    )
    from app.models.access_policy import AccessPolicy  # noqa: PLC0415
    proposed = AccessPolicy(
        usr_seq=identity.usr_seq, usr_id=identity.usr_id,
        view_all_offices_override=(None if view_all is None else ("Y" if view_all else "N")),
        view_other_users_override=(None if view_other is None else ("Y" if view_other else "N")),
        menu_overrides_json=encode_menu_overrides(menu_overrides),
        active="Y" if active else "N",
    ) if active else None
    grant = resolve_role(db, identity)
    pol = build_access_policy(identity, proposed, grant=grant)
    return bool(pol["menu_permissions"].get("permissionManage"))


def _guard_self_keep_manage(
    db: Session, requester_usr_seq: "int | None", identity: Any, *,
    view_all: "bool | None", view_other: "bool | None",
    menu_overrides: "dict[str, bool] | None", active: bool,
) -> None:
    """자기 권한은 자기가 바꿀 수 있다 — 관리자 1명 지사는 자기가 관리해야 한다
    (2026-08-19 사용자 요청). 단 **자기 '권한 관리' 는 스스로 뗄 수 없다**: 그러면
    그 소속에 관리자가 0명이 되어 SQL 로만 되돌린다. 뗄 때는 다른 관리자나 본사가 한다.
    (조회 범위·메뉴는 소속 상한 안에서만 바뀌므로 자기확대 위험이 없다.)"""
    if not (requester_usr_seq and int(requester_usr_seq) == int(identity.usr_seq)):
        return
    if not _self_keeps_manage(db, identity, view_all=view_all, view_other=view_other,
                              menu_overrides=menu_overrides, active=active):
        raise PermissionError_(
            "자기 '권한 관리' 권한은 스스로 뗄 수 없습니다. "
            "다른 권한관리자나 본사에 요청하세요."
        )


def save_access_policy(
    db: Session,
    *,
    usr_seq: int,
    requester_usr_seq: int,
    view_all_offices: "bool | None",
    view_other_users: "bool | None",
    menu_overrides: "dict[str, bool] | None",
    active: bool,
    memo: "str | None",
    visible_office_id: str | None = None,
) -> dict[str, Any]:
    """한 사람 한 행의 권한 예외를 저장한다. 테이블 생성 전에는 명확히 실패한다."""
    source, identity = _policy_target(db, usr_seq)
    _guard_self_keep_manage(
        db, requester_usr_seq, identity, view_all=view_all_offices,
        view_other=view_other_users, menu_overrides=menu_overrides, active=active,
    )
    if visible_office_id is not None and identity.office_id != visible_office_id:
        raise PermissionError_("다른 지사 사용자의 권한을 변경할 수 없습니다.")
    if identity.office_id != "10" and view_all_offices:
        raise PermissionError_("지사 직원에게는 전체지사 조회권한을 부여할 수 없습니다.")
    _guard_last_permission_manager(
        db, usr_seq=usr_seq, identity=identity,
        menu_overrides=menu_overrides, active=active,
    )
    try:
        row = db.get(AccessPolicy, usr_seq)
        # 고치기 전 모습. 되돌리려면 before 가 있어야 한다.
        prior = None if row is None else {
            "view_all_offices": row.view_all_offices_override,
            "view_other_users": row.view_other_users_override,
            "menu_overrides": _menu_overrides(row.menu_overrides_json),
            "active": row.active,
        }
        if row is None:
            row = AccessPolicy(usr_seq=usr_seq, usr_id=identity.usr_id)
            db.add(row)
        row.usr_id = identity.usr_id
        row.view_all_offices_override = (
            None if view_all_offices is None else ("Y" if view_all_offices else "N")
        )
        row.view_other_users_override = (
            None if view_other_users is None else ("Y" if view_other_users else "N")
        )
        row.menu_overrides_json = encode_menu_overrides(menu_overrides)
        row.active = "Y" if active else "N"
        row.updated_by_usr_seq = requester_usr_seq
        # 사유를 안 적었다고 **전에 적어 둔 사유를 지우지는 않는다.**
        # 화면이 빈 칸을 늘 보내므로, 그대로 받으면 저장할 때마다 사유가 날아갔다.
        if memo and memo.strip():
            row.memo = memo.strip()[:200]
        record_change(
            db, target_kind="policy", target_key=usr_seq,
            target_label=identity.emp_name, action="update",
            before=prior,
            after={
                "view_all_offices": row.view_all_offices_override,
                "view_other_users": row.view_other_users_override,
                "menu_overrides": menu_overrides,
                "active": row.active,
            },
            actor_usr_seq=requester_usr_seq,
            reason=(memo or "").strip() or None,
        )
        db.commit()
        db.refresh(row)
    except SQLAlchemyError as exc:
        db.rollback()
        raise PermissionError_(
            "권한 테이블이 아직 생성되지 않았거나 저장할 수 없습니다."
        ) from exc
    return {
        "identity": {
            "usr_seq": identity.usr_seq,
            "usr_id": identity.usr_id,
            "emp_name": identity.emp_name,
            "office_id": identity.office_id,
            "department_name": identity.department_name,
            "employee_type": identity.employee_type,
        },
        # grant 를 빼먹으면 일괄권한으로 메뉴를 받는 사람의 응답 effective 가
        # 전부 꺼진 것으로 나온다 — get_user_policy(478행)와 같은 기준을 쓴다.
        "effective": build_access_policy(identity, row, grant=resolve_role(db, identity)),
        "active": row.active == "Y",
        "memo": row.memo,
        "source": source,
    }
