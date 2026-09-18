# -*- coding: utf-8 -*-
"""읽기 전용 ODBC 접속 및 트랜잭션 컨텍스트 (지시 §7).

■ 연결 보안 예외 (현 환경 확정, 2026-07-01):
  이 PC 에는 ODBC Driver 18 이 없고 Driver 17 만 설치돼 있으며, 테스트 DB 는 사설 IP 로
  접속하여 유효한 서버 인증서가 없다. 따라서 다음으로 확정한다.
  - ODBC Driver 17 for SQL Server 사용 (설치된 드라이버).
  - Encrypt=yes 명시 (미암호화 접속 금지).
  - TrustServerCertificate=yes (내부 신뢰 LAN, 인증서 제약).
  ★ TSC=yes 는 전송 암호화만 제공하고 서버 인증서 신원검증·능동 MITM 방어를 제공하지 않는다.
    DB 자격증명 자체가 미검증 연결로 전송되어 MITM 캡처·재사용 위험이 있다. 보완통제:
    전용 읽기전용 최소권한 계정만 사용, host/IP allowlist + 사후 서버/DB 검증, 고정 사설
    IP·포트, 유효 인증서 확보 후 Driver 18 + TSC=no 전환(운영 전 필수). 다른 TLS 로
    자동 fallback 하지 않는다.

- ApplicationIntent=ReadOnly (권한 통제로 신뢰하지 않음). MARS 등 불필요 기능 비활성.
- 로그인 timeout ≤ 5s, 쿼리 timeout ≤ 30s, LOCK_TIMEOUT 코드 상수.
- READ COMMITTED, autocommit=False. 각 조회 직후/중지/timeout/예외 시 rollback 후 close.
- connect_readonly() 내부에서 preflight(host/IP allowlist)를 강제한다.
- 완성된 연결 문자열은 반환값 repr/로그/예외에 포함하지 않는다.

이 모듈은 통합시험 스위치가 정확할 때만 실제 pyodbc 를 import·연결한다.
연결 문자열 생성과 주입 방지는 DB 없이 단위 테스트할 수 있다.
"""
from __future__ import annotations

from contextlib import contextmanager

import ro_config
import ro_query

RO_DRIVER = "ODBC Driver 17 for SQL Server"
# 내부 신뢰 LAN 예외 (§7). 유효 인증서 확보 시 no 로 전환.
TRUST_SERVER_CERTIFICATE = "yes"
LOGIN_TIMEOUT_SEC = 5
QUERY_TIMEOUT_SEC = 30

# SERVER/DATABASE/UID 에 허용하지 않는 문자(속성 주입/제어문자 방지)
_FORBIDDEN_IDENT_CHARS = ("{", "}", ";", "=", "\n", "\r", "\x00")


class ConnectionBlocked(Exception):
    """연결이 정책상 차단됨(통합시험 스위치 미설정/드라이버 부재 등)."""


class InjectionRejected(Exception):
    """접속 파라미터에 주입/제어문자가 포함됨."""


def _reject_injection(label: str, value: str) -> None:
    if value is None:
        raise InjectionRejected(f"{label} 이(가) None")
    for ch in _FORBIDDEN_IDENT_CHARS:
        if ch in value:
            raise InjectionRejected(f"{label} 에 허용되지 않는 문자 포함")


def _brace_escape(value: str) -> str:
    """ODBC brace escaping: 값 전체를 {..} 로 감싸고 내부 '}' 는 '}}' 로."""
    return "{" + value.replace("}", "}}") + "}"


def build_connection_string(target: "ro_config.ServerTarget", database: str,
                            user: str, password: str) -> str:
    """읽기 전용 ODBC 접속 문자열 생성. 보안값 강제 + 주입 방지.

    반환값은 비밀번호를 포함하므로 로그/예외/ repr 에 남기지 않는다(호출부 책임).
    환경변수를 단순 문자열 연결하지 않고, 파싱된 target 과 escaping 을 사용한다.
    """
    # SERVER: 파싱된 구성요소로 재조립 (원문 단순 연결 금지)
    server = target.host
    if target.instance:
        _reject_injection("instance", target.instance)
        server = f"{server}\\{target.instance}"
    if target.port:
        server = f"{server},{target.port}"

    _reject_injection("host", target.host)
    _reject_injection("database", database)
    _reject_injection("user", user)
    # password 는 brace escaping 으로 처리하되 NUL/개행은 여전히 거부
    for ch in ("\x00", "\n", "\r"):
        if ch in (password or ""):
            raise InjectionRejected("비밀번호에 제어문자 포함")

    parts = [
        f"DRIVER={{{RO_DRIVER}}}",
        f"SERVER={server}",
        f"DATABASE={database}",
        "Encrypt=yes",
        f"TrustServerCertificate={TRUST_SERVER_CERTIFICATE}",
        "ApplicationIntent=ReadOnly",
        "MARS_Connection=no",
        f"LoginTimeout={LOGIN_TIMEOUT_SEC}",
        f"UID={user}",
        f"PWD={_brace_escape(password or '')}",
    ]
    return ";".join(parts) + ";"


def assert_driver_available() -> None:
    """설치된 ODBC Driver 17 확인. 없으면 ConnectionBlocked (다른 TLS/드라이버 fallback 금지)."""
    try:
        import pyodbc
    except Exception as e:   # pragma: no cover - 환경 의존
        raise ConnectionBlocked("pyodbc 미설치") from e
    drivers = set(pyodbc.drivers())
    if RO_DRIVER not in drivers:
        raise ConnectionBlocked("ODBC Driver 17 미설치 (fallback 금지)")


def connect_readonly(creds: "ro_config.Credentials", allowlist: "ro_config.ReadOnlyAllowlist",
                     *, environ: dict | None = None, resolver=None):   # pragma: no cover - 실 DB
    """실제 읽기 전용 연결 생성. 통합시험 스위치가 정확할 때만 동작.

    내부에서 preflight(host/IP allowlist)를 강제한다. autocommit=False, LoginTimeout≤5,
    timeout≤30. 실패 시 자격증명 노출 없이 예외. 연결 직후 자격증명 참조를 best-effort 해제.
    """
    if not ro_config.integration_enabled(environ):
        raise ConnectionBlocked("통합시험 스위치 미설정 — 실 DB 연결 금지")
    # preflight 강제: 실패 시 자격증명을 네트워크로 보내기 전에 중단.
    target = ro_config.preflight_check(creds.server, allowlist, resolver=resolver)
    assert_driver_available()
    import pyodbc

    conn_str = build_connection_string(target, creds.database, creds.user, creds.password)
    try:
        conn = pyodbc.connect(conn_str, autocommit=False, timeout=LOGIN_TIMEOUT_SEC)
    except Exception as e:
        # 원문 pyodbc 진단정보(연결 문자열/서버명 등) 노출 금지
        raise ConnectionBlocked(f"연결 실패: {type(e).__name__}") from None
    finally:
        conn_str = None   # best-effort 참조 해제
        creds.clear()      # 연결 생성 후 자격증명 참조 해제(완전삭제 미보장)
    try:
        conn.timeout = QUERY_TIMEOUT_SEC
    except Exception:
        pass
    return conn


@contextmanager
def readonly_transaction(conn, *, stop_check=None):
    """읽기 전용 트랜잭션 컨텍스트.

    - 진입: autocommit off 확인, 세션 설정문(격리수준/락 타임아웃) 적용, 쿼리 timeout.
    - 종료: 정상/예외/중지/timeout 어떤 경우에도 rollback 후 close 보장.
    - COMMIT 은 절대 호출하지 않는다.
    stop_check: 호출 가능 객체. True 반환 시 협력적 중지(예외).
    """
    try:
        try:
            conn.autocommit = False
        except Exception:
            pass
        try:
            conn.timeout = QUERY_TIMEOUT_SEC
        except Exception:
            pass
        cur = conn.cursor()
        ro_query.apply_readonly_session(cur)
        if stop_check is not None and stop_check():
            raise ConnectionBlocked("중지 요청됨")
        yield conn
    finally:
        # 트랜잭션을 오래 유지하지 않는다: 즉시 rollback 후 close.
        try:
            conn.rollback()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass
