"""공제 대장 — 발생(PENDING) → 이번 달 적용(APPLIED) → 마감 잠금 / 상여 0 이면 다시 대기(이월)."""

import sqlite3
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import BonusClose, BonusDeduction
from app.services.bonus import deduction_items as items
from app.services.bonus.ledger import load_deductions
from app.services.bonus.schedule import BonusMasterError

sqlite3.register_adapter(date, lambda value: value.isoformat())


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", future=True, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[BonusClose.__table__, BonusDeduction.__table__])
    session = sessionmaker(bind=engine, future=True)()
    try:
        yield session
    finally:
        session.close()


def _wreath(db, person="강무진", amount=80_000, **extra):
    return items.create_item(db, {"person": person, "kind": "WREATH", "amount": amount, "occurred_on": date(2026, 8, 12), "memo": "화환", **extra}, usr_seq=7)


def test_등록하면_대기이고_지급월을_주면_바로_적용된다(db):
    pending = _wreath(db)
    assert pending["status"] == "PENDING" and pending["applied_period"] is None and pending["source"] == "MANUAL"
    applied = _wreath(db, amount=20_000, apply_period="202609")
    assert applied["status"] == "APPLIED" and applied["applied_period"] == "202609"
    assert [i["amount"] for i in items.list_items(db, person="강무진", status="PENDING")] == [80_000]
    assert load_deductions(db, "202609") == {"강무진": [{"item_id": applied["item_id"], "kind": "WREATH", "amount": 20_000, "doc_id": None, "memo": "화환"}]}
    with pytest.raises(BonusMasterError):
        items.create_item(db, {"person": "강무진", "kind": "화환", "amount": 1}, usr_seq=7)
    with pytest.raises(BonusMasterError):
        items.create_item(db, {"person": "강무진", "kind": "WREATH", "amount": -1}, usr_seq=7)


def test_적용_집합을_통째로_바꾼다_빠진_것은_대기로_돌아간다(db):
    a, b, c = _wreath(db, amount=1), _wreath(db, amount=2), _wreath(db, amount=3)
    items.set_applied(db, "202609", "강무진", [a["item_id"], b["item_id"]], usr_seq=7)
    assert {i["item_id"] for i in items.list_items(db, period="202609")} == {a["item_id"], b["item_id"]}
    items.set_applied(db, "202609", "강무진", [b["item_id"], c["item_id"]], usr_seq=7)
    by_id = {i["item_id"]: i["status"] for i in items.list_items(db, person="강무진")}
    assert by_id == {a["item_id"]: "PENDING", b["item_id"]: "APPLIED", c["item_id"]: "APPLIED"}
    other = _wreath(db, person="김형식")
    with pytest.raises(BonusMasterError):
        items.set_applied(db, "202609", "강무진", [other["item_id"]], usr_seq=7)           # 남의 항목
    items.set_applied(db, "202610", "강무진", [a["item_id"]], usr_seq=7)
    with pytest.raises(BonusMasterError):
        items.set_applied(db, "202609", "강무진", [a["item_id"]], usr_seq=7)               # 다른 달에 이미 적용
    db.add(BonusClose(period="202609", status="CLOSED", source="MOA")); db.commit()
    with pytest.raises(BonusMasterError):
        items.set_applied(db, "202609", "강무진", [], usr_seq=7)                            # 마감된 달


def test_분할은_대기만_되고_금액을_지키고_출처_키는_원본에_남는다(db):
    """2026-08-27 사용자 결정 — 엑셀 미수금 탭의 부분 회수(273,500 중 4,000만 이번 달) 방식."""
    original = items.create_item(db, {
        "person": "정인수", "kind": "OTHER_DEDUCT", "amount": 273_500, "occurred_on": date(2026, 3, 16),
        "memo": "캐슬렉스서울", "source": "EXCEL", "source_key": "misu:20260316:정인수:273500",
    }, usr_seq=7)
    result = items.split_item(db, original["item_id"], 4_000, usr_seq=7)
    assert result["split"]["amount"] == 4_000 and result["split"]["status"] == "PENDING"
    assert result["remainder"]["item_id"] == original["item_id"] and result["remainder"]["amount"] == 269_500
    assert result["split"]["source_key"] is None                        # 유니크 키 충돌 방지 — 키는 원본에만
    assert result["remainder"]["source_key"] == "misu:20260316:정인수:273500"
    assert result["split"]["kind"] == "OTHER_DEDUCT" and result["split"]["person"] == "정인수"
    assert "분할" in result["split"]["memo"] and "남음" in result["remainder"]["memo"]
    for bad in (0, -1, 269_500, 999_999):                               # 0 이하·전액 이상은 나눌 게 없다
        with pytest.raises(BonusMasterError):
            items.split_item(db, original["item_id"], bad, usr_seq=7)
    applied = _wreath(db, apply_period="202609")
    with pytest.raises(BonusMasterError):
        items.split_item(db, applied["item_id"], 1_000, usr_seq=7)      # 적용된 항목은 먼저 대기로


def test_수정은_대기만_무효는_사유가_있어야_하고_마감된_적용은_못_건드린다(db):
    pending = _wreath(db)
    updated = items.update_item(db, pending["item_id"], {"amount": 90_000, "memo": "화환(수정)"}, usr_seq=7)
    assert updated["amount"] == 90_000 and updated["memo"] == "화환(수정)"
    applied = _wreath(db, apply_period="202609")
    with pytest.raises(BonusMasterError):
        items.update_item(db, applied["item_id"], {"amount": 1}, usr_seq=7)
    with pytest.raises(BonusMasterError):
        items.void_item(db, applied["item_id"], "", usr_seq=7)
    voided = items.void_item(db, applied["item_id"], "잘못 등록", usr_seq=7)
    assert voided["status"] == "VOID" and voided["void_reason"] == "잘못 등록" and voided["applied_period"] is None
    locked = _wreath(db, apply_period="202610")
    db.add(BonusClose(period="202610", status="CLOSED", source="MOA")); db.commit()
    with pytest.raises(BonusMasterError):
        items.void_item(db, locked["item_id"], "늦었다", usr_seq=7)


def test_상여가_0이라_못_뺀_화환은_다시_대기로_돌아간다(db):
    wreath = _wreath(db, apply_period="202609")
    doc_expense = items.create_item(db, {"person": "강무진", "kind": "DOC_EXPENSE", "amount": 40_000, "doc_id": "01-2604-1-0252"}, usr_seq=7, apply_period="202609")
    reverted = items.revert_unconsumed(db, "202609", ["강무진"], usr_seq=7)
    assert reverted == [wreath["item_id"]]
    after = {i["item_id"]: i for i in items.list_items(db, person="강무진")}
    assert after[wreath["item_id"]]["status"] == "PENDING" and "202609" in after[wreath["item_id"]]["memo"]
    assert after[doc_expense["item_id"]]["status"] == "APPLIED"                          # 감정서경비는 Q 단계라 그대로


def test_경비_전표는_감정서_사람들의_대기_후보가_되고_두_번_올리지_않는다(db):
    rows = [
        {"key": "20260806:00012:1", "voucher_date": date(2026, 8, 6), "account_name": "세금과공과금", "amount": 20_000,
         "remark": "01-2606-5-0094 수입인지-성지연", "doc_ids": ["01-2606-5-0094"]},
        {"key": "20260807:00013:2", "voucher_date": date(2026, 8, 7), "account_name": "도서인쇄비", "amount": 30_000,
         "remark": "제본 01-2607-3-0001/01-2607-3-0002", "doc_ids": ["01-2607-3-0001", "01-2607-3-0002"]},
        {"key": "20260810:00014:1", "voucher_date": date(2026, 8, 10), "account_name": "세금과공과금", "amount": 10_068_920,
         "remark": "26.7월분 주민세 종업원분", "doc_ids": []},                               # 감정서도 사람도 없음 → 후보 아님
        {"key": "20260811:00015:1", "voucher_date": date(2026, 8, 11), "account_name": "세금과공과금", "amount": 20_000,
         "remark": "수택동 재개발정비사업조합 수입인지-김형식", "doc_ids": [], "persons": ["김형식"]},   # 감정서 없이 사람만
    ]
    ratios = {("01-2606-5-0094", "성지연"): 100, ("01-2607-3-0001", "강무진"): 50, ("01-2607-3-0001", "정인수"): 50, ("01-2607-3-0002", "김형식"): 100}
    created = items.sync_voucher_candidates(db, rows, ratios)
    assert [(i["person"], i["doc_id"], i["amount"], i["status"], i["source"]) for i in created] == [
        ("성지연", "01-2606-5-0094", 20_000, "PENDING", "VOUCHER"),
        ("강무진", "01-2607-3-0001", 7_500, "PENDING", "VOUCHER"),        # 30,000 ÷ 감정서 2 × 지분 50%
        ("정인수", "01-2607-3-0001", 7_500, "PENDING", "VOUCHER"),
        ("김형식", "01-2607-3-0002", 15_000, "PENDING", "VOUCHER"),
        ("김형식", None, 20_000, "PENDING", "VOUCHER"),                     # 감정서 없는 사람 몫
    ]
    assert created[4]["source_key"] == "vch:20260811:00015:1::김형식"
    assert created[0]["memo"] == "세금과공과금 01-2606-5-0094 수입인지-성지연" and created[0]["occurred_on"] == date(2026, 8, 6)
    assert items.sync_voucher_candidates(db, rows, ratios) == []                                   # 멱등
    # 엑셀·수기로 이미 같은 (사람, 감정서, 금액)이 있으면 전표 후보를 또 만들지 않는다
    items.create_item(db, {"person": "박용준", "kind": "DOC_EXPENSE", "amount": 70_000, "doc_id": "01-2605-3-0781", "source": "EXCEL", "source_key": "doc:26.08:698"})
    twin_rows = [{"key": "20260715:00099:1", "voucher_date": date(2026, 7, 15), "account_name": "세금과공과금", "amount": 70_000, "remark": "01-2605-3-0781 전자수입인지", "doc_ids": ["01-2605-3-0781"]}]
    assert items.sync_voucher_candidates(db, twin_rows, {("01-2605-3-0781", "박용준"): 100}) == []
    assert items.pending_summary(db)["성지연"] == {"count": 1, "amount": 20_000}


def test_감정서_공제_전표_후보는_열린_달에_바로_적용된다(db):
    """재무팀 규칙 1: 감정서 관련 공제는 감정서번호와 상관없이 전부 뺀다 → 후보를 만들면서 적용. 마감된 달이면 대기."""
    row = {"key": "20260806:00012:1", "voucher_date": date(2026, 8, 6), "account_name": "세금과공과금", "amount": 20_000,
           "remark": "01-2606-5-0094 수입인지-성지연", "doc_ids": ["01-2606-5-0094"]}
    created = items.sync_voucher_candidates(db, [row], {("01-2606-5-0094", "성지연"): 100}, apply_period="202609")
    assert created[0]["status"] == "APPLIED" and created[0]["applied_period"] == "202609"
    assert load_deductions(db, "202609")["성지연"][0]["amount"] == 20_000
    db.add(BonusClose(period="202608", status="CLOSED", source="EXCEL")); db.commit()
    closed_row = {**row, "key": "20260706:00001:1", "remark": "01-2605-5-0076 수입인지-유승민", "doc_ids": ["01-2605-5-0076"]}
    created = items.sync_voucher_candidates(db, [closed_row], {("01-2605-5-0076", "유승민"): 100}, apply_period="202608")
    assert created[0]["status"] == "PENDING" and created[0]["applied_period"] is None


def test_같은_출처_키는_두_번_넣지_않는다(db):
    first = items.create_item(db, {"person": "강무진", "kind": "DOC_EXPENSE", "amount": 20_000, "source": "EXCEL", "source_key": "doc:26.08:715"}, usr_seq=None)
    again = items.create_item(db, {"person": "강무진", "kind": "DOC_EXPENSE", "amount": 99, "source": "EXCEL", "source_key": "doc:26.08:715"}, usr_seq=None)
    assert again["item_id"] == first["item_id"] and again["amount"] == 20_000 and again["skipped"] is True
    assert items.pending_summary(db) == {"강무진": {"count": 1, "amount": 20_000}}
