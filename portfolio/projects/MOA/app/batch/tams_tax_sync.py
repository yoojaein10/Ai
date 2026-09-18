"""TAMS 세금계산서(부가세.DB) 동기화 수동/스케줄러 실행 진입점."""

import argparse

from app.database import get_session_factory
from app.services.tams_tax_sync import DEFAULT_SOURCE, sync_tams_tax


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    args = parser.parse_args()
    with get_session_factory()() as db:
        result = sync_tams_tax(db, source_path=args.source)
    print(f"TAMS 세금계산서 동기화 완료: {result}")


if __name__ == "__main__":
    main()
