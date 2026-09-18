"""팝빌 → 발급 원장 동기화 수동/스케줄러 실행 진입점 (2026-09-09).

  python -m app.batch.popbill_sync              # 최근 14일
  python -m app.batch.popbill_sync --days 30 --dry-run
"""

import argparse
import json

from app.database import get_session_factory
from app.services.popbill_sync import sync_popbill


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    with get_session_factory()() as db:
        result = sync_popbill(db, days=args.days, dry_run=args.dry_run)
    print("팝빌 동기화 완료:", json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
