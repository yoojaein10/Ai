# -*- coding: utf-8 -*-
"""연결 후 대상/역할/권한 검증 평가 (지시 §4 사후, §9).

- 순수 평가 함수: 조회 행을 입력받아 (ok, 실패사유) 반환. 원문 식별값은 노출하지 않는다.
- 쓰기·EXECUTE 권한, 과도한 역할, NULL/예상 밖 타입, 확인 불가, 필요한 SELECT/
  VIEW DEFINITION 부족이면 실패로 처리(실 DB 조회 전체 중단 신호).
- 권한 검사는 보조 방어이며 읽기 전용 전용계정을 대체하지 않는다.

행 컬럼 순서는 ro_query 의 등록 SELECT 와 1:1 대응한다.
"""
from __future__ import annotations

# VERIFY_TARGET 컬럼 인덱스
_T_DB_NAME, _T_SERVER, _T_INSTANCE, _T_LOGIN, _T_DBUSER, _T_ORIGLOGIN = range(6)

# VERIFY_ROLES 컬럼 인덱스
_ROLE_NAMES = ("is_sysadmin", "is_db_owner", "is_db_datawriter",
               "is_db_ddladmin", "is_db_securityadmin", "is_db_datareader")
_EXCESSIVE_ROLES = frozenset({"is_sysadmin", "is_db_owner", "is_db_datawriter",
                              "is_db_ddladmin", "is_db_securityadmin"})

# VERIFY_PERMISSIONS 컬럼 인덱스/의미
_PERM_NAMES = ("srv_control", "srv_alter_login", "db_insert", "db_update",
               "db_delete", "db_execute", "db_alter", "db_control",
               "db_take_ownership", "db_view_def", "db_select")
_WRITE_PERMS = frozenset({"srv_control", "srv_alter_login", "db_insert", "db_update",
                          "db_delete", "db_execute", "db_alter", "db_control",
                          "db_take_ownership"})
_REQUIRED_READ_PERMS = ("db_view_def", "db_select")


class _Undetermined:
    pass


def _as_flag(v):
    """1/0 → True/False. NULL/예상 밖 타입 → _Undetermined."""
    if v is None:
        return _Undetermined
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        return v != 0
    return _Undetermined


def evaluate_target(row, allowlist) -> tuple[bool, list[str]]:
    """VERIFY_TARGET 행을 server_identities/databases 와 정확 일치 검증.

    반환 (ok, reasons). 원문 서버/DB 값은 reasons 에 넣지 않는다.
    """
    if row is None:
        return False, ["대상 검증 결과 없음"]
    try:
        db_name = (row[_T_DB_NAME] or "").strip()
        server_name = (row[_T_SERVER] or "").strip()
    except (IndexError, TypeError):
        return False, ["대상 검증 행 형식 오류"]
    reasons = []
    if not allowlist.server_identity_ok(server_name):
        reasons.append("서버 식별값 allowlist 불일치")
    if not allowlist.database_ok(db_name):
        reasons.append("DB명 allowlist 불일치")
    return (not reasons), reasons


def evaluate_roles(row) -> tuple[bool, list[str]]:
    """VERIFY_ROLES 행 평가. 과도한 역할/NULL/타입오류면 실패."""
    if row is None:
        return False, ["역할 검증 결과 없음"]
    reasons = []
    for i, name in enumerate(_ROLE_NAMES):
        try:
            flag = _as_flag(row[i])
        except IndexError:
            return False, ["역할 검증 행 형식 오류"]
        if flag is _Undetermined:
            reasons.append(f"역할 확인 불가/타입오류: {name}")
            continue
        if name in _EXCESSIVE_ROLES and flag:
            reasons.append(f"과도한 역할 보유: {name}")
    return (not reasons), reasons


def evaluate_permissions(row) -> tuple[bool, list[str]]:
    """VERIFY_PERMISSIONS 행 평가. 쓰기/EXECUTE/상승 권한, NULL, 필요한 읽기권한
    부족이면 실패."""
    if row is None:
        return False, ["권한 검증 결과 없음"]
    reasons = []
    flags = {}
    for i, name in enumerate(_PERM_NAMES):
        try:
            flag = _as_flag(row[i])
        except IndexError:
            return False, ["권한 검증 행 형식 오류"]
        if flag is _Undetermined:
            reasons.append(f"권한 확인 불가/타입오류: {name}")
            continue
        flags[name] = flag
        if name in _WRITE_PERMS and flag:
            reasons.append(f"쓰기/상승 권한 보유: {name}")
    for name in _REQUIRED_READ_PERMS:
        if flags.get(name) is not True:
            reasons.append(f"필요한 읽기 권한 부족: {name}")
    return (not reasons), reasons


def evaluate_gate(target_row, roles_row, perms_row, allowlist) -> dict:
    """세 검증을 종합. 하나라도 실패하면 gate_open=False(실 DB 조회 차단)."""
    t_ok, t_r = evaluate_target(target_row, allowlist)
    r_ok, r_r = evaluate_roles(roles_row)
    p_ok, p_r = evaluate_permissions(perms_row)
    reasons = []
    for label, ok, rs in (("target", t_ok, t_r), ("roles", r_ok, r_r),
                          ("permissions", p_ok, p_r)):
        for rr in rs:
            reasons.append(f"{label}: {rr}")
    return {
        "gate_open": t_ok and r_ok and p_ok,
        "target_ok": t_ok,
        "roles_ok": r_ok,
        "permissions_ok": p_ok,
        "reasons": reasons,
    }
