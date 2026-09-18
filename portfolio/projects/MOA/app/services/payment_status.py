"""a10_payment_status 갱신 — 입금된 감정서를 APWorks 조회용으로 정리한다.

a10_receivable_summary(감정서별 집계)에서 입금액이 있는 건만 골라 MERGE한다.
- 입금완료: 청구액이 있고 입금액이 청구액 이상이며, 산정액(청구금액)도 채운 경우
- 분할입금: 입금은 있으나 청구액/산정액을 아직 못 채움 (청구 전 선수금 포함)
기존 행은 UPDATE되므로 분할입금이 완납되면 입금완료로 바뀐다.

전표상으로는 완납이라도 산정액(apw_masterex 청구금액)에 못 미치는 공동감정 배분 건은
분할입금으로 잡는다 — 배분건은 입금분만 전표 계상돼 전표 미수가 0이 되기 때문이다.

미포착 수금 보정(무현금 선수금 정산 + 가수금→매출 직접 대체)은 받은 돈으로 쳐서
산정액과 비교한다 — 입금현황 판정(settle_cte_blocks/_SETTLED)과 같은 식.
안 그러면 입금현황은 완납인데 감정서 LIST·APWorks만 '일부입금'으로 남는다
(2026-09-01, 01-2606-1-0388 — 가수금 18건 + 선수금 18건 실측).

실비 종결(a10_expense_close 활성 행) 건은 무조건 입금완료다 — 처리 시점
수금액이 최종 매출로 확정된 건이다 (입금현황 _GROSS 의 ec 와 같은 규칙).
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.services.receivables import settle_cte_blocks, settled_amount_expr


def _source_db() -> str:
    name = get_settings().mssql_source_db
    if not name.replace("_", "").isalnum():
        raise RuntimeError("MSSQL_SOURCE_DB 이름이 올바르지 않습니다.")
    return name


def _merge_sql(scope_sql: str = "") -> str:
    src = _source_db()
    return f"""
WITH {settle_cte_blocks()}
MERGE dbo.a10_payment_status AS target
USING (
    SELECT s.doc_id,
           s.last_received_date,
           s.received_amount,
           CASE WHEN ec.doc_id IS NOT NULL THEN N'입금완료'
                WHEN s.billed_amount > 0 AND s.received_amount >= s.billed_amount
                     AND (m.[청구금액] IS NULL
                          OR m.[청구금액] - s.received_amount - ISNULL(g.amount, 0)
                             - {settled_amount_expr("st")} <= 1000)
                THEN N'입금완료' ELSE N'분할입금' END AS pay_result
    FROM dbo.a10_receivable_summary s
    LEFT JOIN (
        SELECT DocID, MAX([청구금액]) AS [청구금액]
        FROM [{src}].dbo.apw_masterex
        GROUP BY DocID
    ) m ON m.DocID = s.doc_id
    LEFT JOIN gasu g ON g.doc_id = s.doc_id
    LEFT JOIN settle st ON st.doc_id = s.doc_id
    LEFT JOIN dbo.a10_expense_close ec
      ON ec.doc_id = s.doc_id AND ec.released_at IS NULL
    WHERE s.received_amount > 0{f' AND {scope_sql}' if scope_sql else ''}
) AS source
ON target.doc_id = source.doc_id
WHEN MATCHED THEN UPDATE SET
    paid_date = source.last_received_date,
    paid_amount = source.received_amount,
    pay_result = source.pay_result,
    updated_at = GETDATE()
WHEN NOT MATCHED THEN INSERT (doc_id, paid_date, paid_amount, pay_result, updated_at)
    VALUES (source.doc_id, source.last_received_date, source.received_amount,
            source.pay_result, GETDATE());
"""


def refresh_payment_status(db: Session) -> int:
    result = db.execute(text(_merge_sql()))
    db.commit()
    return int(result.rowcount or 0)


def _reconcile_sql() -> str:
    """현재 APWorks 청구액으로 저장된 입금 판정을 다시 맞춘다.

    짧은 주기 전표 동기화는 전표가 바뀐 감정서만 MERGE한다. APWorks에서
    청구금액만 뒤늦게 수정되면 그 감정서는 대상에 들지 않아 예전 '입금완료'가
    남을 수 있다. 저장된 입금액과 최신 요약·APWorks 청구액을 다시 비교해
    양방향(입금완료↔분할입금)으로 어긋난 행만 고친다.
    """
    src = _source_db()
    return f"""
WITH {settle_cte_blocks()}, expected AS (
    SELECT p.doc_id,
           CASE WHEN ec.doc_id IS NOT NULL THEN N'입금완료'
                WHEN s.billed_amount > 0 AND s.received_amount >= s.billed_amount
                     AND (m.[청구금액] IS NULL
                          OR m.[청구금액] - s.received_amount - ISNULL(g.amount, 0)
                             - {settled_amount_expr("st")} <= 1000)
                THEN N'입금완료' ELSE N'분할입금' END AS pay_result
    FROM dbo.a10_payment_status p
    INNER JOIN dbo.a10_receivable_summary s ON s.doc_id = p.doc_id
    LEFT JOIN (
        SELECT DocID, MAX([청구금액]) AS [청구금액]
        FROM [{src}].dbo.apw_masterex
        GROUP BY DocID
    ) m ON m.DocID = p.doc_id
    LEFT JOIN gasu g ON g.doc_id = s.doc_id
    LEFT JOIN settle st ON st.doc_id = s.doc_id
    LEFT JOIN dbo.a10_expense_close ec
      ON ec.doc_id = s.doc_id AND ec.released_at IS NULL
    WHERE s.received_amount > 0
)
UPDATE p
SET pay_result = e.pay_result,
    updated_at = GETDATE()
FROM dbo.a10_payment_status p
INNER JOIN expected e ON e.doc_id = p.doc_id
WHERE ISNULL(p.pay_result, N'') <> e.pay_result;
"""


def reconcile_payment_status_with_master(db: Session) -> int:
    """APWorks만 바뀌어 남은 오래된 완납/부분입금 판정을 즉시 보정한다."""
    result = db.execute(text(_reconcile_sql()))
    db.commit()
    return int(result.rowcount or 0)


# SQL Server 파라미터 상한(2100) 대비 분할 크기
_CHUNK = 500


def refresh_payment_status_for(db: Session, doc_ids: "set[str] | list[str]") -> int:
    """전표가 바뀐 감정서만 입금 결과를 갱신한다 (10분 주기 부분 동기화용).

    MERGE는 sms_sent_at/sms_sent_by를 건드리지 않아 전송 기록이 보존된다.
    """
    targets = sorted({str(doc).strip() for doc in doc_ids if str(doc or "").strip()})
    if not targets:
        return 0
    merged = 0
    for start in range(0, len(targets), _CHUNK):
        chunk = targets[start:start + _CHUNK]
        placeholders = ", ".join(
            f"CAST(:d{i} AS VARCHAR(500))" for i in range(len(chunk))
        )
        params = {f"d{i}": doc for i, doc in enumerate(chunk)}
        result = db.execute(
            text(_merge_sql(f"s.doc_id IN ({placeholders})")), params
        )
        merged += int(result.rowcount or 0)
    db.commit()
    return merged
