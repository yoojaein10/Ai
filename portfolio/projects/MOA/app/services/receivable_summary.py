"""a10_receivable_summary 재집계 + 입금 알림 큐 적재.

재집계 두 가지 모드:

- 전체(rebuild_receivable_summary): 51만 행을 통째로 DELETE + INSERT. 20초 남짓 걸리지만
  무엇이 어긋나 있든 스스로 바로잡는다. 야간 심층 동기화(365일)에서 쓴다.
- 부분(rebuild_receivable_summary_for): 전표가 바뀐 감정서만 갈아끼운다. 2초 수준이라
  짧은 주기(10분) 배치에 쓴다. 입금 알림을 전표 입력 직후에 띄우려면 이 경로가 필요하다.

부분 갱신은 '바뀐 감정서'를 잘못 모으면 그 행이 계속 틀린 채 남는다. 그래서
동기화 대상 기간에서 지워질 전표와 새로 들어올 전표의 관리번호를 모두 합쳐 넘기고
(voucher_cache_sync._affected_docs 참조), 야간 전체 재집계로 한 번 더 덮는다.

두 경로 모두 재집계 전 누적 입금액을 임시표에 담아두고, 재집계 후 늘어난 감정서만
a10_payment_notify에 넣는다. 요약 테이블에 '갱신 시각'을 두는 방식은 못 쓴다 —
전체 재집계가 전 행을 다시 써서 매일 밤 51만 건이 '변경됨'으로 보이게 된다.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.services.receivables import receivable_status_cte


def _source_db() -> str:
    name = get_settings().mssql_source_db
    if not name.replace("_", "").isalnum():
        raise RuntimeError("MSSQL_SOURCE_DB 이름이 올바르지 않습니다.")
    return name

_COLUMNS = (
    "doc_id, billed_amount, received_amount, advance_amount, suspense_amount, "
    "outstanding_amount, overpaid_amount, last_received_date, receipt_count"
)

# SQL Server 파라미터 상한(2100)에 걸리지 않게 관리번호를 나눠 넣는다.
_CHUNK = 500

_REBUILD_SQL = (
    receivable_status_cte("management_no IS NOT NULL")
    + f"""
    INSERT INTO dbo.a10_receivable_summary ({_COLUMNS})
    SELECT {_COLUMNS} FROM b
    """
)

_SNAPSHOT_DDL = (
    "CREATE TABLE #prev_received "
    "(doc_id VARCHAR(500) PRIMARY KEY, amount NUMERIC(19,4))"
)


def _snapshot(db: Session, where_sql: str = "", params: "dict | None" = None) -> int:
    """재집계 전 누적 입금액을 세션 임시표에 담는다. 담은 행 수를 돌려준다."""
    db.execute(
        text("IF OBJECT_ID('tempdb..#prev_received') IS NOT NULL DROP TABLE #prev_received")
    )
    db.execute(text(_SNAPSHOT_DDL))
    result = db.execute(
        text(
            "INSERT INTO #prev_received (doc_id, amount) "
            "SELECT doc_id, received_amount FROM dbo.a10_receivable_summary "
            + (f"WHERE {where_sql}" if where_sql else "")
        ),
        params or {},
    )
    return int(result.rowcount or 0)


def _enqueue(db: Session, scope_sql: str = "", params: "dict | None" = None) -> int:
    """직전 스냅샷보다 누적 입금액이 늘어난 감정서를 알림 큐에 넣는다.

    scope_sql은 반드시 스냅샷과 같은 범위여야 한다. 부분 갱신에서 이걸 빼면
    스냅샷에 없는 51만 행이 전부 '신규 입금'으로 딸려 들어간다.
    """
    # 담당·거래처·지사 등은 발송 시스템이 큐만 보고 처리할 수 있게 비정규화해 담는다
    # (manager/charge/cust_name=마스터, office=감정서번호 접두사→office_id,
    #  status='완납'/'부분입금' — 입금현황 용어와 동일).
    src = _source_db()
    result = db.execute(
        text(
            f"""
            INSERT INTO dbo.a10_payment_notify
                (doc_id, delta_amount, previous_amount, received_amount,
                 billed_amount, outstanding_amount, last_received_date,
                 manager, charge, cust_name, office, overpaid_amount, status)
            SELECT s.doc_id,
                   s.received_amount - ISNULL(p.amount, 0),
                   ISNULL(p.amount, 0),
                   s.received_amount,
                   s.billed_amount,
                   s.outstanding_amount,
                   s.last_received_date,
                   LEFT(NULLIF(RTRIM(m.Manager), ''), 100),
                   LEFT(NULLIF(RTRIM(m.Charge), ''), 200),
                   LEFT(NULLIF(RTRIM(m.CustName), ''), 200),
                   o.office_id,
                   s.overpaid_amount,
                   CASE WHEN s.billed_amount > 0 AND s.received_amount >= s.billed_amount
                        THEN N'완납' ELSE N'부분입금' END
            FROM dbo.a10_receivable_summary s
                LEFT JOIN #prev_received p ON p.doc_id = s.doc_id
                LEFT JOIN (
                    SELECT DocID, MAX(Manager) AS Manager, MAX(Charge) AS Charge,
                           MAX(CustName) AS CustName
                    FROM [{src}].dbo.apw_masterex
                    GROUP BY DocID
                ) m ON m.DocID = s.doc_id
                LEFT JOIN dbo.a10_office_map o ON o.docid_prefix = LEFT(s.doc_id, 2)
            WHERE s.received_amount > ISNULL(p.amount, 0)
            """
            + (f" AND {scope_sql}" if scope_sql else "")
        ),
        params or {},
    )
    return int(result.rowcount or 0)


def rebuild_receivable_summary(db: Session) -> int:
    snapshot_rows = _snapshot(db)
    db.execute(text("DELETE FROM dbo.a10_receivable_summary"))
    result = db.execute(text(_REBUILD_SQL))
    # 스냅샷이 비어 있으면 요약을 처음 채우는 것이다 — 과거 입금 전부가
    # '신규 입금'으로 쏟아지지 않게 이때는 큐에 넣지 않는다.
    if snapshot_rows:
        _enqueue(db)
    db.commit()
    return int(result.rowcount or 0)


def rebuild_receivable_summary_for(db: Session, doc_ids: "set[str] | list[str]") -> int:
    """지정한 감정서의 요약 행만 다시 만든다. 넘긴 감정서가 없으면 아무것도 하지 않는다.

    전표가 모두 사라진 감정서는 DELETE만 되고 INSERT 대상에서 빠진다 —
    삭제된 입금이 요약에 남는 것을 막으려면 이 동작이 필요하다.
    """
    targets = sorted({str(doc).strip() for doc in doc_ids if str(doc or "").strip()})
    if not targets:
        return 0

    inserted = 0
    for start in range(0, len(targets), _CHUNK):
        chunk = targets[start:start + _CHUNK]
        # varchar 컬럼에 파라미터를 그대로 바인드하면 NVARCHAR 변환으로 풀스캔이 난다.
        placeholders = ", ".join(
            f"CAST(:d{i} AS VARCHAR(50))" for i in range(len(chunk))
        )
        params = {f"d{i}": doc for i, doc in enumerate(chunk)}
        scope = f"doc_id IN ({placeholders})"
        _snapshot(db, scope, params)
        db.execute(
            text(f"DELETE FROM dbo.a10_receivable_summary WHERE {scope}"),
            params,
        )
        result = db.execute(
            text(
                receivable_status_cte(f"management_no IN ({placeholders})")
                + f"""
                INSERT INTO dbo.a10_receivable_summary ({_COLUMNS})
                SELECT {_COLUMNS} FROM b
                """
            ),
            params,
        )
        # 부분 갱신에서는 스냅샷이 비어도(전부 신규 감정서) 큐에 넣는다 —
        # 새 감정서의 첫 입금도 알려야 한다. 범위는 s.doc_id로 한정한다.
        _enqueue(db, f"s.{scope}", params)
        inserted += int(result.rowcount or 0)
    db.commit()
    return inserted
