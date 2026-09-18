"""약식(400) 분할입금 중복 판정과 당일 미발행 전표 이어붙이기."""

import json
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.deposit_outbox import DepositOutbox
from app.models.kb_yak_item import KbYakItem
from app.models.voucher_cache import VoucherCache
from app.services.deposit_vouchers import DepositVoucherService


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for table in (DepositOutbox.__table__, KbYakItem.__table__, VoucherCache.__table__):
        table.create(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _voucher(db, yak_no: str, amount: int, *, day=date(2026, 7, 30), no="00070"):
    db.add(VoucherCache(
        id=len(db.query(VoucherCache).all()) + 1, voucher_date=day, voucher_no=no, line_no="1", division_code="1000",
        management_no=yak_no, debit_credit="4", account_code="4010002", account_name="기타수수료",
        amount=Decimal(amount), remark=f"약식평가수수료 {yak_no}",
    ))
    db.commit()


def _entry(i: int, yak_no: str, amount: int, day=date(2026, 8, 25)):
    return DepositOutbox(
        id=i, unique_field=f"UF{i}", bank_cd="004", acct_no="123",
        tx_day=day, tx_amount=Decimal(amount), jeokyo=f"{yak_no}/대체입금/",
        doc_id=yak_no, voucher_kind="YAK", status="PENDING",
    )


def test_과거_일부입금_전표가_있어도_오늘_잔금은_중복이_아니다(db):
    service = DepositVoucherService(db)
    _voucher(db, "400579202", 2_000)                                          # 7/30 발급수수료류 2,000원
    entry = _entry(1, "400579202", 52_800)
    db.add(entry)
    db.commit()
    assert service._yak_duplicate_reason(entry, Decimal(48_000)) is None


def test_같은_번호의_다른_입금은_배치_이력이_있어도_중복이_아니다(db):
    service = DepositVoucherService(db)
    db.add(KbYakItem(id=1, yak_no="400580090", outbox_id=389, tx_day=date(2026, 8, 12), supply=Decimal(2_000), vat=Decimal(200),
                     branch_name="국민은행 영도", partner_code="0000006473", menu_sq=50372, status="S"))
    entry = _entry(2, "400580090", 52_800)
    db.add(entry)
    db.commit()
    assert service._yak_duplicate_reason(entry, Decimal(48_000)) is None


def test_동일한_outbox_입금만_배치_중복이다(db):
    service = DepositVoucherService(db)
    entry = _entry(389, "400580090", 2_200, day=date(2026, 8, 12))
    db.add(entry)
    db.add(KbYakItem(id=1, yak_no="400580090", outbox_id=389, tx_day=entry.tx_day,
                     supply=Decimal(2_000), vat=Decimal(200), branch_name="국민은행 영도",
                     partner_code="0000006473", menu_sq=50372, status="S"))
    db.commit()
    assert service._yak_duplicate_reason(entry, Decimal(2_000)) == "이미 배치가 전표화한 400번호"


def test_같은날_같은금액의_수기전표만_중복이다(db):
    service = DepositVoucherService(db)
    entry = _entry(3, "400579202", 2_200)
    db.add(entry)
    _voucher(db, "400579202", 2_000, day=entry.tx_day)
    assert service._yak_duplicate_reason(entry, Decimal(2_000)) == "이미 전표 있음(수기 처리 추정) — 관리번호로 확인"


def test_당일_미발행_약식전표_50744의_다음줄을_찾는다(db):
    previous = _entry(744, "400565483", 88_000)
    previous.status = "S"
    previous.menu_sq = 50744
    previous.request_body = json.dumps({"data": [{
        "docuTy": "3", "inDivCd": "1000", "menuSq": 50744,
        "menuLnSq": 2, "acctCd": "4010002", "isuDoc": "약식입금 400565483 외 3건",
    }]}, ensure_ascii=False)
    db.add(previous)
    db.commit()
    service = DepositVoucherService(db)

    class Client:
        def post(self, endpoint, *, json_body, timeout):
            assert endpoint == "/apiproxy/api11A16"
            assert json_body["docuFg"] == "0"
            return {"resultData": [
                {"menuDt": "20260825", "menuSq": 50744,
                 "menuLnSq": line, "docuTy": "3", "isuSq": 0}
                for line in range(1, 10)
            ]}

    service.client = Client()
    assert service._yak_append_target(date(2026, 8, 25), "1000", "1000") == (50744, 10)


def test_발행된_약식전표에는_이어붙이지_않는다(db):
    previous = _entry(744, "400565483", 88_000)
    previous.status = "S"
    previous.menu_sq = 50744
    previous.request_body = json.dumps({"data": [{
        "docuTy": "3", "inDivCd": "1000", "menuSq": 50744,
        "menuLnSq": 2, "acctCd": "4010002", "isuDoc": "약식입금 400565483 외 3건",
    }]}, ensure_ascii=False)
    db.add(previous)
    db.commit()
    service = DepositVoucherService(db)

    class Client:
        def post(self, endpoint, *, json_body, timeout):
            return {"resultData": [{
                "menuDt": "20260825", "menuSq": 50744,
                "menuLnSq": 9, "docuTy": "3", "isuSq": 123,
            }]}

    service.client = Client()
    assert service._yak_append_target(date(2026, 8, 25), "1000", "1000") is None
