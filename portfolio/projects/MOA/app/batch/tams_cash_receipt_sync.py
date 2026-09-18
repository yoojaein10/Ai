"""TAMS 현금영수증(TAX_CASH.DB) 동기화 수동 실행 진입점."""

import argparse

from app.database import get_session_factory
from app.services.tams_cash_receipt_sync import DEFAULT_SOURCE, sync_tams_cash_receipts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    args = parser.parse_args()
    with get_session_factory()() as db:
        result = sync_tams_cash_receipts(db, source_path=args.source)
    print(f"TAMS 현금영수증 동기화 완료: {result}")


if __name__ == "__main__":
    main()

