"""CB2 입금 → 아마란스 전표 배치 진입점.

기본은 수집·분류만 한다(전송 없음). 실제 전송은 --send를 명시해야 한다.
약식(400) 묶음전표는 하루 1장을 유지하려고 --include-yak 회차(17시 1회
예약)에서만 전송한다 — 매시간 회차는 반제·일반만 보낸다.

  python -m app.batch.deposit_voucher_sync --days 3                 # 분류만
  python -m app.batch.deposit_voucher_sync --days 7 --send          # 반제·일반 전송
  python -m app.batch.deposit_voucher_sync --days 7 --send --include-yak  # +약식 묶음
  python -m app.batch.deposit_voucher_sync \
      --date-from 2026-05-01 --date-to 2026-08-04 --legacy          # 도입 백필
"""

import argparse
from datetime import date, timedelta

from app.database import get_session_factory
from app.services.deposit_vouchers import DepositVoucherService


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("날짜는 YYYY-MM-DD 형식이어야 합니다.") from exc


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--date-from", type=_parse_date)
    parser.add_argument("--date-to", type=_parse_date)
    parser.add_argument("--send", action="store_true", help="PENDING 건을 실제 전송")
    parser.add_argument(
        "--include-yak", action="store_true",
        help="약식(400) 묶음전표도 전송 — 하루 1장 유지를 위해 17시 회차에만",
    )
    parser.add_argument(
        "--legacy", action="store_true",
        help="감정서번호 건도 LEGACY(기존처리)로 기록 — 도입 시점 백필용",
    )
    # 보류(수기 중복 등)가 PENDING에 쌓여도 신규가 창에 들어오도록 여유 있게.
    parser.add_argument("--send-limit", type=int, default=200)
    args = parser.parse_args()

    if (args.date_from is None) != (args.date_to is None):
        raise SystemExit("--date-from과 --date-to는 함께 입력하세요.")
    if args.date_from:
        date_from, date_to = args.date_from, args.date_to
    else:
        date_to = date.today()
        date_from = date_to - timedelta(days=args.days - 1)

    with get_session_factory()() as db:
        service = DepositVoucherService(db)
        scanned = service.scan(date_from, date_to, legacy=args.legacy)
        print(
            f"입금 수집 {date_from}~{date_to}: 신규 {scanned['new']}건 "
            f"(전표대상 {scanned['doc']} · 제외 {scanned['excluded']}) · "
            f"기존 {scanned['known']}건(재분류 {scanned['reclassified']})"
        )
        if args.send and not args.legacy:
            sent = service.send_pending(
                limit=args.send_limit, include_yak=args.include_yak
            )
            print(
                f"전표 전송: 성공 {sent['sent']} · 보류 {sent['held']} · "
                f"실패 {sent['failed']} · 약식·지사 이월 {sent['yak_deferred']}"
            )


if __name__ == "__main__":
    main()
