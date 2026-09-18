"""SQL Server 연결 헬퍼 (pyodbc)."""
from __future__ import annotations

import decimal  # noqa: F401 - pyodbc 가 fetch 중 lazy-import 하는 모듈 선로딩(frozen 환경 안전)
import uuid  # noqa: F401 - 상동
from contextlib import contextmanager

import pyodbc

from .config import SqlConfig


@contextmanager
def connect(sql: SqlConfig, *, readonly: bool = False, timeout: int = 15, autocommit: bool = True):
    """SqlConfig 로 연결을 열고 컨텍스트 종료 시 닫는다.

    적재(store_result)는 트랜잭션 단위 멱등 처리를 위해 autocommit=False 로 연다.
    """
    conn = pyodbc.connect(
        sql.connection_string(readonly=readonly),
        autocommit=autocommit,
        timeout=timeout,
    )
    try:
        yield conn
    finally:
        conn.close()


# 새 연결로 재시도할 가치가 있는 일시적 DB 오류 시그니처(소문자).
# 병렬 적재 시 SQL Server 데드락 victim 은 driver 단에서 opaque pyodbc 오류
# ('returned a result with an exception set')로 표면화된다 — 문서 결함이 아니라
# 경합이므로 재접속 후 재시도하면 대개 성공한다. 데이터 오류(22001 잘림 등)는
# 여기 없어서 재시도 없이 그대로 failed 로 격리된다(진짜 버그를 가리지 않음).
_TRANSIENT_DB_TOKENS = (
    "returned a result with an exception set",
    "deadlock",
    "40001",
    "1205",
    "communication link failure",
    "08s01",
    "08003",
    "connection is busy",
)


def is_transient_db_error(exc: Exception) -> bool:
    """일시적(재시도 가치 있는) DB 오류인지 판별한다.

    pyodbc C 예외가 CPython SystemError 로 깨져 나오는 경우도 잡는다
    (예: "SystemError: <class 'pyodbc.ProgrammingError'> returned a result with
    an exception set" — 실제 오류가 가려진 채 표면화되며, 새 연결 재시도로
    대개 회복된다. 프리징/스레드 환경에서 관측됨).
    """
    text = (" ".join(str(a) for a in exc.args) or str(exc)).lower()
    if isinstance(exc, pyodbc.Error):
        return any(token in text for token in _TRANSIENT_DB_TOKENS)
    return "pyodbc" in text and "returned a result with an exception set" in text


class SqlHandle:
    """재접속 가능한 SQL 연결 홀더([[FtpHandle]] 과 동형).

    장시간 배치 중 일시적 DB 오류(데드락 등)로 연결이 오염되면 reconnect() 로
    새 연결로 갈아끼운다. 사용처는 항상 .conn 속성으로 현재 연결에 접근해야 한다.
    """

    def __init__(self, sql: SqlConfig, *, readonly: bool = False,
                 timeout: int = 15, autocommit: bool = True):
        self._sql = sql
        self._readonly = readonly
        self._timeout = timeout
        self._autocommit = autocommit
        self.conn = self._open()

    def _open(self):
        return pyodbc.connect(
            self._sql.connection_string(readonly=self._readonly),
            autocommit=self._autocommit,
            timeout=self._timeout,
        )

    def reconnect(self) -> None:
        try:
            self.conn.close()
        except Exception:  # noqa: BLE001 - 종료 실패는 무시
            pass
        self.conn = self._open()

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:  # noqa: BLE001
            pass


@contextmanager
def sql_handle(sql: SqlConfig, *, readonly: bool = False,
               timeout: int = 15, autocommit: bool = True):
    """재접속 가능한 SqlHandle 을 열고 종료 시 닫는다."""
    handle = SqlHandle(sql, readonly=readonly, timeout=timeout, autocommit=autocommit)
    try:
        yield handle
    finally:
        handle.close()
