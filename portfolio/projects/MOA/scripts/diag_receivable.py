"""입금현황 미수금 판정 진단 (읽기 전용).

한 감정서에 대해 원장·요약·전표·계산서를 모두 뽑고, 입금현황이 쓰는 식
(_GROSS - _PAID)을 그대로 재현해 어느 값 때문에 미수가 남는지 보여준다.

사용법: python -m scripts.diag_receivable --docid 01-2606-5-0095
"""

import argparse

from sqlalchemy import text

from app.database import get_session_factory
from app.services.receivables import (
    _GROSS,
    _PAID,
    _SETTLED,
    _SETTLE_CTE,
    _TAX_OK,
    _source_view,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--docid", required=True)
    args = parser.parse_args()
    doc = args.docid

    source = _source_view()
    session = get_session_factory()()
    try:
        print(f"=== 원장 {source} ===")
        row = session.execute(
            text(
                f"SELECT DocID, LStatus, SendDate, ReceiptDate, CustName, Manager, "
                f"LWorkinfo, LCategory, [기초수수료], [절사금액], [수수료합계], "
                f"[부가가치세], [청구금액], [매출총액] "
                f"FROM {source} WHERE DocID = :doc"
            ),
            {"doc": doc},
        ).mappings().first()
        if not row:
            print("  (원장에 없음)")
        else:
            for key, value in row.items():
                print(f"  {key:12} = {value}")

        print("\n=== 요약 a10_receivable_summary ===")
        summary = session.execute(
            text("SELECT * FROM dbo.a10_receivable_summary WHERE doc_id = :doc"),
            {"doc": doc},
        ).mappings().first()
        if not summary:
            print("  (요약 없음 — 전표가 한 건도 안 잡혔다는 뜻)")
        else:
            for key, value in summary.items():
                print(f"  {key:24} = {value}")

        print("\n=== 세금계산서 ===")
        for label, sql in (
            (
                "TAMS 캐시",
                "SELECT approval_no, sup_am, vat_am, total_am, bal_date, status_cd "
                "FROM dbo.a10_tams_tax_cache WHERE appraisal_no = :doc",
            ),
            (
                "MOA 발급분",
                "SELECT nts_confirm, supply_cost, tax, total, issue_dt "
                "FROM dbo.a10_issued_taxinvoice WHERE doc_id = :doc",
            ),
        ):
            rows = session.execute(text(sql), {"doc": doc}).mappings().all()
            print(f"  [{label}] {len(rows)}건")
            for r in rows:
                print(f"    {dict(r)}")

        print("\n=== 전표 캐시 (전표 전체 줄) ===")
        # 관리번호로만 거르면 안 된다 — 부가세예수금(2550000) 줄에는 관리번호가
        # 안 붙어서 통째로 빠진다. 그러면 '부가세를 안 받았다'로 오독하게 된다
        # (2026-08-07 실제 오독). 관리번호로 전표를 찾은 뒤 그 전표의 모든 줄을 본다.
        vouchers = session.execute(
            text(
                "SELECT c.voucher_date, c.voucher_no, c.division_code, c.account_code, "
                "c.account_name, c.debit_credit, c.amount, c.partner_name, "
                "c.management_no, c.remark "
                "FROM dbo.a10_voucher_cache c "
                "INNER JOIN (SELECT DISTINCT voucher_date, voucher_no, division_code "
                "            FROM dbo.a10_voucher_cache WHERE management_no = :doc) k "
                "  ON k.voucher_date = c.voucher_date AND k.voucher_no = c.voucher_no "
                " AND k.division_code = c.division_code "
                "ORDER BY c.voucher_date, c.voucher_no, c.account_code"
            ),
            {"doc": doc},
        ).mappings().all()
        print(f"  {len(vouchers)}줄 (이 감정서와 무관한 줄은 묶음전표의 다른 건이다)")
        for v in vouchers:
            side = "차변" if str(v["debit_credit"]) == "3" else "대변"
            mine = " " if v["management_no"] == doc else "·"
            print(
                f"  {mine} {v['voucher_date']} {v['voucher_no']:>6} {v['division_code']} "
                f"{v['account_code']} {(v['account_name'] or '')[:8]:8} {side} "
                f"{float(v['amount'] or 0):>14,.0f} "
                f"{(v['partner_name'] or '')[:12]:12} {(v['remark'] or '')[:36]}"
            )

        print("\n=== 입금현황 판정식 재현 ===")
        verdict = session.execute(
            text(
                _SETTLE_CTE
                + f"SELECT {_GROSS} AS gross, {_PAID} AS paid, "
                f"{_GROSS} - {_PAID} AS outstanding, {_SETTLED} AS settled, "
                f"CASE WHEN {_TAX_OK} THEN 1 ELSE 0 END AS tax_ok, "
                "ISNULL(b.received_amount, 0) AS received_amount, "
                "ISNULL(b.billed_amount, 0) AS billed_amount, "
                "ISNULL(b.advance_amount, 0) AS advance_amount, "
                "ISNULL(b.overpaid_amount, 0) AS overpaid_amount, "
                "b.last_received_date, "
                "ISNULL(a.[매출총액], 0) AS ledger_gross, "
                "ISNULL(a.[청구금액], 0) AS ledger_billed, "
                "ISNULL(t.tax_total, 0) AS tax_total, "
                "ISNULL(t.own_sales, 0) AS own_sales, "
                "ISNULL(s.uncounted, 0) AS uncounted, ISNULL(s.vat_extra, 0) AS vat_extra, "
                "ISNULL(s.gasu_settled, 0) AS gasu_settled, "
                "ISNULL(s.credit_all, 0) AS credit_all, ISNULL(s.debit_all, 0) AS debit_all "
                f"FROM dbo.a10_receivable_summary b "
                f"LEFT JOIN {source} a ON a.DocID = b.doc_id "
                "LEFT JOIN settle s ON s.doc_id = b.doc_id "
                "LEFT JOIN tax_doc t ON t.doc_id = b.doc_id "
                "LEFT JOIN dbo.a10_expense_close ec "
                "  ON ec.doc_id = b.doc_id AND ec.released_at IS NULL "
                "WHERE b.doc_id = :doc"
            ),
            {"doc": doc},
        ).mappings().first()
        if not verdict:
            print("  (요약이 없어 판정식을 못 돌린다)")
        else:
            for key, value in verdict.items():
                mark = ""
                if key == "outstanding" and value is not None:
                    mark = "   <<< 미수금" if float(value) > 2.0 else "   (미수 없음)"
                print(f"  {key:20} = {value}{mark}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
