"""일계표 대사 실측 — 하루치 리포트를 돌려 계좌별 상태와 회계단위 소계를 찍는다.

  python -m scripts.bank_reconcile_check --date 2026-08-25
  python -m scripts.bank_reconcile_check --date 2026-08-25 --division 1000 --detail

본사(1000) 차변·대변 소계가 아마란스 일계표 보통예금 계와 같아야 한다.
"""

import argparse
from datetime import date

from app.database import get_session_factory
from app.services.bank_reconcile import STATUS_TEXT, build_report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--to", help="YYYY-MM-DD (기본: --date)")
    parser.add_argument("--division", default=None)
    parser.add_argument("--detail", action="store_true", help="미일치 건을 줄 단위로 찍는다")
    args = parser.parse_args()
    date_from = date.fromisoformat(args.date)
    date_to = date.fromisoformat(args.to) if args.to else date_from

    with get_session_factory()() as db:
        report = build_report(db, date_from, date_to, args.division)

    summary = report["summary"]
    print(f"[{report['period']['from']} ~ {report['period']['to']}] 전표 캐시 {report['synced_at']} · "
          f"계좌 {summary['accounts']} · 차이 {summary['mismatched']} · 합계만 {summary['total_only']} · 매핑필요 {summary['unmapped']}")
    for name, label in (("deposit", "입금"), ("withdrawal", "출금")):
        side = summary[name]
        print(f"  {label}: 은행 {side['bank_count']}건 {side['bank_total']:,} / 전표 {side['voucher_count']}건 "
              f"{side['voucher_total']:,} / 차이 {side['diff']:,}")
    print("회계단위 소계(전표):")
    for item in report["division_totals"]:
        print(f"  {item['division_code']}: 차변 {item['debit_count']}건 {item['debit_total']:,} · "
              f"대변 {item['credit_count']}건 {item['credit_total']:,}")
    print("계좌별:")
    for row in report["rows"]:
        label = row["nickname"] or row["partner_name"] or row["acct_no"] or "?"
        dep, wd = row["deposit"], row["withdrawal"]
        print(f"  {row['day']} {label:16} [{STATUS_TEXT[row['status']]}] 입금 {dep['bank_total']:,}/{dep['voucher_total']:,} "
              f"출금 {wd['bank_total']:,}/{wd['voucher_total']:,} 회계단위 {','.join(row['divisions']) or '-'}")
        if args.detail:
            for side_name, side in (("입금", dep), ("출금", wd)):
                for item in side["unmatched_bank"]:
                    print(f"      은행 {side_name} {item['amount']:>13,} {item['jeokyo']} | {item['memo']}")
                for item in side["unmatched_lines"]:
                    print(f"      전표 {side_name} {item['amount']:>13,} {item['voucher_no']}/{item['line_no']} "
                          f"{item['division_code']} {item['remark']} | {item['management_no']}")


if __name__ == "__main__":
    main()
