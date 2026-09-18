"""A10-Bridge SQLAlchemy 테이블을 생성하고 안전한 호환 마이그레이션을 적용한다."""

from pathlib import Path

from sqlalchemy import text

from app.database import Base, get_engine
from app.models import ApiLog  # noqa: F401 - metadata 등록 목적


_SQL_DIR = Path(__file__).resolve().parent / "sql"
_COMPATIBLE_MIGRATIONS = (
    "20260825_widen_deposit_outbox_voucher_kind.sql",
    "20260825_allow_partial_kb_yak.sql",
    "20260826_bank_account_map_reconcile_only.sql",
)


def _apply_compatible_migrations() -> None:
    engine = get_engine()
    with engine.begin() as connection:
        for name in _COMPATIBLE_MIGRATIONS:
            connection.execute(text((_SQL_DIR / name).read_text(encoding="utf-8")))
            print(f"A10-Bridge 호환 마이그레이션 완료: {name}")


def main() -> None:
    Base.metadata.create_all(bind=get_engine())
    _apply_compatible_migrations()
    print("A10-Bridge 테이블 생성 완료")


if __name__ == "__main__":
    main()
