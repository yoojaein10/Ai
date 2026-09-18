# -*- coding: utf-8 -*-
"""SP_I_APW_TS_Master 실행/커밋 래퍼 (쓰기 실행 모듈).

★ SP 정의는 분석 보고서 기반 PROVISIONAL 이다. 실SP 호출 전 반드시 DB 메타데이터로
  파라미터 개수/이름/타입/길이/기본값을 검증해야 한다(SP_DEFINITION_SOURCE 참조).
  메타데이터 미검증 상태에서는 실제 쓰기를 차단한다.

이번 작업에서는:
- 실제 DB 연결/SP 호출/INSERT/UPDATE/DELETE/COMMIT 을 하지 않는다.
- fake connection/fake cursor 로 placeholder 개수·순서·OUTPUT nextset 만 검증한다.

값 바인딩: 모든 입력은 pyodbc `?` 로 바인딩한다. 데이터 값을 SQL 에 문자열로 삽입하지 않는다.

파라미터 스펙·빌더는 sp_spec 으로 분리되어 있다(미리보기/파싱 경로가 실행 코드를
끌어들이지 않도록; 지시 §13). 하위호환을 위해 여기서 재export 한다.
"""
from __future__ import annotations

from dataclasses import dataclass

import config
import security  # noqa: F401  (하위호환 재export 사용처 대비)
# 스펙/빌더는 실행 코드 없는 sp_spec 에서 재export (import 단위 분리)
from sp_spec import (  # noqa: F401
    INPUT_PARAM_NAMES,
    INPUT_PARAM_SPECS,
    EXEC_BIND_PARAM_NAMES,
    OUTPUT_PARAM_SPECS,
    REGHIST_NOT_QUERIED,
    SP_DEFINITION_SOURCE,
    SP_NAME,
    ParamSpec,
    build_sp_params,
    build_wrapper_sql,
    count_placeholders,
    params_in_order,
)

GUI_COMMIT_PHRASE = "실서버 저장"


class SpWriteBlocked(Exception):
    """실쓰기 차단(가드 미통과/메타데이터 미검증)."""


# ───────────────────────────── OUTPUT 수신 + nextset 소진 ─────────────────────────────
def fetch_output_and_drain(cur) -> dict | None:
    """SP 실행 후 OUTPUT SELECT(NewMasterID/NewSEQ) 를 찾고 모든 결과셋을 소진."""
    output_cols = {"NewMasterID", "NewSEQ"}
    output = None
    while True:
        try:
            desc = cur.description
        except Exception:
            desc = None
        if desc is not None:
            names = {d[0] for d in desc}
            if output_cols.issubset(names) and output is None:
                row = cur.fetchone()
                if row is not None:
                    output = {"NewMasterID": row[0], "NewSEQ": row[1]}
                _drain_rows(cur)
            else:
                _drain_rows(cur)
        try:
            if not cur.nextset():
                break
        except Exception:
            break
    return output


def _drain_rows(cur) -> None:
    try:
        cur.fetchall()
    except Exception:
        try:
            while cur.fetchone() is not None:
                pass
        except Exception:
            pass


# ───────────────────────────── 접속 문자열 (마스킹) ─────────────────────────────
# ODBC 드라이버 선호 순위(신→구). 설정값이 미설치면 이 중 설치된 첫 번째로 대체한다.
# 레거시 "SQL Server"(DBNETLIB)는 Encrypt/TrustServerCertificate 미지원 + 최신 SQL Server TLS
# 불가(SSL 보안 오류)라 자동 대체 대상에서 제외한다 — 없으면 명확한 IM002(드라이버 미설치)로
# 실패시켜 대상 PC 에 Driver 17/18 설치를 유도한다.
_DRIVER_PREFERENCE = (
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
    "ODBC Driver 13 for SQL Server",
    "SQL Server Native Client 11.0",
)


def resolve_odbc_driver(preferred: str) -> str:
    """설치된 ODBC 드라이버 중 사용할 것을 고른다.

    설정값(preferred)이 설치돼 있으면 그대로 사용한다. 없으면 _DRIVER_PREFERENCE 순서로
    설치된 첫 번째를 쓴다(대상 PC 에 Driver 18 이 없고 17 만 있는 경우 대응). pyodbc 조회가
    불가하면 preferred 를 그대로 반환한다(동작 변화 최소화). 드라이버명은 시크릿이 아니다.
    """
    try:
        import pyodbc
        installed = set(pyodbc.drivers())
    except Exception:
        return preferred
    if preferred in installed:
        return preferred
    for cand in _DRIVER_PREFERENCE:
        if cand in installed:
            return cand
    return preferred


def build_connection_string(db: "config.DbConfig", user: str, pwd: str,
                            encrypt: str = None) -> str:
    """ODBC 접속 문자열 생성. Encrypt/TrustServerCertificate 기본 보안값 적용.

    - 설정 드라이버가 대상 PC 에 미설치면 설치된 드라이버로 자동 대체한다.
    - encrypt 인자가 주어지면 그 값을 강제(연결 폴백용). None 이면 설정값, 그것도 없으면
      키를 넣지 않아 드라이버 기본값을 따른다(Driver 17=no, Driver 18=yes).
    반환값은 시크릿을 포함하므로 로그에 남기지 않는다(호출부 책임).
    """
    parts = db.odbc_parts_nonsecret()   # 설정 encrypt 가 있으면 이미 Encrypt 포함
    parts["DRIVER"] = "{%s}" % resolve_odbc_driver(db.driver)
    if encrypt is not None:
        parts["Encrypt"] = encrypt
    ordered = [f"{k}={v}" for k, v in parts.items()]
    ordered.append(f"UID={user}")
    ordered.append(f"PWD={pwd}")
    return ";".join(ordered) + ";"


# ───────────────────────────── 실행 (fake/real 공통) ─────────────────────────────
def execute_sp(conn, params: dict, *, rollback_test: bool = True) -> dict:
    """SP 래퍼 실행 → OUTPUT 수신. 기본 rollback_test=True 면 항상 롤백.

    이 함수는 COMMIT 을 절대 하지 않는다. 실제 COMMIT 은 commit_with_guards 경로에서만.
    """
    sql = build_wrapper_sql()
    values = params_in_order(params)
    cur = conn.cursor()
    cur.execute(sql, values)
    output = fetch_output_and_drain(cur)
    # 기본: 항상 롤백 (S7)
    try:
        conn.rollback()
    except Exception:
        pass
    return {
        "output": output,
        "rolled_back": True,
        "committed": False,
        "placeholder_count": count_placeholders(sql),
        "rollback_test": rollback_test,
    }


# ───────────────────────────── COMMIT 가드 (S7) ─────────────────────────────
@dataclass
class CommitContext:
    rollback_test: bool
    env_allow_commit: bool          # config.commit_env_ok()
    gui_phrase: str                 # 사용자가 GUI 에 직접 입력한 문구
    server: str
    database: str
    allowlist: "config.Allowlist"
    target_count: int
    target_count_confirmed: bool
    dup_check_passed: bool          # 실행 내 중복 검사
    audit_log_pii_free: bool
    metadata_verified: bool         # SP 메타데이터 검증 완료 여부


def check_commit_guards(ctx: CommitContext) -> tuple[bool, list[str]]:
    """모든 COMMIT 조건을 검사. 하나라도 실패하면 (False, 실패목록).

    CLI 플래그 하나만으로 COMMIT 하지 않는다(다중 독립 가드).
    """
    failures = []
    if ctx.rollback_test:
        failures.append("rollback_test 가 false 가 아님")
    if not ctx.env_allow_commit:
        failures.append(f"환경변수 {config.ENV_ALLOW_COMMIT} 매직값 불일치")
    if ctx.gui_phrase != GUI_COMMIT_PHRASE:
        failures.append("GUI 확인 문구('실서버 저장') 미입력")
    if not ctx.server or not ctx.database:
        failures.append("서버/DB 미표시")
    if not (ctx.allowlist.server_ok(ctx.server) and ctx.allowlist.database_ok(ctx.database)):
        failures.append("서버/DB allowlist 불일치")
    if not (ctx.target_count > 0 and ctx.target_count_confirmed):
        failures.append("대상 건수 미확인")
    if not ctx.dup_check_passed:
        failures.append("실행 내 중복 검사 미통과")
    if not ctx.audit_log_pii_free:
        failures.append("감사 로그 PII 미제거")
    if not ctx.metadata_verified or SP_DEFINITION_SOURCE != "metadata":
        failures.append("SP 메타데이터 미검증(provisional)")
    return (not failures), failures


def commit_with_guards(conn, params: dict, ctx: CommitContext) -> dict:
    """가드 통과 시에만 COMMIT. 하나라도 실패하면 rollback.

    NOTE: 이번 작업에서는 어떤 경로로도 호출되지 않는다(실쓰기 금지).
    """
    ok, failures = check_commit_guards(ctx)
    if not ok:
        raise SpWriteBlocked("COMMIT 가드 미통과: " + "; ".join(failures))
    sql = build_wrapper_sql()
    values = params_in_order(params)
    cur = conn.cursor()
    cur.execute(sql, values)
    output = fetch_output_and_drain(cur)
    conn.commit()
    return {"output": output, "committed": True, "rolled_back": False}


# ───────────────────────────── DB 대상 검증 (미실행) ─────────────────────────────
def verify_db_target(conn, allowlist: "config.Allowlist") -> dict:
    """@@SERVERNAME / DB_NAME() 를 allowlist 와 정확 일치 검증. 고정 SQL.

    이번 작업에서는 호출하지 않는다(DB 미연결).
    """
    cur = conn.cursor()
    cur.execute("SELECT @@SERVERNAME AS srv, DB_NAME() AS db")
    row = cur.fetchone()
    srv = (row[0] or "").strip() if row else ""
    db = (row[1] or "").strip() if row else ""
    return {
        "server": srv, "database": db,
        "server_ok": allowlist.server_ok(srv),
        "database_ok": allowlist.database_ok(db),
        "ok": allowlist.server_ok(srv) and allowlist.database_ok(db),
    }
