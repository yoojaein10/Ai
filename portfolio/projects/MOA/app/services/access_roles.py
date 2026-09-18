"""일괄권한(역할) 관리 — 만들기·고치기·부서와 개인에 붙이기.

왜 있나 (2026-08-13 요청)
  지금까지는 권한을 **사람 하나씩만** 고칠 수 있었고, 부서·직군 기본값은 **코드에
  박혀** 있어 바꾸려면 배포를 해야 했다. 이 모듈은 그걸 '화면에서 일괄권한을 만들고
  부서·사람에 붙이는' 방식으로 바꾼다.

해석 순서 (사용자 확정) — **개인이 부서를 이긴다**
  ① 코드 기본값(과도기)  ② 부서 일괄권한이 ①을 대체  ③ 개인 일괄권한이 ②를 대체
  ④ 개인 예외(a10_access_policy)가 그 위에 얹힌다
실제 해석은 access_policy.resolve_role / build_access_policy 가 한다. 여기서는
그 표를 읽고 쓰는 일만 한다.

일괄권한은 백엔드에서는 **참조**다 — assign_department/assign_user 는 role_id 로 걸므로,
고치면 그걸 쓰는 부서·사람이 즉시 따라간다. 그래서 화면이 지우거나 고치기 전에
'쓰는 곳 N군데'를 보여줄 수 있도록 usage 를 같이 돌려준다.
다만 **화면의 기본 동작은 2026-08-18 부터 복사**다: preview.js resolveDraftRole 은
부서에 세트를 걸어도 참조 대신 그 부서 전용 자동일괄권한(복사본)을 만들고, 개인 편집기는
개인 예외로 복사한다. 삭제도 detach 로 쓰던 곳을 복사본으로 떼어낸 뒤 지운다. 즉
참조 메커니즘은 남아 있지만, 담당자가 만드는 새 배정은 서로 안 얽힌다.

표가 아직 없는 환경(운영 반영 전)에서는 조회가 빈 목록을 돌려주고 저장은
RoleError 를 낸다 — 화면이 죽지 않고 '표를 먼저 만드세요'라고 말할 수 있게.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.access_role import AccessDeptRole, AccessRole, AccessUserRole
from app.services.access_history import record
from app.services.access_policy import (
    HEAD_OFFICE_FULL_ACCESS_DEPARTMENTS,
    HEAD_OFFICE_ID,
    MENU_KEYS,
    resolve_role,
)


class LockoutError(ValueError):
    """이 변경이 사람을 프로그램 밖으로 밀어낸다 — 확인을 받고 다시 부르면 진행한다.

    RoleError 와 나누는 이유: 화면이 '막힌 것' 과 '확인이 필요한 것' 을 달리
    보여 줘야 한다. 앞의 것은 고쳐야 하고, 뒤의 것은 사람이 결정할 일이다.
    """

    def __init__(self, message: str, *, locked: int) -> None:
        super().__init__(message)
        self.locked = locked


class RoleError(ValueError):
    """화면에 그대로 보여 줄 수 있는 실패."""


def _yn(value: bool | None) -> str | None:
    return None if value is None else ("Y" if value else "N")


def _is_admin_dept(office_id: str, department_name: str) -> bool:
    """권한관리(permissionManage)를 **부서 단위로** 줄 수 있는 예외 부서.

    본사 재무팀·전산정보팀만(이 시스템을 운영하는 관리팀 — 2026-08-18 사용자 지정).
    이 두 팀은 새 입사자도 자동 관리자가 되도록 부서에 권한관리를 붙일 수 있다.
    나머지 부서는 여전히 막는다(부서 인원이 늘면 관리자가 조용히 불어나는 사고 방지).
    """
    return (
        str(office_id).strip() == HEAD_OFFICE_ID
        and (department_name or "").strip() in HEAD_OFFICE_FULL_ACCESS_DEPARTMENTS
    )


def _keys(raw: str | None) -> list[str]:
    try:
        data = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return []
    # MENU_KEYS 순서로 정렬해 화면·저장이 늘 같은 차례를 본다.
    got = {str(k) for k in data if isinstance(k, str)}
    return [k for k in MENU_KEYS if k in got]


def _row_to_dict(row: AccessRole, usage: dict[int, dict[str, int]]) -> dict[str, Any]:
    used = usage.get(row.role_id, {})
    return {
        "role_id": row.role_id,
        "name": row.name,
        "office_id": row.office_id,
        "menu_keys": _keys(row.menu_keys_json),
        "view_all_offices": None if row.view_all_offices is None else row.view_all_offices == "Y",
        "view_other_users": None if row.view_other_users is None else row.view_other_users == "Y",
        "memo": row.memo,
        # 고치기 전에 '몇 군데가 따라 바뀌는지' 보여 주려고 붙인다.
        "used_by": {"departments": used.get("dept", 0), "users": used.get("user", 0)},
    }


def _usage(db: Session) -> dict[int, dict[str, int]]:
    out: dict[int, dict[str, int]] = {}
    for model, kind in ((AccessDeptRole, "dept"), (AccessUserRole, "user")):
        rows = db.execute(
            select(model.role_id, func.count()).where(model.active == "Y")
            .group_by(model.role_id)
        ).all()
        for role_id, count in rows:
            out.setdefault(int(role_id), {})[kind] = int(count)
    return out


def _manage_role_ids(db: Session) -> set[int]:
    """permissionManage 를 켠 살아 있는 일괄권한."""
    out: set[int] = set()
    for row in db.scalars(select(AccessRole).where(AccessRole.active == "Y")).all():
        if "permissionManage" in _keys(row.menu_keys_json):
            out.add(int(row.role_id))
    return out


def permission_manager_holders(db: Session, org: dict | None = None) -> set[int]:
    """지금 권한관리 화면에 들어갈 수 있는 **사람**의 usr_seq.

    세 갈래를 모두 센다 — 어느 하나만 보면 자물쇠가 헐거워진다.
      ① 개인 예외(a10_access_policy 의 menu_overrides_json)
      ② 개인 일괄권한(a10_access_user_role → permissionManage 를 켠 일괄권한)
      ③ 부서 일괄권한(a10_access_dept_role) — **그 부서에 실제로 사람이 있어야** 센다.
         빈 부서에 붙은 매핑을 사람으로 세면, 실제 보유자가 0명인데 자물쇠가
         열려 있다고 착각한다.
    개인 예외는 ②③ 보다 뒤에 얹히므로 permissionManage=False 로 꺼 둔 사람은 뺀다.
    """
    from app.services.access_policy import _menu_overrides  # noqa: PLC0415
    from app.models.access_policy import AccessPolicy       # noqa: PLC0415
    from app.services.permissions import organization_preview  # noqa: PLC0415

    holders: set[int] = set()
    denied: set[int] = set()
    try:
        for row in db.scalars(
            select(AccessPolicy).where(AccessPolicy.active == "Y")
        ).all():
            got = _menu_overrides(row.menu_overrides_json)
            if got.get("permissionManage") is True:
                holders.add(int(row.usr_seq))
            elif got.get("permissionManage") is False:
                denied.add(int(row.usr_seq))
    except SQLAlchemyError:
        pass        # 읽기 실패 — 여기서 rollback 하면 검사 중인 변경이 날아간다

    role_ids = set()
    try:
        role_ids = _manage_role_ids(db)
        if role_ids:
            for row in db.scalars(
                select(AccessUserRole).where(
                    AccessUserRole.active == "Y", AccessUserRole.role_id.in_(role_ids)
                )
            ).all():
                holders.add(int(row.usr_seq))
            dept_keys = {
                (row.office_id, row.department_name)
                for row in db.scalars(
                    select(AccessDeptRole).where(
                        AccessDeptRole.active == "Y",
                        AccessDeptRole.role_id.in_(role_ids),
                    )
                ).all()
            }
            if dept_keys:
                # 개인 일괄권한이 부서를 이기므로, 개인 일괄권한이 따로 붙은 사람은 부서로 세지 않는다.
                overridden = {
                    int(row.usr_seq)
                    for row in db.scalars(
                        select(AccessUserRole).where(AccessUserRole.active == "Y")
                    ).all()
                    if int(row.role_id) not in role_ids
                }
                if org is None:
                    org = organization_preview(db)
                for office in org.get("offices") or []:
                    for dept in office.get("departments") or []:
                        if (str(office.get("id")), str(dept.get("name"))) not in dept_keys:
                            continue
                        for emp in dept.get("employees") or []:
                            # 계정 미연결·퇴사자는 account_linked=False → usr_seq=None 이다.
                            # usr_id 를 usr_seq 대용으로 세면 퇴사자(예: 고정은 usr_id 4467)가
                            # 유령 권한관리자로 남으므로, usr_seq 없으면 세지 않는다.
                            seq = emp.get("usr_seq")
                            if seq is None:
                                continue
                            seq = int(seq)
                            if seq not in overridden:
                                holders.add(seq)
    except SQLAlchemyError:
        pass
    return holders - denied


def locked_out_count(db: Session, *, office_id: str, department_name: str,
                     org: dict | None = None) -> int:
    """이 부서에서 **메뉴가 0개가 되어 프로그램에 못 들어오는** 사람 수.

    메뉴 0개는 빈 화면이 아니라 로그인 거절이다(users.py:97 ACCESS_DENIED).
    부서 드롭다운을 '권한 없음' 으로 한 칸 옮기면 그 부서 전원이 그렇게 된다 —
    셀렉트 한 번에 되돌릴 수 없는 일이 벌어지므로, 화면이 확인받을 수 있도록
    몇 명인지 세어 준다.
    """
    from app.services.access_policy import (  # noqa: PLC0415
        build_access_policy, identity_from_row,
    )
    from app.services.permissions import _policy_target  # noqa: PLC0415
    from app.services.permissions import organization_preview  # noqa: PLC0415

    locked = 0
    try:
        # org 를 받아 쓰면 전사 스캔을 건너뛴다 — 일괄(부서 수십 개)에서 대상마다
        # organization_preview 를 다시 부르면 요청 하나가 수십 초짜리가 된다.
        if org is None:
            org = organization_preview(db)
        for office in org.get("offices") or []:
            if str(office.get("id")) != str(office_id):
                continue
            for dept in office.get("departments") or []:
                if str(dept.get("name")) != str(department_name):
                    continue
                for emp in dept.get("employees") or []:
                    seq = emp.get("usr_seq")
                    if seq is None:
                        continue
                    try:
                        _src, identity = _policy_target(db, int(seq))
                    except Exception:      # noqa: BLE001 — 못 푸는 사람은 세지 않는다
                        continue
                    grant = resolve_role(db, identity)
                    policy = build_access_policy(identity, None, grant=grant)
                    if not policy["menu_keys"]:
                        locked += 1
    except SQLAlchemyError:
        pass
    return locked


def locks_out_user(db: Session, usr_seq: int, role_id: int | None) -> bool:
    """이 일괄권한을 이 사람에게 붙이면 **메뉴 0개가 되어 로그인이 거절되나**.

    부서 경로(locked_out_count)와 같은 잣대를 개인에도 적용한다. 종전에는 개인
    부여에 이 검사가 없어서, 본사 전용만 든 세트를 지사 사람에게 걸면 조용히
    잠겼다 — 교집합(available)이 본사 전용을 전부 잘라내 0개가 되기 때문이다
    (2026-08-17 사용자 지적으로 발견).
    """
    from app.models.access_policy import AccessPolicy               # noqa: PLC0415
    from app.services.access_policy import _role_of, build_access_policy  # noqa: PLC0415
    from app.services.permissions import _policy_target              # noqa: PLC0415

    try:
        _source, identity = _policy_target(db, int(usr_seq))
    except Exception:      # noqa: BLE001 — 못 푸는 사람은 판단하지 않는다
        return False
    # 붙일 일괄권한(없으면 코드 기본값으로 돌아간다)과 **개인 예외까지** 함께 본다.
    # 개인 예외로 메뉴가 하나라도 살아 있으면 잠기지 않는다 — locked_out_count 는
    # 부서 전원을 세느라 예외를 못 보지만, 한 사람이면 정확히 볼 수 있다.
    grant = _role_of(db, int(role_id), "user") if role_id is not None else None
    try:
        row = db.get(AccessPolicy, int(usr_seq))
    except SQLAlchemyError:
        row = None
    policy = build_access_policy(identity, row, grant=grant)
    return not policy["menu_keys"]


def guard_permission_managers(db: Session, *, before: set[int], action: str) -> None:
    """이 변경으로 권한관리자가 **있다가 0명이 되면** 막는다.

    '늘 1명 이상이어야 한다' 가 아니라 **'더 나빠지게 하지 마라'** 다. 처음에 전자로
    썼더니 관리자가 원래 0명인 상태(표를 막 만든 직후 등)에서 무관한 저장까지
    전부 막혔다. before 가 비어 있으면 이 검사는 할 말이 없다.

    **flush 뒤·commit 앞에서 부른다.** 바뀐 상태를 같은 트랜잭션 안에서 봐야 정확한데,
    커밋한 뒤에 되돌리려 하면 이미 늦다(rollback 이 아무것도 안 한다 — 처음에 그렇게
    썼다가 고쳤다). 여기서 RoleError 를 던지면 부르는 쪽이 rollback 한다.

    왜 필요한가: 종전 자물쇠(_guard_last_permission_manager)는 a10_access_policy
    한 갈래만 봐서, 일괄권한으로 권한을 옮기거나 부서 일괄권한에서 permissionManage 를 빼면
    **아무 검사 없이** 전원이 잠겼다. 그러면 SQL 을 직접 고치는 수밖에 없다.
    """
    if not before or permission_manager_holders(db):
        return
    raise RoleError(
        f"{action} 하면 권한 관리 화면에 들어갈 수 있는 사람이 0명이 됩니다. "
        "다른 사람에게 권한 관리를 먼저 부여한 뒤에 다시 시도하세요."
    )


def list_roles(db: Session, office_id: str | None = None) -> list[dict[str, Any]]:
    """살아 있는 일괄권한. office_id 를 주면 **그 소속만** — 공용 없이 각 소속(본사·지사)이
    자기 일괄권한만 만들고 본다(2026-08-18). 표가 없으면 빈 목록(화면이 죽지 않게)."""
    try:
        q = select(AccessRole).where(AccessRole.active == "Y")
        if office_id is not None:
            q = q.where(AccessRole.office_id == office_id)
        rows = db.scalars(q.order_by(AccessRole.name)).all()
        usage = _usage(db)
    except SQLAlchemyError:
        db.rollback()
        return []
    return [_row_to_dict(row, usage) for row in rows]


def save_role(
    db: Session,
    *,
    role_id: int | None,
    name: str,
    menu_keys: list[str],
    view_all_offices: bool | None,
    view_other_users: bool | None,
    memo: str | None,
    updated_by_usr_seq: int | None,
    office_id: str = "10",
    confirm_lockout: bool = False,
) -> dict[str, Any]:
    """일괄권한 하나를 만들거나 고친다. role_id 가 없으면 새로 만든다.

    붙어 있는 일괄권한을 고치는 것은 **그 부서·사람을 지금 바꾸는 것**이라, 붙일 때
    거는 검사를 여기서도 똑같이 걸어야 한다. 2026-08-16 진단에서 두 가드가
    '붙일 때만' 보고 있어, 순서를 둘로 나누면 그냥 통과했다.
    """
    label = (name or "").strip()
    if not label:
        raise RoleError("일괄권한 이름을 입력하세요.")
    if len(label) > 60:
        raise RoleError("일괄권한 이름은 60자까지입니다.")
    unknown = [k for k in menu_keys if k not in MENU_KEYS]
    if unknown:
        raise RoleError(f"모르는 메뉴 키입니다: {', '.join(unknown)}")
    keys = [k for k in MENU_KEYS if k in set(menu_keys)]
    office = (office_id or "10").strip() or "10"

    before = permission_manager_holders(db)
    # 고치기 전 모습을 먼저 떠 둔다 — 되돌리려면 before 가 있어야 한다.
    prior = None
    if role_id is not None:
        old_row = db.get(AccessRole, role_id)
        if old_row is not None:
            # 남의 소속 일괄권한은 고칠 수 없다 — office 는 로그인 계정으로 강제되므로,
            # 지사 담당자가 다른 소속 role_id 를 넘겨도 여기서 막힌다(2026-08-18).
            if old_row.office_id != office:
                raise RoleError("다른 소속의 일괄권한은 고칠 수 없습니다.")
            prior = {"name": old_row.name, "menu_keys": _keys(old_row.menu_keys_json),
                     "view_all_offices": old_row.view_all_offices,
                     "view_other_users": old_row.view_other_users}
    try:
        # 이름 유일성은 **소속별**이다 — 지사마다 '평가사 기본' 을 따로 둘 수 있다.
        dup = db.scalars(
            select(AccessRole).where(
                AccessRole.name == label, AccessRole.office_id == office,
                AccessRole.active == "Y")
        ).first()
        if dup is not None and dup.role_id != role_id:
            raise RoleError(f"'{label}' 은 이 소속에 이미 있는 일괄권한 이름입니다.")

        if role_id is None:
            row = AccessRole(name=label, office_id=office)
            db.add(row)
        else:
            row = db.get(AccessRole, role_id)
            if row is None or row.active != "Y":
                raise RoleError("없는 일괄권한입니다.")
            row.name = label
            row.office_id = office
        row.menu_keys_json = json.dumps(keys, ensure_ascii=False)
        row.view_all_offices = _yn(view_all_offices)
        row.view_other_users = _yn(view_other_users)
        row.memo = (memo or "").strip() or None
        row.updated_by_usr_seq = updated_by_usr_seq
        db.flush()          # 같은 트랜잭션 안에서 바뀐 상태를 보이게 한다
        guard_permission_managers(db, before=before, action="이 일괄권한을 이렇게 저장")

        # 이 일괄권한이 지금 어느 부서에 붙어 있나. 붙어 있다면 '부서에 붙이는 것'과
        # 같은 검사를 받아야 한다 — 안 그러면 깨끗한 일괄권한을 먼저 붙여 두고
        # 나중에 고쳐서 두 가드를 모두 우회할 수 있다.
        attached = list(db.scalars(
            select(AccessDeptRole).where(
                AccessDeptRole.role_id == row.role_id, AccessDeptRole.active == "Y"
            )
        ))
        # 본사 재무팀·전산정보팀(관리팀)에만 붙어 있으면 권한관리를 넣어도 된다
        # (2026-08-18 사용자 지정). 그 외 부서가 하나라도 섞여 있으면 막는다.
        bad_attached = [a for a in attached
                        if not _is_admin_dept(a.office_id, a.department_name)]
        if bad_attached and "permissionManage" in keys:
            raise RoleError(
                "이 일괄권한은 부서에 붙어 있어 '권한 관리' 를 넣을 수 없습니다. "
                f"({', '.join(f'{a.office_id}·{a.department_name}' for a in bad_attached[:3])}"
                f"{' 외' if len(bad_attached) > 3 else ''}) "
                "부서에서 뗀 뒤에 고치거나, 개인에게 지정하세요."
            )
        # 개인에게 붙은 일괄권한도 함께 센다 — 부서만 세면 개인 배정된 일괄권한을 0메뉴로
        # 편집할 때 그 사람들이 확인 없이 조용히 잠긴다(2026-08-18 적대검증 발견).
        user_holders = list(db.scalars(
            select(AccessUserRole.usr_seq).where(
                AccessUserRole.role_id == row.role_id, AccessUserRole.active == "Y"
            )
        ))
        if (attached or user_holders) and not confirm_lockout:
            # 메뉴 0개는 빈 화면이 아니라 로그인 거절이다. 붙어 있는 일괄권한을 비우면
            # 그 부서·사람이 그렇게 된다 — 부서(전원)와 개인 보유자를 모두 센다.
            locked = sum(
                locked_out_count(db, office_id=a.office_id, department_name=a.department_name)
                for a in attached
            )
            locked += sum(
                1 for seq in user_holders if locks_out_user(db, int(seq), row.role_id)
            )
            if locked:
                raise LockoutError(
                    f"이 일괄권한을 이렇게 저장하면 {locked}명이 프로그램에 들어올 수 "
                    "없게 됩니다(메뉴 0개는 로그인 거절입니다). 정말 그렇게 하려면 "
                    "확인을 눌러 주세요.", locked=locked,
                )
        record(
            db, target_kind="role", target_key=row.role_id, target_label=label,
            action="update" if role_id is not None else "create",
            before=prior,
            after={"name": label, "menu_keys": keys,
                   "view_all_offices": row.view_all_offices,
                   "view_other_users": row.view_other_users},
            actor_usr_seq=updated_by_usr_seq, reason=(memo or "").strip() or None,
        )
        db.commit()
        db.refresh(row)
        return _row_to_dict(row, _usage(db))
    except LockoutError:
        # RoleError 하위가 아니라 아래 갈래에 안 걸렸다 — flush 된 변경이 세션에
        # 남아 같은 세션의 다음 commit 에 묻는다(2026-08-17 적대 검증).
        db.rollback()
        raise
    except RoleError:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise RoleError(
            "일괄권한 표가 아직 없습니다. scripts/sql/20260813_create_access_role.sql 을 먼저 실행하세요."
        ) from exc


# 자동으로 만든 **숨김 일괄권한**의 표식. 부서 전용 복사본이라 담당자가 템플릿으로
# 다룰 것이 아니므로, 두 권한 화면 목록에서 이 memo 를 단 일괄권한은 감춘다.
# (permissions-preview.js namedPresets · permission-roles.js 가 같은 문자열로 거른다.)
AUTO_ROLE_MEMO = "부서 권한 화면에서 만든 묶음"


def _copy_role_name(db: Session, base: str) -> str:
    """복사본에 붙일 **유일한** 이름. 살아 있는 이름과 겹치면 번호를 붙인다
    (a10_access_role 은 active='Y' 이름에 유니크 인덱스가 걸려 있다)."""
    taken = set(db.scalars(select(AccessRole.name).where(AccessRole.active == "Y")))
    stem = f"자동 · {base} 사본"
    name = stem[:60]
    n = 2
    while name in taken and n < 100:
        suffix = f" ({n})"
        name = stem[: 60 - len(suffix)] + suffix
        n += 1
    return name


def _detach_role_to_copies(
    db: Session, row: AccessRole, updated_by: int | None
) -> dict[str, int]:
    """이 일괄권한을 쓰는 부서·개인을 **복사본으로 떼어낸 뒤** 일괄권한을 지울 수 있게 한다.

    · 부서 → 이 일괄권한의 복사본(숨김 자동일괄권한) 하나로 옮긴다. 복사본은 메뉴·조회범위가
      원본과 같으므로 그 부서 권한은 그대로다. 나중에 그 부서를 한 번 저장하면
      resolveDraftRole 이 그 부서 전용 자동일괄권한으로 다시 쪼갠다.
    · 개인 → 각자 **개인 예외**로 지금 유효한 권한을 그대로 박제하고 개인 일괄권한을
      해제한다. 어느 층이 드러나든 결과가 같도록 모든 메뉴 키·조회범위를 절대값으로
      박는다.

    아무도 권한을 잃지 않는다 — 그게 '쓰는 곳이 있으면 막는다'를 뒤집는 조건이다
    (2026-08-18 사용자 결정). **읽기(개인 현재정책 계산)를 먼저 다 한 뒤 쓰기로**
    넘어간다: load_access_policy 는 표가 없는 환경에서 db.rollback() 을 부르므로,
    쓰기 중간에 읽기가 끼면 앞서 쓴 것이 되돌아갈 수 있다."""
    from app.models.access_policy import AccessPolicy           # noqa: PLC0415
    from app.services.access_policy import load_access_policy   # noqa: PLC0415
    from app.services.permissions import _policy_target         # noqa: PLC0415

    dept_rows = list(db.scalars(select(AccessDeptRole).where(
        AccessDeptRole.role_id == row.role_id, AccessDeptRole.active == "Y")))
    user_rows = list(db.scalars(select(AccessUserRole).where(
        AccessUserRole.role_id == row.role_id, AccessUserRole.active == "Y")))

    # ── 읽기: 개인마다 '지금 유효한 권한'을 먼저 계산해 둔다(아직 아무것도 안 쓴다) ──
    pins: list[tuple[int, str | None, str, str, str]] = []
    for u in user_rows:
        try:
            _src, identity = _policy_target(db, u.usr_seq)
        except Exception:      # noqa: BLE001 — 못 푸는 사람(퇴사 등)은 박제할 것이 없다
            pins.append((u.usr_seq, None, "", "N", "N"))
            continue
        policy = load_access_policy(db, identity)
        overrides = {k: bool(policy["menu_permissions"].get(k)) for k in MENU_KEYS}
        pins.append((
            u.usr_seq, identity.usr_id,
            json.dumps(overrides, ensure_ascii=False),
            "Y" if policy["view_all_offices"] else "N",
            "Y" if policy["view_other_users"] else "N",
        ))

    # ── 쓰기: 부서 복사본 + 개인 예외 박제 + 개인 일괄권한 해제 ──
    moved_dept = 0
    if dept_rows:
        copy = AccessRole(
            name=_copy_role_name(db, row.name),
            menu_keys_json=row.menu_keys_json,
            view_all_offices=row.view_all_offices,
            view_other_users=row.view_other_users,
            memo=AUTO_ROLE_MEMO, active="Y", updated_by_usr_seq=updated_by,
        )
        db.add(copy)
        db.flush()                 # copy.role_id 확보 (부서가 이걸 가리켜야 한다)
        for d in dept_rows:
            d.role_id = copy.role_id
            d.updated_by_usr_seq = updated_by
            moved_dept += 1

    moved_user = 0
    for (usr_seq, usr_id, overrides_json, va, vo), u in zip(pins, user_rows):
        if usr_id is not None:     # 신원을 푼 사람만 박제한다(못 푼 사람은 로그인도 못 함)
            prow = db.get(AccessPolicy, usr_seq)
            if prow is None:
                prow = AccessPolicy(
                    usr_seq=usr_seq, usr_id=usr_id,
                    memo="일괄권한 삭제 시 자동 분리(복사)",
                )
                db.add(prow)
            prow.usr_id = usr_id
            prow.active = "Y"
            prow.menu_overrides_json = overrides_json
            prow.view_all_offices_override = va
            prow.view_other_users_override = vo
            prow.updated_by_usr_seq = updated_by
        u.active = "N"
        u.updated_by_usr_seq = updated_by
        moved_user += 1

    return {"departments": moved_dept, "users": moved_user}


def delete_role(
    db: Session, role_id: int, *, detach: bool = False, updated_by: int | None = None,
    office_id: str | None = None,
) -> dict[str, Any]:
    """일괄권한을 지운다(active='N').

    쓰는 곳이 있으면 **기본은 막는다** — 지우면 그 부서·사람이 말없이 아래 층으로
    돌아가는데, 그건 화면에 안 보이는 변화다. 다만 담당자가 확인하고 detach=True 로
    다시 부르면, 쓰던 부서·사람을 **복사본으로 떼어낸 뒤**(_detach_role_to_copies)
    지운다 — 아무도 권한을 잃지 않는다(2026-08-18 사용자 결정)."""
    try:
        row = db.get(AccessRole, role_id)
        if row is None or row.active != "Y":
            raise RoleError("없는 일괄권한입니다.")
        # 남의 소속 일괄권한은 지울 수 없다(소속은 로그인 계정으로 정해진다, 2026-08-18).
        if office_id is not None and row.office_id != office_id:
            raise RoleError("다른 소속의 일괄권한은 지울 수 없습니다.")
        used = _usage(db).get(role_id, {})
        n_dept, n_user = used.get("dept", 0), used.get("user", 0)
        if (n_dept or n_user) and not detach:
            # 화면이 이 문구를 받아 '각자 복사본으로 떼어낸 뒤 지웁니다' 확인창을
            # 띄우고, 확인하면 detach=True 로 다시 부른다.
            raise RoleError(
                f"이 일괄권한을 쓰는 곳이 있습니다 (부서 {n_dept} · 개인 {n_user}). "
                "확인하면 각자 복사본으로 떼어낸 뒤 지웁니다."
            )
        detached = {"departments": 0, "users": 0}
        if n_dept or n_user:
            detached = _detach_role_to_copies(db, row, updated_by)
        row.active = "N"
        record(
            db, target_kind="role", target_key=role_id, target_label=row.name,
            action="delete",
            before={"name": row.name, "menu_keys": _keys(row.menu_keys_json)},
            after=({"detached": detached}
                   if (detached["departments"] or detached["users"]) else None),
            actor_usr_seq=updated_by,
        )
        db.commit()
        return {"role_id": role_id, "deleted": True, "detached": detached}
    except RoleError:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise RoleError("일괄권한을 지우지 못했습니다.") from exc


def _assign(db: Session, model, key, role_id: int | None, updated_by: int | None):
    row = db.get(model, key)
    if role_id is None:                      # 해제 — 아래 층으로 되돌린다
        if row is not None:
            row.active = "N"
            row.updated_by_usr_seq = updated_by
        return
    role = db.get(AccessRole, role_id)
    if role is None or role.active != "Y":
        raise RoleError("없는 일괄권한입니다.")
    if row is None:
        fields = dict(zip(("office_id", "department_name"), key)) if isinstance(key, tuple) \
            else {"usr_seq": key}
        row = model(role_id=role_id, **fields)
        db.add(row)
    row.role_id = role_id
    row.active = "Y"
    row.updated_by_usr_seq = updated_by


def _dept_member_seqs(db: Session, office_id: str, department_name: str,
                      org: dict | None = None) -> list[int]:
    """이 (소속, 부서)에 속한 사람들의 usr_seq. locked_out_count 와 같은 방식."""
    from app.services.permissions import organization_preview  # noqa: PLC0415
    if org is None:
        org = organization_preview(db)
    seqs: list[int] = []
    for off in org.get("offices") or []:
        if str(off.get("id")) != str(office_id):
            continue
        for dep in off.get("departments") or []:
            if str(dep.get("name")) != str(department_name):
                continue
            for emp in dep.get("employees") or []:
                if emp.get("usr_seq"):
                    seqs.append(int(emp["usr_seq"]))
    return seqs


def _reset_dept_individuals(db: Session, office_id: str, department_name: str,
                            updated_by: int | None, org: dict | None = None) -> int:
    """부서 일괄권한 = **복사/덮어쓰기**(2026-08-18 사용자). 부서에 일괄권한을 걸면 그 부서
    사람들의 개인 일괄권한·개인 예외를 내려 **모두 부서값으로 리셋**한다. 개인이 나중에
    바꾸면 개인이 이기지만(개인>부서), 부서권한을 다시 걸면 다시 부서값으로 덮인다.
    되돌린 사람 수를 돌려준다(화면 문구용)."""
    from app.models.access_policy import AccessPolicy  # noqa: PLC0415
    try:
        seqs = _dept_member_seqs(db, office_id, department_name, org=org)
    except SQLAlchemyError:
        # 조직도 원본을 못 읽으면(표 미생성 등) 리셋을 건너뛴다 — locked_out_count 와
        # 같은 태도. 부서 배정 자체는 계속 진행한다.
        return 0
    reset: set[int] = set()
    for seq in seqs:
        ur = db.get(AccessUserRole, seq)
        if ur is not None and ur.active == "Y":
            ur.active = "N"
            ur.updated_by_usr_seq = updated_by
            reset.add(seq)
        ap = db.get(AccessPolicy, seq)
        if ap is not None and ap.active == "Y":
            ap.active = "N"
            reset.add(seq)
    return len(reset)


def assign_department(
    db: Session, *, office_id: str, department_name: str,
    role_id: int | None, updated_by_usr_seq: int | None,
    confirm_lockout: bool = False,
    org: dict | None = None,
) -> dict[str, Any]:
    """부서 하나에 일괄권한을 붙인다. role_id=None 이면 해제(코드 기본값으로 되돌림).

    org: 일괄 호출이 조직도 스냅샷을 재사용할 때 넘긴다(전사 스캔 1회로).
    """
    office = (office_id or "").strip()
    dept = (department_name or "").strip()
    if not office or not dept:
        raise RoleError("지사와 부서를 지정하세요.")
    # 권한 관리는 **부서 단위로 줄 수 없다** (2026-08-13 검수) — 예외: 본사 재무팀·
    # 전산정보팀(관리팀, 2026-08-18 사용자 지정). available_menu_keys 가 permissionManage
    # 를 전원에게 열어 두므로, 이 키를 담은 일괄권한을 (예외 아닌) 부서에 붙이면 그 부서
    # 사람 전부가 권한관리자가 되고, 부서 인원이 늘면 자동으로 따라 늘어난다.
    if role_id is not None and not _is_admin_dept(office, dept):
        role = db.get(AccessRole, role_id)
        if role is not None and "permissionManage" in _keys(role.menu_keys_json):
            raise RoleError(
                "'권한 관리' 가 들어 있는 일괄권한은 부서에 붙일 수 없습니다. "
                "그 부서 사람 전부가 권한관리자가 됩니다 — 개인에게 지정하세요."
            )
    # 멱등: 해제(role_id=None)는 이미 해제 상태면 아무것도 안 한다.
    # 그런데 부서 저장은 '이 부서를 이 일괄권한으로 통일' = **개인 설정을 부서값으로 되돌리는
    # 초기화**도 겸한다(2026-08-18 복사/덮어쓰기). 그래서 일괄권한이 그대로여도 되돌릴 개인
    # 설정이 남아 있으면 건너뛰면 안 된다 — 종전엔 같은 일괄권한 재적용을 무조건 skip 해서,
    # "3명만 바꿨는데 헷갈려 부서로 초기화" 가 막혔다(2026-08-19 사용자 신고). 되돌릴 것이
    # 하나도 없을 때만 skip 해, 같은 내용의 이력을 또 쌓아 감사 추적을 오염시키는 것을 막는다.
    was0 = db.get(AccessDeptRole, (office, dept))
    if role_id is None and (was0 is None or was0.active != "Y"):
        return {"office_id": office, "department_name": dept, "role_id": None,
                "skipped": True}
    same_role = (role_id is not None and was0 is not None and was0.active == "Y"
                 and int(was0.role_id) == int(role_id))
    before = permission_manager_holders(db, org=org)
    try:
        was = db.get(AccessDeptRole, (office, dept))
        prior = {"role_id": was.role_id, "active": was.active} if was is not None else None
        # 부서 일괄권한 = 복사/덮어쓰기 — 이 부서 사람들의 개인 일괄권한·예외를 내려 부서값
        # 으로 리셋한다(2026-08-18 사용자). 로크아웃 검사 **전**에 해서, 검사가 리셋 후의
        # 진짜 상태(전원 부서값)를 보게 한다. 실패하면 롤백이 리셋도 되돌린다.
        reset_count = (
            _reset_dept_individuals(db, office, dept, updated_by_usr_seq, org=org)
            if role_id is not None else 0
        )
        # 일괄권한도 그대로, 되돌릴 개인 설정도 없으면 진짜 no-op — 아무것도 쓰지 않고 빠진다.
        # rollback 을 한 번 해 준다: _reset_dept_individuals 는 읽기 실패를 삼키고 0 을
        # 돌려주는데(표 미생성 등), 그 삼킨 오류가 세션에 pending 으로 남으면 **일괄의
        # 다음 대상 commit 에 묻어 간다**(2026-08-17 실측한 사고 유형). 쓴 게 없으니
        # 정상 경로에선 rollback 이 무해한 no-op 이고, 오류가 남았으면 여기서 씻어낸다.
        if same_role and not reset_count:
            db.rollback()
            return {"office_id": office, "department_name": dept,
                    "role_id": role_id, "reset_count": 0, "skipped": True}
        if not same_role:
            _assign(db, AccessDeptRole, (office, dept), role_id, updated_by_usr_seq)
        db.flush()
        guard_permission_managers(db, before=before, action="이 부서의 일괄권한을 이렇게")
        # 메뉴 0개 = 로그인 거절이다. 확인 없이 부서 전원을 잠그면 안 된다.
        locked = locked_out_count(db, office_id=office, department_name=dept, org=org)
        if locked and not confirm_lockout:
            raise LockoutError(
                f"이 일괄권한을 붙이면 {dept} 소속 {locked}명이 프로그램에 들어올 수 "
                "없게 됩니다(메뉴 0개는 로그인 거절입니다). 정말 그렇게 하려면 "
                "확인을 눌러 주세요.", locked=locked,
            )
        # 담당자 **본인**이 이 저장으로 '권한 관리' 를 잃으면(자기잠금) 한 번 더 묻는다.
        # 전원 잠금(guard_permission_managers)이 아니어도, 본인이 이 화면을 못 쓰게
        # 되는 것은 되돌리기 어렵다 — 다른 담당자가 되살려 줘야 한다(2026-08-18 실측:
        # 원동하가 자기 부서 전산정보팀에 '집행부'(권한관리 없음)를 걸어 잠겼다).
        # 본인 1명만 계산해 전사 스캔을 피한다(managers 재계산은 일괄에서 비싸다).
        if (updated_by_usr_seq and updated_by_usr_seq in before
                and not confirm_lockout):
            from app.services.access_policy import load_access_policy  # noqa: PLC0415
            from app.services.permissions import _policy_target        # noqa: PLC0415
            try:
                _s, me = _policy_target(db, updated_by_usr_seq)
                keeps_pm = load_access_policy(db, me)["menu_permissions"].get(
                    "permissionManage")
            except Exception:      # noqa: BLE001 — 본인을 못 풀면 막지 않는다
                keeps_pm = True
            if not keeps_pm:
                raise LockoutError(
                    "이 저장으로 당신이 '권한 관리' 권한을 잃습니다 — 저장하면 이 "
                    "화면을 더는 열지 못할 수 있습니다(다른 담당자가 되돌려야 합니다). "
                    "정말 그렇게 하려면 확인을 눌러 주세요.", locked=1,
                )
        record(
            db, target_kind="dept_role", target_key=f"{office}|{dept}",
            target_label=f"{office} {dept}",
            action="assign" if role_id is not None else "unassign",
            # reset_count 를 남긴다 — 같은 일괄권한 재적용(before==after)이 '개인 N명 초기화'
            # 였는지 진짜 no-op 였는지 이력에서 구별되게 한다(감사 명료성, 2026-08-19 리뷰).
            before=prior, after={"role_id": role_id, "reset_count": reset_count},
            actor_usr_seq=updated_by_usr_seq,
        )
        db.commit()
    except LockoutError:
        # RoleError 의 하위가 아니라 아래 갈래에 안 걸렸다. 롤백을 빼먹으면
        # flush 된 배정이 세션에 남아, 일괄 루프의 **다음 대상 commit 에 묻어
        # 확인 없이·이력 없이 커밋됐다**(2026-08-17 적대 검증 실측). 응답은
        # '미적용'이라고 거짓말하는 최악의 조합이다.
        db.rollback()
        raise
    except RoleError:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise RoleError("부서 권한을 저장하지 못했습니다.") from exc
    return {"office_id": office, "department_name": dept, "role_id": role_id,
            "reset_count": reset_count}


def assign_user(
    db: Session, *, usr_seq: int, role_id: int | None, updated_by_usr_seq: int | None,
    visible_office_id: str | None = None,
    confirm_lockout: bool = False,
) -> dict[str, Any]:
    """사람 하나에 일괄권한을 붙인다. **부서 일괄권한을 이긴다.**

    visible_office_id 가 있으면(=지사 관리자) 그 지사 사람만 바꿀 수 있다.
    """
    # 자기 권한은 자기가 바꿀 수 있다(2026-08-19 사용자 — 관리자 1명 지사는 자기가
    # 관리해야 한다). 단 자기 '권한 관리'는 스스로 못 뗀다(자기잠금) — 배정 후 아래
    # try 안에서 본인이 권한관리를 유지하는지 확인한다.
    if visible_office_id is not None:
        from app.services.permissions import _policy_target  # noqa: PLC0415
        try:
            _source, identity = _policy_target(db, int(usr_seq))
        except Exception as exc:      # noqa: BLE001 — 대상을 못 찾으면 막는 쪽
            raise RoleError("대상 사용자를 찾을 수 없습니다.") from exc
        if identity.office_id != visible_office_id:
            raise RoleError("다른 지사 사용자의 권한은 바꿀 수 없습니다.")
    # 같은 값이면 no-op — 재전송·중복 클릭이 같은 이력을 또 쌓지 않게(멱등).
    was0 = db.get(AccessUserRole, int(usr_seq))
    if role_id is None:
        if was0 is None or was0.active != "Y":
            return {"usr_seq": int(usr_seq), "role_id": None, "skipped": True}
    elif was0 is not None and was0.active == "Y" and int(was0.role_id) == int(role_id):
        return {"usr_seq": int(usr_seq), "role_id": role_id, "skipped": True}
    # 메뉴 0개는 빈 화면이 아니라 **로그인 거절**이다. 부서 경로에는 이 확인이
    # 있었는데 개인 경로에는 없어서, 지사 사람에게 본사 전용만 든 일괄권한을 붙이면
    # 조용히 잠겼다(2026-08-17). 막지는 않는다 — 한 번 묻고, 확인하면 그대로 한다.
    #
    # ★ 이 검사는 반드시 아래 try(=쓰기) **앞**에 둔다. 그래야 거절할 때 세션에
    #   더럽힌 것이 없어 되돌릴 것도 없다. 뒤로 옮기면 flush 된 행이 남아, 일괄에서
    #   **다음 대상의 commit 에 묻어 들어간다** — 부서 경로에서 실제로 났던 사고다
    #   (LockoutError 는 RoleError 가 아니라 except RoleError 를 그냥 지나쳤다).
    #   그 성질은 test_거절된_사람은_다음_사람의_commit_에_묻어가지_않는다 가 지킨다.
    if not confirm_lockout and locks_out_user(db, int(usr_seq), role_id):
        raise LockoutError(
            "이 일괄권한을 붙이면 이 사람은 프로그램에 들어올 수 없게 됩니다"
            "(메뉴 0개는 로그인 거절입니다). 지사 사람에게 본사 전용 메뉴만 든"
            " 일괄권한을 붙이면 이렇게 됩니다. 그래도 적용하려면 확인을 눌러 주세요.",
            locked=1,
        )
    before = permission_manager_holders(db)
    try:
        was = db.get(AccessUserRole, int(usr_seq))
        prior = {"role_id": was.role_id, "active": was.active} if was is not None else None
        _assign(db, AccessUserRole, int(usr_seq), role_id, updated_by_usr_seq)
        db.flush()
        guard_permission_managers(db, before=before, action="이 사람의 일괄권한을 이렇게")
        # 자기 권한관리는 스스로 못 뗀다 — 이 배정으로 본인이 잃으면 막는다(2026-08-19).
        if updated_by_usr_seq and int(updated_by_usr_seq) == int(usr_seq):
            from app.services.access_policy import load_access_policy  # noqa: PLC0415
            from app.services.permissions import _policy_target        # noqa: PLC0415
            try:
                _s, me = _policy_target(db, int(usr_seq))
                keeps = load_access_policy(db, me)["menu_permissions"].get("permissionManage")
            except Exception:      # noqa: BLE001 — 본인을 못 풀면 막지 않는다
                keeps = True
            if not keeps:
                raise RoleError(
                    "자기 '권한 관리' 권한은 스스로 뗄 수 없습니다. "
                    "다른 권한관리자나 본사에 요청하세요."
                )
        record(
            db, target_kind="user_role", target_key=int(usr_seq),
            action="assign" if role_id is not None else "unassign",
            before=prior, after={"role_id": role_id},
            actor_usr_seq=updated_by_usr_seq,
        )
        db.commit()
    except RoleError:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise RoleError("개인 권한을 저장하지 못했습니다.") from exc
    return {"usr_seq": int(usr_seq), "role_id": role_id}


def department_assignments(db: Session, *, office_id: str | None = None) -> list[dict[str, Any]]:
    """부서 → 일괄권한 목록. 화면이 '어느 부서에 무엇이 붙어 있나'를 그린다."""
    try:
        stmt = select(AccessDeptRole).where(AccessDeptRole.active == "Y")
        if office_id:
            stmt = stmt.where(AccessDeptRole.office_id == office_id)
        rows = db.scalars(stmt).all()
        names = {
            r.role_id: r.name
            for r in db.scalars(select(AccessRole).where(AccessRole.active == "Y")).all()
        }
    except SQLAlchemyError:
        db.rollback()
        return []
    return [
        {
            "office_id": row.office_id,
            "department_name": row.department_name,
            "role_id": row.role_id,
            "role_name": names.get(row.role_id),
        }
        for row in rows
    ]


def all_user_assignments(db: Session) -> list[dict[str, Any]]:
    """살아 있는 개인 → 일괄권한 전부. 일괄 적용 화면이 '지금 누가 이 세트를 쓰나'를
    미리 체크해 보여 줄 때 쓴다. 표가 없으면 빈 목록 — 화면은 죽지 않는다."""
    try:
        rows = db.scalars(
            select(AccessUserRole).where(AccessUserRole.active == "Y")
        ).all()
    except SQLAlchemyError:
        db.rollback()
        return []
    return [{"usr_seq": int(r.usr_seq), "role_id": int(r.role_id)} for r in rows]


def personal_override_usr_seqs(db: Session) -> list[int]:
    """**개인 예외**(a10_access_policy)가 실제로 걸린 사람들.

    부서 일괄권한을 바꾸면 그 부서 사람들은 자동으로 따라오는데, 개인 예외가 있는
    사람은 그 예외가 위에 얹혀서 결과가 달라진다. 화면이 '이 사람은 부서를
    따라가지 않는다'를 표시할 수 있어야 한다(2026-08-17 인사이동 질문).

    행이 있다고 다 예외는 아니다 — 세 칸이 모두 비면 아무것도 안 바꾸는 빈 행이라
    세지 않는다. 빈 행까지 세면 '예외 있음' 표가 의미를 잃는다.
    """
    from app.models.access_policy import AccessPolicy   # noqa: PLC0415

    try:
        rows = db.scalars(
            select(AccessPolicy).where(AccessPolicy.active == "Y")
        ).all()
    except SQLAlchemyError:
        db.rollback()
        return []
    out = []
    for row in rows:
        try:
            menus = json.loads(row.menu_overrides_json) if row.menu_overrides_json else {}
        except (TypeError, ValueError):
            menus = {}
        if menus or row.view_all_offices_override or row.view_other_users_override:
            out.append(int(row.usr_seq))
    return out


def user_assignments(db: Session, usr_seqs: list[int]) -> dict[int, dict[str, Any]]:
    """사람 → 일괄권한. 권한관리 화면이 목록에 '일괄권한' 칸을 그릴 때 쓴다."""
    if not usr_seqs:
        return {}
    try:
        rows = db.scalars(
            select(AccessUserRole).where(
                AccessUserRole.usr_seq.in_(usr_seqs), AccessUserRole.active == "Y"
            )
        ).all()
        names = {
            r.role_id: r.name
            for r in db.scalars(select(AccessRole).where(AccessRole.active == "Y")).all()
        }
    except SQLAlchemyError:
        db.rollback()
        return {}
    return {
        int(row.usr_seq): {"role_id": row.role_id, "role_name": names.get(row.role_id)}
        for row in rows
    }
