"""실적 행의 원천 — 어느 감정서가 이번 달 상여 후보인가 (앱 소유 표만 읽는다).

후보 = {입금월에 4010001 감정수수료 대변 전표가 있는 본사 감정서}
     ∪ {그 달 완납된 감정서 (a10_payment_status '입금완료' 또는 a10_receivable_summary 미수 0)}
순수수료 F = 그 감정서의 4010001 대변 − 차변 전 기간 순액 — 든든전세류 "수수료 배분 전표"
(일괄 −81.2M 은 관리번호가 감정서가 아니라 빠지고 건별 +45만 만 잡힌다)가 그대로 든다.
2026-07 실측: 현행 GaPrice 302/528 → 이 규칙 515/528 (메모리 bonus-rewrite-analysis).

이 SQL 은 dbo.a10_* 만 읽어서 sqlite(ATTACH dbo)로 실행 검증한다 — COALESCE 만 쓰고
TOP/DATEADD/CONVERT 는 쓰지 않는다. 원천 DB([apworksdw]) 리더는 sources_apw.py.
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import text

from app.services.bonus.rules import FEE_ACCOUNTS, HQ_DIVISION, PRICE_ADVICE_ACCOUNT, PRICE_ADVICE_TYPE

HQ_PREFIX = "01-%"
HQ_SUB_PREFIX = "01____-%"   # 가지번호 012607-4-0236-1 (대시 없이 6자리)
PAID_RESULT = "입금완료"

_CANDIDATES_SQL = """
WITH sales AS (
    SELECT management_no AS doc_id,
           SUM(CASE WHEN debit_credit = '4' THEN amount ELSE -amount END) AS fee_month
    FROM dbo.a10_voucher_cache
    WHERE {fee_filter}
      AND division_code = CAST(:division AS VARCHAR(4))
      AND voucher_date >= :perf_from AND voucher_date <= :perf_to
      AND (management_no LIKE CAST(:hq_prefix AS VARCHAR(50)) OR management_no LIKE CAST(:hq_sub AS VARCHAR(50)))
    GROUP BY management_no
), paid_summary AS (
    SELECT doc_id FROM dbo.a10_receivable_summary
    WHERE last_received_date >= :perf_from AND last_received_date <= :perf_to
      AND COALESCE(outstanding_amount, 0) <= 0
      AND (doc_id LIKE CAST(:hq_prefix AS VARCHAR(50)) OR doc_id LIKE CAST(:hq_sub AS VARCHAR(50)))
), paid_status AS (
    SELECT doc_id FROM dbo.a10_payment_status
    WHERE pay_result = :paid_result
      AND paid_date >= :perf_from AND paid_date <= :perf_to
      AND (doc_id LIKE CAST(:hq_prefix AS VARCHAR(50)) OR doc_id LIKE CAST(:hq_sub AS VARCHAR(50)))
), cand AS (
    SELECT doc_id, 1 AS from_sales, 0 AS from_paid FROM sales
    UNION ALL SELECT doc_id, 0, 1 FROM paid_summary
    UNION ALL SELECT doc_id, 0, 1 FROM paid_status
), cand_g AS (
    SELECT doc_id, MAX(from_sales) AS from_sales, MAX(from_paid) AS from_paid
    FROM cand GROUP BY doc_id
), sale_vouchers AS (
    SELECT DISTINCT v.management_no AS doc_id, v.voucher_date, v.voucher_no, v.division_code
    FROM dbo.a10_voucher_cache v
    INNER JOIN cand_g c ON c.doc_id = v.management_no
    WHERE {fee_filter_v} AND v.debit_credit = '4'
      AND v.division_code = CAST(:division AS VARCHAR(4))
      AND v.voucher_date >= :perf_from AND v.voucher_date <= :perf_to
), sale_flags AS (
    -- MSSQL 은 집계 안에 서브쿼리를 못 넣는다 — 전표별 판정을 먼저 만들고 다음 CTE 에서 모은다
    SELECT sv.doc_id,
           CASE WHEN EXISTS (
                SELECT 1 FROM dbo.a10_voucher_cache d
                WHERE d.voucher_date = sv.voucher_date AND d.voucher_no = sv.voucher_no
                  AND d.division_code = sv.division_code
                  AND d.account_code = CAST(:ar_acct AS VARCHAR(8)) AND d.debit_credit = '3')
            AND NOT EXISTS (
                SELECT 1 FROM dbo.a10_voucher_cache k
                WHERE k.voucher_date = sv.voucher_date AND k.voucher_no = sv.voucher_no
                  AND k.division_code = sv.division_code
                  AND k.account_code IN (CAST(:cash_acct AS VARCHAR(8)), CAST(:hq_cash_acct AS VARCHAR(8)))
                  AND k.debit_credit = '3')
            THEN 1 ELSE 0 END AS invoice_only
    FROM sale_vouchers sv
), invoice_only AS (
    SELECT doc_id, MAX(invoice_only) AS invoice_only FROM sale_flags GROUP BY doc_id
), fee_all AS (
    SELECT v.management_no AS doc_id,
           SUM(CASE WHEN v.debit_credit = '4' THEN v.amount ELSE -v.amount END) AS fee_total,
           MIN(CASE WHEN v.debit_credit = '4' THEN v.voucher_date END) AS first_sale_date
    FROM dbo.a10_voucher_cache v
    INNER JOIN cand_g c ON c.doc_id = v.management_no
    WHERE {fee_filter_v}
      AND v.division_code = CAST(:division AS VARCHAR(4))
    GROUP BY v.management_no
)
SELECT c.doc_id, c.from_sales, c.from_paid,
       COALESCE(f.fee_total, 0) AS fee_total, COALESCE(s.fee_month, 0) AS fee_month,
       f.first_sale_date,
       r.billed_amount, r.received_amount, r.outstanding_amount, r.last_received_date,
       p.pay_result, p.paid_date, COALESCE(i.invoice_only, 0) AS invoice_only
FROM cand_g c
LEFT JOIN fee_all f ON f.doc_id = c.doc_id
LEFT JOIN invoice_only i ON i.doc_id = c.doc_id
LEFT JOIN sales s ON s.doc_id = c.doc_id
LEFT JOIN dbo.a10_receivable_summary r ON r.doc_id = c.doc_id
LEFT JOIN dbo.a10_payment_status p ON p.doc_id = c.doc_id
ORDER BY c.doc_id
"""


def _as_date(value: Any) -> "date | None":
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _money(value: Any) -> float:
    return float(value or 0)


def _fee_filter(prefix: str) -> str:
    """감정서 유형에 따라 수수료 계정이 다르다: 가격자문(유형 6)은 4010002, 나머지는 4010001.
    유형은 관리번호 9번째 글자('01-2606-6-0406')."""
    kind = (
        f"CASE WHEN {prefix}management_no LIKE CAST(:hq_prefix AS VARCHAR(50)) "
        f"THEN SUBSTRING({prefix}management_no, 9, 1) ELSE SUBSTRING({prefix}management_no, 8, 1) END"
    )
    return (
        f"(({prefix}account_code = CAST(:fee_acct AS VARCHAR(8)) AND {kind} <> CAST(:advice_type AS VARCHAR(1))) "
        f"OR ({prefix}account_code = CAST(:advice_acct AS VARCHAR(8)) AND {kind} = CAST(:advice_type AS VARCHAR(1))))"
    )


def candidate_docs(db, perf_from: date, perf_to: date) -> "list[dict[str, Any]]":
    """입금월(perf_from~perf_to)의 상여 후보 감정서와 판정에 필요한 숫자."""
    sql = _CANDIDATES_SQL.format(fee_filter=_fee_filter(""), fee_filter_v=_fee_filter("v."))
    rows = db.execute(text(sql), {
        "fee_acct": FEE_ACCOUNTS[0], "advice_acct": PRICE_ADVICE_ACCOUNT, "advice_type": PRICE_ADVICE_TYPE,
        "division": HQ_DIVISION, "hq_prefix": HQ_PREFIX, "hq_sub": HQ_SUB_PREFIX, "paid_result": PAID_RESULT,
        "ar_acct": "1080000", "cash_acct": "1030000", "hq_cash_acct": "1410001",
        "perf_from": perf_from, "perf_to": perf_to,
    }).mappings().all()
    result = []
    for row in rows:
        sources = []
        if row["from_sales"]:
            sources.append("SALES")
        if row["from_paid"]:
            sources.append("PAID")
        result.append({
            "doc_id": str(row["doc_id"]).strip(),
            "sources": sources,
            "fee_total": _money(row["fee_total"]),
            "fee_month": _money(row["fee_month"]),
            "first_sale_date": _as_date(row["first_sale_date"]),
            "billed": _money(row["billed_amount"]),
            "received": _money(row["received_amount"]),
            "outstanding": _money(row["outstanding_amount"]),
            "last_received_date": _as_date(row["last_received_date"]),
            "pay_result": row["pay_result"],
            "paid_date": _as_date(row["paid_date"]),
            "invoice_only": bool(row["invoice_only"]),
        })
    return result


def classify_candidate(row: "dict[str, Any]", *, perf_to: date) -> "tuple[str, list[str]]":
    """(상태, 표시). INCLUDED | HELD_UNPAID | HELD_NO_FEE | HELD_PAID_LATER.

    월말 기준 게이트 — 매출은 이달인데 입금이 다음 달이면 다음 달 몫이다(두 번 지급 방지 1).
    청구·입금이 둘 다 0 인 묶음 건(든든전세)은 포함하되 PAID_BY_BUNDLE 로 표시한다.
    """
    if row["outstanding"] > 0:
        return ("HELD_UNPAID", [])
    # 외상매출금만 잡히고 현금이 없는 전표(청구서만 끊은 건)는 입금 판정이 없으면 미입금이다 —
    # 외상 차변의 관리번호가 거래처코드라 입금요약이 청구를 모르는 건(01-2604-7-0035 78M)을 막는다.
    if row.get("invoice_only") and row["billed"] == 0 and not row.get("pay_result"):
        return ("HELD_UNPAID", [])
    if row["fee_total"] <= 0:
        return ("HELD_NO_FEE", [])
    last_received = row.get("last_received_date")
    if last_received is not None and last_received > perf_to:
        return ("HELD_PAID_LATER", [])
    flags = ["PAID_BY_BUNDLE"] if (row["billed"] == 0 and row["received"] == 0) else []
    return ("INCLUDED", flags)


# ── 당월감정서경비 (앱 소유 전표 캐시) ──────────────────────────────────────────

def voucher_expense_rows(db, date_from: date, date_to: date) -> "list[dict[str, Any]]":
    """당월 경비 전표(본사 1000, 잡급·세금과공과금·도서인쇄비·용역비, 차변) 줄 단위 — 적요의 감정서번호를 뽑아 둔다.

    key 는 (전표일, 전표번호, 줄번호)로 안정적이다 → 공제 대장의 전표 후보 중복 방지 키.
    """
    from app.services.bonus.rules import EXPENSE_ACCOUNTS, extract_doc_ids

    accounts = {f"a{i}": code for i, code in enumerate(EXPENSE_ACCOUNTS)}
    rows = db.execute(text(f"""
SELECT voucher_date, voucher_no, line_no, account_code, RTRIM(account_name) AS account_name, amount, RTRIM(remark) AS remark
FROM dbo.a10_voucher_cache
WHERE voucher_date >= :date_from AND voucher_date <= :date_to
  AND division_code = CAST(:division AS VARCHAR(4)) AND debit_credit = '3'
  AND account_code IN ({", ".join(f"CAST(:{name} AS VARCHAR(8))" for name in accounts)})
ORDER BY voucher_date DESC, voucher_no, line_no
"""), {"date_from": date_from, "date_to": date_to, "division": HQ_DIVISION, **accounts}).mappings().all()
    result = []
    for row in rows:
        day = _as_date(row["voucher_date"])
        result.append({
            "key": f"{day:%Y%m%d}:{str(row['voucher_no'] or '').strip()}:{str(row['line_no'] or '').strip()}",
            "voucher_date": day, "account_name": row["account_name"], "amount": float(row["amount"] or 0),
            "remark": row["remark"], "doc_ids": extract_doc_ids(row["remark"] or ""),
        })
    return result


def voucher_expenses(
    db, date_from: date, date_to: date, known_docs: "set[str] | None" = None,
) -> "tuple[dict[str, float], list[dict[str, Any]]]":
    """감정서별 경비 합계와 귀속 못 한 전표 목록 (참고 표시용).

    2026-08-27부터 엔진은 이 합계를 자동으로 빼지 않는다 — 전표는 공제 대장의 대기 후보가 된다(voucher_expense_rows).
    한 적요에 감정서가 여럿이면 균등 분할. known_docs 를 주면 그 밖의 감정서 전표도 참고 목록으로.
    """
    by_doc: "dict[str, float]" = {}
    unmatched: "list[dict[str, Any]]" = []
    for row in voucher_expense_rows(db, date_from, date_to):
        doc_ids = row["doc_ids"]
        if known_docs is not None:
            doc_ids = [doc for doc in doc_ids if doc in known_docs]
        if doc_ids:
            for doc_id in doc_ids:
                by_doc[doc_id] = by_doc.get(doc_id, 0.0) + row["amount"] / len(doc_ids)
        else:
            unmatched.append({
                "voucher_date": row["voucher_date"].isoformat() if row["voucher_date"] else None,
                "account_name": row["account_name"], "amount": row["amount"], "remark": row["remark"],
            })
    return by_doc, unmatched


def simple_appraisal_total(db, date_from: date, date_to: date) -> "tuple[float, int]":
    """국민약식(관리번호 400*) 4010002 순액(대변−차변)과 건수 — 입금월의 전표 기준 (엑셀 '국민약식' F 의 원천)."""
    from app.services.bonus.rules import PRICE_ADVICE_ACCOUNT, SIMPLE_APPRAISAL_PREFIX

    row = db.execute(text("""
SELECT COALESCE(SUM(CASE WHEN debit_credit = '4' THEN amount ELSE -amount END), 0) AS net, COUNT(DISTINCT management_no) AS docs
FROM dbo.a10_voucher_cache
WHERE voucher_date >= :date_from AND voucher_date <= :date_to
  AND division_code = CAST(:division AS VARCHAR(4)) AND account_code = CAST(:account AS VARCHAR(8))
  AND management_no LIKE CAST(:prefix AS VARCHAR(50))
"""), {"date_from": date_from, "date_to": date_to, "division": HQ_DIVISION, "account": PRICE_ADVICE_ACCOUNT,
       "prefix": f"{SIMPLE_APPRAISAL_PREFIX}%"}).mappings().one()
    return float(row["net"] or 0), int(row["docs"] or 0)
