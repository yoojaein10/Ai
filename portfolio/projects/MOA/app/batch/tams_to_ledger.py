"""TAMS 캐시 → 발급 원장(source='TAMS') 반영 진입점 (2026-09-09).

TAMS 동기화(08시·13시) 직후에 돌려 그날 들어온 행을 원장에 붙인다. 내용 기반 해시로
같은 행은 한 번만 들어가므로 언제 몇 번을 돌려도 안전하다.

  python -m app.batch.tams_to_ledger --dry-run
  python -m app.batch.tams_to_ledger
"""

import argparse
import json

from app.database import get_session_factory
from app.services.tams_ledger import sync_tams_to_ledger


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    with get_session_factory()() as db:
        result = sync_tams_to_ledger(db, dry_run=args.dry_run)
    print("TAMS→원장 반영 완료:", json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
