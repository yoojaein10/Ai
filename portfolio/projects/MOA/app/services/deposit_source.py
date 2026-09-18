"""CB2_ACCT_HIS(Branch DB) 거래 내역 읽기 전용 조회.

카드내역과 같은 서버(.env CARD_SOURCE_*)를 쓴다. 쓰기는 절대 하지 않는다
(처리 기록은 GamJunDW의 a10_deposit_outbox — 방식 B).

INOUT_GUBUN '2' = 입금, '1' = 출금. 입금전표 배치는 입금만(fetch_deposits),
일계표 대사는 입·출금 전부(fetch_transactions)를 본다 (2026-08-26).
"""

from typing import Any

import pyodbc

from app.config import get_settings


class DepositSourceError(RuntimeError):
    pass


MAX_ROWS = 20000

_SELECT = """
SELECT h.UNIQUE_FIELD, h.BANK_CD, h.ACCT_NO, h.ACCT_TXDAY, h.ACCT_TXTIME, h.INOUT_GUBUN,
       h.TX_AMT, h.JEOKYO, h.Memo, a.ACCT_NICKNAME
FROM dbo.CB2_ACCT_HIS h
LEFT JOIN dbo.CB2_ACCT a
  ON a.BANK_CD = h.BANK_CD AND a.ACCT_NO = h.ACCT_NO
WHERE h.ACCT_TXDAY BETWEEN ? AND ?
"""
_ORDER = "ORDER BY h.ACCT_TXDAY, h.ACCT_TXDAY_SEQ\n"


def build_query(date_from: str, date_to: str, inout: "str | None") -> "tuple[str, tuple[str, ...]]":
    """inout: '2' 입금만, '1' 출금만, None 전체."""
    if inout is None:
        return _SELECT + _ORDER, (date_from, date_to)
    return _SELECT + "  AND h.INOUT_GUBUN = ?\n" + _ORDER, (date_from, date_to, inout)


def fetch_transactions(date_from: str, date_to: str, inout: "str | None" = None) -> "list[dict[str, Any]]":
    """거래일(YYYYMMDD) 기간의 거래를 조회한다. inout 이 None 이면 입·출금 전부."""
    settings = get_settings()
    if not settings.is_card_source_configured:
        raise DepositSourceError("입금내역 DB 설정이 없습니다 (.env의 CARD_SOURCE_*).")
    conn_str = (
        f"DRIVER={{{settings.mssql_driver}}};"
        f"SERVER={settings.card_source_server};DATABASE={settings.card_source_db};"
        f"UID={settings.card_source_user};"
        f"PWD={settings.card_source_password.get_secret_value()};"
        f"Encrypt={settings.mssql_encrypt};"
        f"TrustServerCertificate={settings.mssql_trust_server_certificate};"
    )
    sql, params = build_query(date_from, date_to, inout)
    try:
        with pyodbc.connect(conn_str, timeout=10) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            columns = [d[0] for d in cursor.description]
            rows = cursor.fetchmany(MAX_ROWS + 1)
    except pyodbc.Error as exc:
        raise DepositSourceError(f"입금내역 DB 조회에 실패했습니다: {exc}") from exc
    if len(rows) > MAX_ROWS:
        raise DepositSourceError(
            f"기간 내 거래가 {MAX_ROWS:,}건을 넘습니다. 기간을 좁혀 조회하세요."
        )
    return [dict(zip(columns, row)) for row in rows]


def fetch_deposits(date_from: str, date_to: str) -> "list[dict[str, Any]]":
    """입금(INOUT_GUBUN='2')을 거래일(YYYYMMDD) 기간으로 조회한다."""
    return fetch_transactions(date_from, date_to, inout="2")
