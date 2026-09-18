"""전표 캐시 수동/스케줄러 실행 진입점."""

import argparse
from datetime import date, timedelta

from app.services.voucher_sync_runner import (
    VoucherSyncAlreadyRunning,
    execute_voucher_sync,
)

MAX_DAYS = 365


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("날짜는 YYYY-MM-DD 형식이어야 합니다.") from exc


def _resolve_period(args: argparse.Namespace, today: date) -> tuple[date, date]:
    if args.date_from is not None or args.date_to is not None:
        if args.date_from is None or args.date_to is None:
            raise ValueError("--date-from과 --date-to를 함께 입력하세요.")
        date_from, date_to = args.date_from, args.date_to
    else:
        days = args.days if args.days is not None else 30
        if days < 1 or days > MAX_DAYS:
            raise ValueError(f"--days는 1~{MAX_DAYS} 사이여야 합니다.")
        date_to = today
        date_from = date_to - timedelta(days=days - 1)

    if date_from > date_to:
        raise ValueError("시작일은 종료일보다 늦을 수 없습니다.")
    if (date_to - date_from).days + 1 > MAX_DAYS:
        raise ValueError(f"한 번에 동기화할 수 있는 기간은 최대 {MAX_DAYS}일입니다.")
    return date_from, date_to


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int)
    parser.add_argument("--date-from", type=_parse_date)
    parser.add_argument("--date-to", type=_parse_date)
    parser.add_argument(
        "--monthly-chunks",
        action="store_true",
        help="긴 기간을 달력 월 단위로 나누고 요약은 마지막에 한 번만 재집계",
    )
    parser.add_argument(
        "--partial-summary",
        action="store_true",
        help="전표가 바뀐 감정서만 요약 재집계 (짧은 주기 배치용, 전체 재집계보다 빠름)",
    )
    args = parser.parse_args()
    try:
        date_from, date_to = _resolve_period(args, date.today())
        result = execute_voucher_sync(
            date_from,
            date_to,
            monthly_chunks=args.monthly_chunks,
            partial_summary=args.partial_summary,
        )
    except (ValueError, VoucherSyncAlreadyRunning) as exc:
        # 예약 작업이 장기 동기화와 겹친 경우 실패로 쌓지 않고 이번 회차만 건너뛴다.
        print(f"전표 캐시 동기화 건너뜀: {exc}")
        return
    print(f"전표 캐시 동기화 완료: {result}")


if __name__ == "__main__":
    main()
