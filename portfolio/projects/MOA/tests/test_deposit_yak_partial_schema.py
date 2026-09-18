"""400 약식 분할입금 스키마와 배포 마이그레이션 회귀 검사."""

from pathlib import Path

from app.models.kb_yak_item import KbYakItem


ROOT = Path(__file__).resolve().parent.parent


def test_약식원장은_번호가_아니라_개별입금이_unique다():
    table = KbYakItem.__table__
    unique_sets = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("outbox_id",) in unique_sets
    assert ("yak_no",) not in unique_sets


def test_재배포가_분할입금_마이그레이션을_자동적용한다():
    create_tables = (ROOT / "scripts" / "create_tables.py").read_text(encoding="utf-8")
    migration_name = "20260825_allow_partial_kb_yak.sql"
    assert migration_name in create_tables
    sql = (ROOT / "scripts" / "sql" / migration_name).read_text(encoding="utf-8")
    assert "DROP CONSTRAINT" in sql or "DROP INDEX" in sql
    assert "outbox_id" in sql and "CREATE UNIQUE INDEX" in sql
    assert "EXEC sys.sp_executesql @ddl" in sql
    assert "EXEC(N'" not in sql
