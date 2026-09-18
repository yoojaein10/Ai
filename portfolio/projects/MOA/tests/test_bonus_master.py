"""상여 마스터 3표(사람·요율·지분) — 모델·SQL·저장 규칙 (1단계 3·4).

저장은 ledger_mail.save_recipients 와 같은 replace-all: 넘어온 목록이 곧 현재 상태고,
빠진 행은 지우지 않고 active='N' 으로 남긴다(누가 언제 빠졌는지 남아야 한다).
"""

import sqlite3
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import BonusPerson, BonusRate, BonusShare
from app.services.bonus import persons, schedule, shares
from app.services.bonus.schedule import BonusMasterError

sqlite3.register_adapter(date, lambda value: value.isoformat())

ROOT = Path(__file__).resolve().parents[1]
SQL = ROOT / "scripts" / "sql" / "20260826_create_bonus_master.sql"


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine, tables=[BonusPerson.__table__, BonusRate.__table__, BonusShare.__table__]
    )
    session = sessionmaker(bind=engine, future=True)()
    try:
        yield session
    finally:
        session.close()


# ── 모델 ────────────────────────────────────────────────────────────────

def test_사람_표_기본값은_주주_전액_30퍼센트다(db):
    db.add(BonusPerson(person="강무진", kind="SHAREHOLDER"))
    db.commit()
    row = db.get(BonusPerson, "강무진")
    db.refresh(row)
    assert (float(row.pay_ratio), float(row.tax_rate), row.active) == (1.0, 0.30, "Y")


def test_마이그레이션_SQL은_세_표와_조건부_인덱스를_만든다():
    sql = SQL.read_text(encoding="utf-8")
    for table in ("a10_bonus_person", "a10_bonus_rate", "a10_bonus_share"):
        assert f"CREATE TABLE dbo.{table}" in sql
    assert "UX_a10_bonus_share_doc_person" in sql and "WHERE active = 'Y'" in sql
    assert "IX_a10_bonus_rate_person" in sql
    # 재배포 create_all 이 먼저 표를 만들어 놓아도 인덱스를 채운다
    assert sql.count("NOT EXISTS (SELECT 1 FROM sys.indexes") >= 2
    assert "THROW 5001" in sql
    assert "CK_a10_bonus_person_kind" in sql


# ── 사람 ────────────────────────────────────────────────────────────────

def test_사람_저장은_목록_그대로_맞추고_빠진_사람은_비활성으로_남긴다(db):
    saved = persons.save_persons(db, [
        {"person": "강무진", "kind": "SHAREHOLDER"},
        {"person": "김기도", "kind": "ASSOCIATE", "pay_ratio": 0.7, "tax_rate": 0.15},
        {"person": "김기도", "kind": "ASSOCIATE"},   # 같은 사람 두 번 → 하나로
    ], usr_seq=7)
    assert [(p["person"], p["kind"], p["pay_ratio"], p["tax_rate"]) for p in saved] == [
        ("강무진", "SHAREHOLDER", 1.0, 0.30), ("김기도", "ASSOCIATE", 0.7, 0.15),
    ]

    persons.save_persons(db, [{"person": "강무진", "kind": "SHAREHOLDER"}], usr_seq=7)
    assert [p["person"] for p in persons.list_persons(db)] == ["강무진"]
    assert db.get(BonusPerson, "김기도").active == "N"          # 지우지 않는다

    revived = persons.save_persons(db, [
        {"person": "강무진", "kind": "SHAREHOLDER"},
        {"person": "김기도", "kind": "ASSOCIATE", "pay_ratio": 1.0, "tax_rate": 0.15},
    ], usr_seq=8)
    assert [p["person"] for p in revived] == ["강무진", "김기도"]
    assert db.get(BonusPerson, "김기도").active == "Y"
    assert db.get(BonusPerson, "김기도").updated_by_usr_seq == 8


def test_사람_값이_규칙에_어긋나면_저장하지_않는다(db):
    with pytest.raises(BonusMasterError):
        persons.save_persons(db, [{"person": "강무진", "kind": "임원"}], usr_seq=1)
    with pytest.raises(BonusMasterError):
        persons.save_persons(db, [{"person": "강무진", "kind": "ASSOCIATE", "pay_ratio": 1.5}], usr_seq=1)
    with pytest.raises(BonusMasterError):
        persons.save_persons(db, [{"person": " ", "kind": "ASSOCIATE"}], usr_seq=1)
    assert persons.list_persons(db) == []


# ── 요율 ────────────────────────────────────────────────────────────────

def test_요율_저장은_사람_단위_replace_all_이고_겹치면_거부한다(db):
    rows = [
        {"from_date": date(2025, 7, 7), "to_date": None, "rate": 40, "label": "2025년 7월 7일 접수분~"},
        {"from_date": date(2022, 7, 1), "to_date": date(2025, 7, 6), "rate": 30, "label": "2022년 7월~ 2025년 7월 6일 접수분까지"},
    ]
    saved = schedule.save_rates(db, "노승환", rows, usr_seq=7)
    assert [(r["from_date"], r["to_date"], r["rate"]) for r in saved] == [
        (date(2022, 7, 1), date(2025, 7, 6), 30.0), (date(2025, 7, 7), None, 40.0),
    ]
    blocks = schedule.load_schedule(db)["노승환"]
    assert [b.rate for b in blocks] == [30.0, 40.0]
    assert schedule.rate_for(blocks, date(2025, 7, 7)) == (40.0, date(2025, 7, 7), "SCHEDULE")

    with pytest.raises(BonusMasterError):
        schedule.save_rates(db, "노승환", [
            {"from_date": date(2022, 7, 1), "to_date": None, "rate": 30},
            {"from_date": date(2024, 7, 1), "to_date": None, "rate": 40},
        ], usr_seq=7)
    assert [b.rate for b in schedule.load_schedule(db)["노승환"]] == [30.0, 40.0]  # 그대로

    schedule.save_rates(db, "노승환", [{"from_date": date(2025, 7, 7), "to_date": None, "rate": 40}], usr_seq=7)
    assert [b.rate for b in schedule.load_schedule(db)["노승환"]] == [40.0]
    assert sum(1 for r in db.query(BonusRate).all() if r.active == "N") == 1


def test_요율은_0_초과_100_이하만_받는다(db):
    with pytest.raises(BonusMasterError):
        schedule.save_rates(db, "노승환", [{"from_date": None, "to_date": None, "rate": 0}], usr_seq=1)
    with pytest.raises(BonusMasterError):
        schedule.save_rates(db, "노승환", [{"from_date": None, "to_date": None, "rate": 140}], usr_seq=1)


# ── 지분 ────────────────────────────────────────────────────────────────

def test_지분_저장은_감정서_단위이고_합이_100이_아니어도_경고만_한다(db):
    saved = shares.save_shares(db, "01-2603-1-0155", [
        {"person": "안창덕", "share_pct": 90}, {"person": "이덕권", "share_pct": 10},
    ], usr_seq=7)
    assert [(r["person"], r["share_pct"], r["bc_pct"], r["source"]) for r in saved["items"]] == [
        ("안창덕", 90.0, None, "MANUAL"), ("이덕권", 10.0, None, "MANUAL"),
    ]
    assert (saved["total"], saved["warning"]) == (100.0, False)

    joint = shares.save_shares(db, "01-2606-3-2029", [{"person": "신상우", "share_pct": 50}], usr_seq=7)
    assert (joint["total"], joint["warning"]) == (50.0, True)          # 공동유치 50% 인정

    card = shares.save_shares(db, "01-2607-3-0001", [{"person": "안창덕", "share_pct": 60, "bc_pct": 100}], usr_seq=7, source="SEED")
    assert (card["items"][0]["bc_pct"], card["items"][0]["source"]) == (100.0, "SEED")

    loaded = shares.load_shares(db, ["01-2603-1-0155", "01-2606-3-2029", "없음"])
    assert loaded["01-2603-1-0155"]["안창덕"]["share_pct"] == 90.0
    assert loaded["01-2606-3-2029"] == {"신상우": {"share_pct": 50.0, "bc_pct": None, "source": "MANUAL", "note": None}}
    assert "없음" not in loaded

    shares.save_shares(db, "01-2603-1-0155", [{"person": "안창덕", "share_pct": 100}], usr_seq=7)
    assert list(shares.load_shares(db, ["01-2603-1-0155"])["01-2603-1-0155"]) == ["안창덕"]
    assert sum(1 for r in db.query(BonusShare).all() if r.active == "N") == 1


def test_지분_값이_규칙에_어긋나면_저장하지_않는다(db):
    with pytest.raises(BonusMasterError):
        shares.save_shares(db, "01-2603-1-0155", [{"person": "안창덕", "share_pct": 0}], usr_seq=1)
    with pytest.raises(BonusMasterError):
        shares.save_shares(db, "01-2603-1-0155", [{"person": "안창덕", "share_pct": 150}], usr_seq=1)
    with pytest.raises(BonusMasterError):
        shares.save_shares(db, "", [{"person": "안창덕", "share_pct": 50}], usr_seq=1)
    assert shares.load_shares(db, ["01-2603-1-0155"]) == {}
