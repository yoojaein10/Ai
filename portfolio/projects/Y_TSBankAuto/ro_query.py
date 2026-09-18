# -*- coding: utf-8 -*-
"""고정 쿼리 레지스트리 및 안전 실행 계층 (읽기 전용 검증 단계; 지시 §8).

핵심 원칙:
- 외부 SQL 을 받는 범용 실행기를 만들지 않는다.
- 코드에 고정된 작업 ID 만 허용한다. schema/테이블/컬럼/ORDER BY/연산자/SQL fragment 를
  런타임 입력으로 받지 않는다.
- 실행 계층은 (작업 ID, 바인딩 값) 만 받는다. 모든 사용자값은 `?` 로 바인딩한다.
- 설정문(SET)과 조회문(SELECT)을 한 문자열로 조합하지 않는다.
- LIKE 는 명시적 ESCAPE 절을 쓰고 Python escape 문자와 SQL ESCAPE 문자를 일치시킨다.
- 미등록 작업은 기본 거부한다(정규식/키워드 검사는 보조 방어).

이 모듈은 DB 에 연결하지 않는다. 순수 상수/함수만 제공한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# 고정 대상 (allowlist 상수) ─ 런타임 입력 아님
SP_SCHEMA = "dbo"
SP_OBJECT = "SP_I_APW_TS_Master"
REGHIST_TABLE = "dbo.APW_RegHist"
CUSTOMER_TABLE = "dbo.APW_Customer"
CUSTOMER_OFFICE = "10"           # 참조 프로젝트 고정 필터 (config.SP_OFFICE 와 동일)

# 결정적 상한 (코드 상수 — 사용자 입력 아님)
REGHIST_TOP = 5
CUSTOMER_TOP = 20

# LIKE ESCAPE 문자. SQL 의 ESCAPE 절과 정확히 일치해야 한다.
LIKE_ESCAPE_CHAR = "\\"


class UnregisteredOperation(Exception):
    """등록되지 않은 작업 ID 또는 미허용 SQL (기본 거부)."""


class QueryContract(Exception):
    """등록 SQL 이 안전 계약(단일 SELECT/바인딩 개수 등)을 위반."""


# ───────────────────────────── LIKE 이스케이프 ─────────────────────────────
_LIKE_SPECIAL = ("\\", "%", "_", "[")


def escape_like(text: str) -> str:
    """LIKE 특수문자(%, _, [, 이스케이프문자)를 LIKE_ESCAPE_CHAR 로 이스케이프."""
    out = []
    for ch in text or "":
        if ch in _LIKE_SPECIAL:
            out.append(LIKE_ESCAPE_CHAR + ch)
        else:
            out.append(ch)
    return "".join(out)


def like_prefix(text: str) -> str:
    """접두 매칭 패턴: '<escaped>%'."""
    return escape_like(text) + "%"


def like_contains(text: str) -> str:
    """포함 매칭 패턴: '%<escaped>%'."""
    return "%" + escape_like(text) + "%"


# ───────────────────────────── 세션 설정문 (고정) ─────────────────────────────
# 조회문과 절대 결합하지 않는다. 각각 별도 cursor.execute 로 실행한다.
STMT_ISOLATION = "SET TRANSACTION ISOLATION LEVEL READ COMMITTED"
LOCK_TIMEOUT_MS = 3000                     # 수 초 이내 코드 상수
STMT_LOCK_TIMEOUT = f"SET LOCK_TIMEOUT {LOCK_TIMEOUT_MS}"   # 정수 상수만, 바인딩 아님
SESSION_SETUP_STATEMENTS = (STMT_ISOLATION, STMT_LOCK_TIMEOUT)


# ───────────────────────────── 등록 작업 ─────────────────────────────
@dataclass(frozen=True)
class RegisteredQuery:
    op_id: str
    sql: str
    param_count: int
    max_rows: int          # fetchmany 상한


# 대상/권한 검증
_VERIFY_TARGET = (
    "SELECT "
    "DB_NAME() AS db_name, "
    "CAST(SERVERPROPERTY('ServerName') AS nvarchar(256)) AS server_name, "
    "CAST(SERVERPROPERTY('InstanceName') AS nvarchar(256)) AS instance_name, "
    "SUSER_SNAME() AS login_name, "
    "USER_NAME() AS db_user, "
    "ORIGINAL_LOGIN() AS original_login"
)

_VERIFY_ROLES = (
    "SELECT "
    "IS_SRVROLEMEMBER('sysadmin') AS is_sysadmin, "
    "IS_ROLEMEMBER('db_owner') AS is_db_owner, "
    "IS_ROLEMEMBER('db_datawriter') AS is_db_datawriter, "
    "IS_ROLEMEMBER('db_ddladmin') AS is_db_ddladmin, "
    "IS_ROLEMEMBER('db_securityadmin') AS is_db_securityadmin, "
    "IS_ROLEMEMBER('db_datareader') AS is_db_datareader"
)

# 유효 권한(직접+상속). 권한명은 문자열 리터럴이며 statement 키워드가 아니다.
_VERIFY_PERMISSIONS = (
    "SELECT "
    "HAS_PERMS_BY_NAME(NULL, NULL, 'CONTROL SERVER') AS srv_control, "
    "HAS_PERMS_BY_NAME(NULL, NULL, 'ALTER ANY LOGIN') AS srv_alter_login, "
    "HAS_PERMS_BY_NAME(DB_NAME(), 'DATABASE', 'INSERT') AS db_insert, "
    "HAS_PERMS_BY_NAME(DB_NAME(), 'DATABASE', 'UPDATE') AS db_update, "
    "HAS_PERMS_BY_NAME(DB_NAME(), 'DATABASE', 'DELETE') AS db_delete, "
    "HAS_PERMS_BY_NAME(DB_NAME(), 'DATABASE', 'EXECUTE') AS db_execute, "
    "HAS_PERMS_BY_NAME(DB_NAME(), 'DATABASE', 'ALTER') AS db_alter, "
    "HAS_PERMS_BY_NAME(DB_NAME(), 'DATABASE', 'CONTROL') AS db_control, "
    "HAS_PERMS_BY_NAME(DB_NAME(), 'DATABASE', 'TAKE OWNERSHIP') AS db_take_ownership, "
    "HAS_PERMS_BY_NAME(DB_NAME(), 'DATABASE', 'VIEW DEFINITION') AS db_view_def, "
    "HAS_PERMS_BY_NAME(DB_NAME(), 'DATABASE', 'SELECT') AS db_select"
)

# SP 파라미터 메타데이터 (sys 카탈로그). schema/object 는 바인딩.
_READ_SP_METADATA = (
    "SELECT "
    "p.parameter_id AS parameter_id, "
    "p.name AS param_name, "
    "p.is_output AS is_output, "
    "ty.name AS type_name, "
    "ty.is_user_defined AS is_user_defined, "
    "bt.name AS base_type_name, "
    "p.max_length AS max_length, "
    "p.precision AS precision, "
    "p.scale AS scale "
    "FROM sys.objects o "
    "JOIN sys.schemas s ON s.schema_id = o.schema_id "
    "JOIN sys.parameters p ON p.object_id = o.object_id "
    "JOIN sys.types ty ON ty.user_type_id = p.user_type_id "
    "LEFT JOIN sys.types bt ON bt.user_type_id = ty.system_type_id "
    "AND bt.user_type_id = bt.system_type_id "
    "WHERE s.name = ? AND o.name = ? AND o.type IN ('P', 'PC') "
    "ORDER BY p.parameter_id"
)

# APW_RegHist 제한 조회 (고정 컬럼/테이블, 결정적 TOP+ORDER BY, ESCAPE)
_LOOKUP_REGHIST = (
    f"SELECT TOP {REGHIST_TOP} REG, EUB, NAME, AS1, AS2, AS3, AS4 "
    f"FROM {REGHIST_TABLE} "
    "WHERE FUSE = '1' "
    f"AND AS1 LIKE ? ESCAPE '{LIKE_ESCAPE_CHAR}' "
    f"AND AS2 LIKE ? ESCAPE '{LIKE_ESCAPE_CHAR}' "
    "ORDER BY AS1, AS2, AS3, AS4, REG"
)

# APW_Customer 제한 조회 (고정 컬럼/테이블/Office, 결정적 TOP+ORDER BY, ESCAPE)
_LOOKUP_CUSTOMER = (
    f"SELECT TOP {CUSTOMER_TOP} CustID, CustName, Active "
    f"FROM {CUSTOMER_TABLE} "
    f"WHERE Office = '{CUSTOMER_OFFICE}' "
    f"AND CustName LIKE ? ESCAPE '{LIKE_ESCAPE_CHAR}' "
    f"AND CustName LIKE ? ESCAPE '{LIKE_ESCAPE_CHAR}' "
    "ORDER BY Active DESC, LEN(CustName), CustName, CustID"
)

_LOOKUP_CUSTOMER_EXACT = (
    f"SELECT TOP {CUSTOMER_TOP} CustID, CustName, Active "
    f"FROM {CUSTOMER_TABLE} "
    f"WHERE Office = '{CUSTOMER_OFFICE}' "
    "AND CustName = ? "
    "ORDER BY Active DESC, CustName, CustID"
)

# APW_Customer_Manager 담당자 조회 (고정 컬럼/테이블/Office, CustID 바인딩, 결정적 TOP+ORDER)
# 퇴사자 담당자는 TMWCMN_USR_BAC_INFO(USR_SEQ) 조인으로 제외 → 재직 담당자만 카운트한다.
# 실측(apworksdw): RTRM_FL 은 char(1) NOT NULL, 값은 '0'(재직)/'1'(퇴사) 뿐 → <>'1' ≡ ='0'.
# LEFT JOIN + (u.RTRM_FL IS NULL) 로 직원 마스터에 없는 Manager 코드(미매칭)는 재직으로 남긴다.
# 저장쪽은 '재직 담당자가 정확히 1명이고 제외대상'일 때만 저장을 건너뛰므로, 담당자 수를
# 과소집계하면 무고한 저장 제외가 생긴다 → 확실히 퇴사('1')한 건만 빼는 게 fail-open(저장 우선).
MANAGER_TABLE = "dbo.APW_Customer_Manager"
MANAGER_USER_TABLE = "dbo.TMWCMN_USR_BAC_INFO"   # 직원 마스터(재직/퇴사 플래그). 실측 dbo 확인됨
MANAGER_OFFICE = CUSTOMER_OFFICE          # 참조 프로젝트 고정 필터('10')
MANAGER_TOP = 20
_LOOKUP_MANAGER = (
    f"SELECT TOP {MANAGER_TOP} m.Manager "
    f"FROM {MANAGER_TABLE} m "
    f"LEFT JOIN {MANAGER_USER_TABLE} u ON m.Manager = u.USR_SEQ "
    f"WHERE m.Office = '{MANAGER_OFFICE}' "
    "AND m.CustID = ? "
    "AND (u.RTRM_FL <> '1' OR u.RTRM_FL IS NULL) "
    "ORDER BY m.Manager"
)


_REGISTRY: dict[str, RegisteredQuery] = {
    q.op_id: q
    for q in (
        RegisteredQuery("VERIFY_TARGET", _VERIFY_TARGET, 0, 1),
        RegisteredQuery("VERIFY_ROLES", _VERIFY_ROLES, 0, 1),
        RegisteredQuery("VERIFY_PERMISSIONS", _VERIFY_PERMISSIONS, 0, 1),
        RegisteredQuery("READ_SP_METADATA", _READ_SP_METADATA, 2, 500),
        RegisteredQuery("LOOKUP_REGHIST", _LOOKUP_REGHIST, 2, REGHIST_TOP),
        RegisteredQuery("LOOKUP_CUSTOMER", _LOOKUP_CUSTOMER, 2, CUSTOMER_TOP),
        RegisteredQuery("LOOKUP_CUSTOMER_EXACT", _LOOKUP_CUSTOMER_EXACT, 1, CUSTOMER_TOP),
        RegisteredQuery("LOOKUP_MANAGER", _LOOKUP_MANAGER, 1, MANAGER_TOP),
    )
}

ALLOWED_OP_IDS = frozenset(_REGISTRY)


# ───────────────────────────── 보조 안전 검사 (defense-in-depth) ─────────────
# statement 키워드(문자열 리터럴 밖)만 잡기 위해 먼저 '...' 리터럴을 제거한다.
_STRLIT_RE = re.compile(r"'[^']*'")
_FORBIDDEN_KW_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|CREATE|ALTER|TRUNCATE|GRANT|REVOKE|"
    r"EXEC|EXECUTE|OPENROWSET|OPENDATASOURCE|BULK|XP_CMDSHELL)\b",
    re.IGNORECASE,
)
_INTO_RE = re.compile(r"\bINTO\b", re.IGNORECASE)


def _strip_literals(sql: str) -> str:
    return _STRLIT_RE.sub("''", sql)


def assert_safe_sql(sql: str, *, kind: str = "select") -> None:
    """등록 SQL 이 안전 계약을 만족하는지 검사. 위반 시 QueryContract.

    kind='select' : 단일 SELECT/WITH. kind='set' : 고정 SET 문.
    """
    if not sql or not sql.strip():
        raise QueryContract("빈 SQL")
    if ";" in sql:
        raise QueryContract("세미콜론 금지(다중 statement 방지)")
    stripped = _strip_literals(sql)
    if kind == "set":
        if not re.match(r"^\s*SET\s+(TRANSACTION ISOLATION LEVEL|LOCK_TIMEOUT)\b",
                        stripped, re.IGNORECASE):
            raise QueryContract("허용되지 않은 SET 문")
        return
    if not re.match(r"^\s*(SELECT|WITH)\b", stripped, re.IGNORECASE):
        raise QueryContract("SELECT/WITH 로 시작하지 않음")
    m = _FORBIDDEN_KW_RE.search(stripped)
    if m:
        raise QueryContract(f"금지 키워드: {m.group(1).upper()}")
    if _INTO_RE.search(stripped):
        raise QueryContract("INTO 금지(SELECT INTO 방지)")


def validate_registry() -> None:
    """모든 등록 항목과 세션 설정문이 안전 계약을 만족하는지 시작 시 1회 검사."""
    for stmt in SESSION_SETUP_STATEMENTS:
        assert_safe_sql(stmt, kind="set")
    for q in _REGISTRY.values():
        assert_safe_sql(q.sql, kind="select")
        expected = q.sql.count("?")
        if expected != q.param_count:
            raise QueryContract(f"{q.op_id}: ? 개수({expected}) != param_count({q.param_count})")


def get_registered(op_id: str) -> RegisteredQuery:
    """등록 작업 조회. 미등록이면 UnregisteredOperation (기본 거부)."""
    try:
        return _REGISTRY[op_id]
    except KeyError:
        raise UnregisteredOperation(f"미등록 작업 ID: {op_id!r}")


# 시작 시 계약 검증(모듈 로드 시 1회). 위반이면 import 자체가 실패한다.
validate_registry()


# ───────────────────────────── 실행기 ─────────────────────────────
def execute_registered(cur, op_id: str, params=()) -> list:
    """등록 작업만 실행. (op_id, 바인딩 값) 만 받는다. fetchmany 로 상한까지만 읽는다.

    - 미등록 op_id → UnregisteredOperation
    - 등록 SQL 이 계약 위반 → QueryContract
    - 바인딩 개수 불일치 → QueryContract
    반환: 행 리스트(상한 max_rows). 원문 처리·마스킹은 상위 계층 책임.
    """
    q = get_registered(op_id)
    assert_safe_sql(q.sql, kind="select")
    params = list(params)
    if len(params) != q.param_count:
        raise QueryContract(
            f"{op_id}: 바인딩 개수({len(params)}) != 필요({q.param_count})")
    cur.execute(q.sql, params)
    return cur.fetchmany(q.max_rows)


def apply_readonly_session(cur) -> None:
    """세션 설정문(격리수준/락 타임아웃)을 각각 별도 실행. 조회문과 결합하지 않는다."""
    for stmt in SESSION_SETUP_STATEMENTS:
        assert_safe_sql(stmt, kind="set")
        cur.execute(stmt)
