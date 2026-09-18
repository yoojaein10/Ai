"""3단계 — 공제 원장·오버라이드 쓰기, 마감/재개 스냅샷, 총괄표 전표 라인."""

import json
import sqlite3
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import BonusClose, BonusDeduction, BonusOverride, BonusResult
from app.services.bonus import closing, ledger, summary
from app.services.bonus.engine import Row, associate_person, shareholder_person
from app.services.bonus.schedule import BonusMasterError

sqlite3.register_adapter(date, lambda value: value.isoformat())


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


# ── 공제 원장 ───────────────────────────────────────────────────────────

# 공제 입력은 공제 대장(deduction_items)으로 옮겼다 — tests/test_bonus_deduction_items.py


def test_오버라이드는_달_감정서_사람_단위로_통째로_바꾼다(db):
    ledger.set_overrides(db, "202609", "01-2604-3-1076", "유승민", {"INCLUDE": None, "FEE": 580_000}, usr_seq=7)
    ledger.set_overrides(db, "202609", "KB약식", "김형수", {"INCLUDE": None, "FEE": 8_519_000, "WORK": "가격자문"}, usr_seq=7)
    assert ledger.load_overrides(db, "202609") == {
        ("01-2604-3-1076", "유승민"): {"INCLUDE": None, "FEE": 580_000.0},
        ("KB약식", "김형수"): {"INCLUDE": None, "FEE": 8_519_000.0, "WORK": "가격자문"},
    }
    ledger.set_overrides(db, "202609", "01-2604-3-1076", "유승민", {"EXCLUDE": None}, usr_seq=7)
    assert ledger.load_overrides(db, "202609")[("01-2604-3-1076", "유승민")] == {"EXCLUDE": None}
    ledger.set_overrides(db, "202609", "01-2604-3-1076", "유승민", {}, usr_seq=7)
    assert ("01-2604-3-1076", "유승민") not in ledger.load_overrides(db, "202609")
    with pytest.raises(BonusMasterError):
        ledger.set_overrides(db, "202609", "01-2604-3-1076", "유승민", {"RATE": 55}, usr_seq=7)   # 요율은 목록에서만
    with pytest.raises(BonusMasterError):
        ledger.set_overrides(db, "202609", "01-2604-3-1076", "유승민", {"INCLUDE": None, "EXCLUDE": None}, usr_seq=7)


# ── 마감 / 재개 ─────────────────────────────────────────────────────────

def _report():
    kang = shareholder_person([Row(doc_id="01-2607-3-0001", person="강무진", work_type="담보", fee=10_000_000, rate=40, block_from=date(2021, 3, 1))],
                              variable_auto=100_000, deductions=[{"kind": "WREATH", "amount": 20_000}])
    lee = associate_person([Row(doc_id="01-2508-4-0279", person="이영은", kind="COMMON", work_type="일반거래", fee=9_166_600, rate=10)],
                           pay_ratio=0.7, tax_rate=0.30)
    kim = associate_person([Row(doc_id="01-2606-6-0406", person="김기석", kind="COMMON", work_type="가격자문", fee=10_000)], pay_ratio=1.0, tax_rate=0.30)
    kim["kind"] = "COMMON"
    groups = {
        "shareholders": [{"name": "강무진", "retired": False, **kang}],
        "common": [{"name": "김기석", "retired": False, **kim}],
        "associates": [{"name": "이영은", "retired": True, **lee}],
    }
    return {"period": "202609", "perf_month": "202608", "status": "OPEN", **groups,
            "held": [{"doc_id": "01-2604-4-0153", "reason": "HELD_UNPAID"}], "warnings": ["w1"], "expense_notes": [],
            "summary": summary.summarize(groups["shareholders"], groups["common"], groups["associates"])}


def test_마감은_스냅샷을_쓰고_재개는_지운다(db):
    report = _report()
    closed = closing.close_period(db, "202609", report, usr_seq=7)
    assert closed["status"] == "CLOSED" and closed["rows"] == 6            # 행 3 + 사람 합계 3
    assert closing.close_status(db, "202609") == "CLOSED" and closing.close_source(db, "202609") == "MOA"
    snap = closing.snapshot_report(db, "202609")
    assert snap["status"] == "CLOSED" and [p["name"] for p in snap["shareholders"]] == ["강무진"]
    kang = snap["shareholders"][0]
    assert kang["totals"]["payment"] == report["shareholders"][0]["totals"]["payment"]
    assert kang["rows"][0]["doc_id"] == "01-2607-3-0001" and kang["rows"][0]["rate"] == 40
    assert kang["blocks"][0]["rate"] == 40
    assert snap["associates"][0]["retired"] is True and snap["associates"][0]["totals"]["payment"] == 425_900
    assert [row["name"] for row in snap["summary"]] == ["강무진", "김기석", "이영은"]
    assert snap["held"] == report["held"] and snap["warnings"] == ["w1"]
    assert closing.carry_in(db, "202610") == {"강무진": 0.0, "김기석": 0.0, "이영은": 0.0}

    with pytest.raises(BonusMasterError):
        closing.close_period(db, "202609", report, usr_seq=7)                 # 이미 마감
    reopened = closing.reopen_period(db, "202609", usr_seq=8)
    assert reopened["status"] == "OPEN" and closing.close_status(db, "202609") == "OPEN"
    assert closing.load_result(db, "202609") == []
    assert db.get(BonusClose, "202609").reopened_by_usr_seq == 8


def test_엑셀_이력_마감은_재개할_수_없고_마감_전_달이_열려_있으면_경고만_한다(db):
    db.add(BonusClose(period="202608", status="CLOSED", source="EXCEL")); db.commit()
    with pytest.raises(BonusMasterError):
        closing.reopen_period(db, "202608", usr_seq=1)
    closed = closing.close_period(db, "202610", _report() | {"period": "202610"}, usr_seq=1)
    assert any("202609" in w for w in closed["warnings"])                   # 전월(202609)이 마감되지 않았다


# ── 총괄표 · 전표 ────────────────────────────────────────────────────────

def test_총괄표_전표는_임원상여_예수금_미수금_보통예금이다():
    report = _report()
    lines = summary.journal_lines(report["summary"])
    by = {(line["account"], line["side"]): line["amount"] for line in lines}
    total_pretax = sum(row["pretax"] for row in report["summary"])
    assert by[("임원상여", "차변")] == total_pretax
    assert by[("예수금", "대변")] == sum(row["income_tax"] + row["resident_tax"] for row in report["summary"])
    assert by[("미수금", "대변")] == sum(row["other_deduct"] for row in report["summary"])
    assert by[("보통예금", "대변")] == sum(row["payment"] for row in report["summary"])
    assert sum(l["amount"] for l in lines if l["side"] == "차변") == sum(l["amount"] for l in lines if l["side"] == "대변")
