"""상여 원장·마감 표 (2단계 11) — 공제 원장·오버라이드·마감·결과 스냅샷의 읽기 쪽.

같은 감정서를 두 달에 두 번 지급하지 않으려면 **마감된** 결과만 기지급으로 센다.
미납비이월은 전월이 마감돼 있을 때만 자동으로 들어온다(없으면 None → 화면 경고).
"""

import sqlite3
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import BonusClose, BonusDeduction, BonusOverride, BonusResult
from app.services.bonus import closing

sqlite3.register_adapter(date, lambda value: value.isoformat())

ROOT = Path(__file__).resolve().parents[1]
SQL = ROOT / "scripts" / "sql" / "20260901_create_bonus_ledger.sql"


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", future=True, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[
        BonusClose.__table__, BonusResult.__table__, BonusDeduction.__table__, BonusOverride.__table__,
    ])
    session = sessionmaker(bind=engine, future=True)()
    try:
        yield session
    finally:
        session.close()


def _close(db, period, status, source="MOA"):
    db.add(BonusClose(period=period, status=status, source=source))


def _result(db, period, person, doc_id=None, fee=0, unpaid_carry_out=None, kind="SHAREHOLDER"):
    db.add(BonusResult(period=period, person=person, kind=kind, doc_id=doc_id, fee=fee,
                       unpaid_carry_out=unpaid_carry_out, source="MOA"))


def test_마이그레이션_SQL은_네_표와_유니크를_만든다():
    sql = SQL.read_text(encoding="utf-8")
    for table in ("a10_bonus_deduction", "a10_bonus_override", "a10_bonus_close", "a10_bonus_result"):
        assert f"CREATE TABLE dbo.{table}" in sql
    assert "UX_a10_bonus_override" in sql and "IX_a10_bonus_result_doc" in sql
    assert sql.count("NOT EXISTS (SELECT 1 FROM sys.indexes") >= 2
    assert "THROW 5001" in sql


def test_기간_계산은_지급월에서_입금월을_뺀다():
    assert closing.prev_period("202608") == "202607"
    assert closing.prev_period("202601") == "202512"
    assert closing.period_bounds("202608") == (date(2026, 7, 1), date(2026, 7, 31))
    assert closing.period_bounds("202603") == (date(2026, 2, 1), date(2026, 2, 28))
    with pytest.raises(ValueError):
        closing.period_bounds("2026-08")


def test_기지급은_마감된_기간의_행만_센다(db):
    _close(db, "202607", "CLOSED")
    _close(db, "202608", "OPEN")
    _result(db, "202607", "안창덕", "01-2603-1-0155", fee=255_600)
    _result(db, "202607", "이덕권", "01-2603-1-0155", fee=28_400)
    _result(db, "202607", "안창덕", None, fee=0)                 # 사람 합계 행은 제외
    _result(db, "202608", "안창덕", "01-2603-1-0155", fee=100)   # 아직 열린 달
    _result(db, "202606", "안창덕", "01-2603-1-0156", fee=1)     # 마감 행 자체가 없는 달
    db.commit()
    paid = closing.already_paid(db, ["01-2603-1-0155", "01-2603-1-0156", "없음"])
    assert paid == {("01-2603-1-0155", "안창덕"): 255_600, ("01-2603-1-0155", "이덕권"): 28_400}
    assert closing.already_paid(db, []) == {}


def test_미납비이월은_전월이_마감돼_있을_때만_들어온다(db):
    assert closing.carry_in(db, "202608") is None
    _close(db, "202607", "OPEN")
    _result(db, "202607", "권오억", None, unpaid_carry_out=-2_693_660)
    db.commit()
    assert closing.carry_in(db, "202608") is None                # 열려 있으면 아직 확정이 아니다
    db.get(BonusClose, "202607").status = "CLOSED"
    _result(db, "202607", "강무진", None, unpaid_carry_out=0)
    _result(db, "202607", "김동하", "01-2606-3-1813", unpaid_carry_out=-999)   # 행 단위 값은 무시
    db.commit()
    assert closing.carry_in(db, "202608") == {"권오억": 2_693_660, "강무진": 0}


def test_마감_상태를_묻는다(db):
    assert closing.close_status(db, "202608") is None
    _close(db, "202608", "CLOSED", source="EXCEL")
    db.commit()
    assert closing.close_status(db, "202608") == "CLOSED"
    assert closing.close_source(db, "202608") == "EXCEL"


def test_공제_원장과_오버라이드는_리포트가_쓰는_모양으로_읽는다(db):
    from app.services.bonus import ledger

    db.add(BonusDeduction(person="강무진", kind="WREATH", amount=20_000, memo="화환", status="APPLIED", applied_period="202608"))
    db.add(BonusDeduction(person="강무진", kind="DOC_EXPENSE", amount=40_000, doc_id="01-2604-1-0252", status="APPLIED", applied_period="202608"))
    db.add(BonusDeduction(person="강무진", kind="WREATH", amount=1, status="APPLIED", applied_period="202607"))
    db.add(BonusDeduction(person="강무진", kind="WREATH", amount=2, status="PENDING"))
    db.add(BonusOverride(period="202608", doc_id="01-2604-3-1076", person="유승민", action="INCLUDE"))
    db.add(BonusOverride(period="202608", doc_id="01-2606-6-0406", person="김기석", action="RATE", value=4))
    db.commit()
    loaded = ledger.load_deductions(db, "202608")
    assert {name: [{k: v for k, v in item.items() if k != "item_id"} for item in items] for name, items in loaded.items()} == {"강무진": [
        {"kind": "WREATH", "amount": 20_000, "doc_id": None, "memo": "화환"},
        {"kind": "DOC_EXPENSE", "amount": 40_000, "doc_id": "01-2604-1-0252", "memo": None},
    ]}
    assert all(item["item_id"] for item in loaded["강무진"])
    assert ledger.load_overrides(db, "202608") == {
        ("01-2604-3-1076", "유승민"): {"INCLUDE": None},
        ("01-2606-6-0406", "김기석"): {"RATE": 4.0},
    }
    assert ledger.load_deductions(db, "202609") == {} and ledger.load_overrides(db, "202609") == {}
