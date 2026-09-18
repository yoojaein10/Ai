from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.deposit_outbox import DepositOutbox
from app.services.deposit_vouchers import (
    DepositVoucherService,
    banje_bundle_lines,
    classify_memo,
    general_lines,
    yak_bundle_lines,
    yak_no_from_jeokyo,
)


def test_memo_분류_규칙():
    assert classify_memo("01-2607-3-2220") == ("DOC", "01-2607-3-2220")
    assert classify_memo(" 01-2607-A-0112 ") == ("DOC", "01-2607-A-0112")
    # '*'는 처리완료 — 감정서번호가 있어도 가져오지 않는다 (사용자 규칙)
    assert classify_memo("01-2604-4-0142 *") == ("STAR", None)
    assert classify_memo("01-2605-5-0070*") == ("STAR", None)
    assert classify_memo("부산지사") == ("BRANCH", None)
    assert classify_memo("가수금") == ("OTHER", None)
    assert classify_memo(None) == ("EMPTY", None)
    assert classify_memo("  ") == ("EMPTY", None)


@pytest.fixture
def outbox_sessions():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    DepositOutbox.__table__.create(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


def _pending(i: int, *, reason: "str | None" = None) -> DepositOutbox:
    # sqlite는 BigInteger PK를 자동 채번하지 않아 id를 직접 준다
    return DepositOutbox(
        id=i + 1,
        unique_field=f"UF{i}", bank_cd="004", acct_no="123",
        tx_day=date(2026, 8, 10), tx_amount=Decimal("1000"),
        doc_id="99-0000", voucher_kind="GENERAL",
        status="PENDING", reason=reason,
    )


def test_send_pending은_시도_안한_신규를_먼저_집는다(outbox_sessions):
    """영구 보류성 건이 limit 창을 차지해 신규가 굶던 회귀 방지(2026-08-11).

    PENDING 86건 > limit 50 상태에서 오래된 '수기 전표 있음' 보류가 id 순서로
    창을 다 차지해, 8/7 이후 신규 35건이 나흘간 시도조차 안 됐다.
    """
    with outbox_sessions() as db:
        for i in range(3):
            db.add(_pending(i, reason="이미 전표 있음(수기 처리 추정)"))
        db.add(_pending(3))
        db.add(_pending(4))
        db.commit()

        counts = DepositVoucherService(db).send_pending(limit=2)

        rows = db.scalars(select(DepositOutbox).order_by(DepositOutbox.id)).all()
        # 신규 2건(3·4)이 먼저 시도돼 사유가 새로 기록된다(01- 외 보류)
        assert all("본사(01-) 외" in (r.reason or "") for r in rows[3:])
        # 오래된 보류 3건은 이번 회차에 손대지 않았다
        assert [r.reason for r in rows[:3]] == ["이미 전표 있음(수기 처리 추정)"] * 3
        assert counts["held"] == 2


def test_반제_묶음전표는_수기_정산전표와_같은_모양():
    # 재무팀 정산 전표 실측(2026-08-06): 감정서별 차·대 쌍, 계좌 혼재 허용
    lines = banje_bundle_lines(
        items=[
            {"doc_id": "01-2607-4-0257", "tx_amount": Decimal("500500"),
             "account_partner": "0000000101",
             "receivable_partner": "0000059118"},
            {"doc_id": "01-2504-3-1119", "tx_amount": Decimal("67100"),
             "account_partner": "0000000202",
             "receivable_partner": "0000012345"},
        ],
        voucher_date=date(2026, 7, 31),
        menu_sq=50007,
        division_code="1000",
    )
    assert [line["acctCd"] for line in lines] == [
        "1030000", "1080000", "1030000", "1080000"
    ]
    assert [line["drcrFg"] for line in lines] == ["3", "4", "3", "4"]
    assert [line["menuLnSq"] for line in lines] == [1, 2, 3, 4]
    assert all(line["docuTy"] == "4" for line in lines)
    assert lines[0]["acctAm"] == lines[1]["acctAm"] == 500500.0
    assert lines[2]["acctAm"] == lines[3]["acctAm"] == 67100.0
    assert lines[0]["rmkDc"] == lines[1]["rmkDc"] == "정산 01-2607-4-0257"
    assert lines[2]["rmkDc"] == "정산 01-2504-3-1119"
    # 관리번호는 외상매출금 라인에만, 계좌 거래처는 건별로 (수기전표 실측)
    assert "maNb" not in lines[0] and "maNb" not in lines[2]
    assert lines[1]["maNb"] == "01-2607-4-0257"
    assert lines[3]["maNb"] == "01-2504-3-1119"
    assert lines[0]["trCd"] == "0000000101"
    assert lines[2]["trCd"] == "0000000202"


def test_일반입금전표_라인과_부가세():
    lines = general_lines(
        doc_id="01-2605-3-1715",
        fee=Decimal("2342000"),
        vat=Decimal("234200"),
        voucher_date=date(2026, 8, 4),
        menu_sq=50011,
        division_code="1000",
        account_partner="0000000202",
        customer_partner="0000059279",
        customer_name="상주시산림조합",
    )
    assert [line["acctCd"] for line in lines] == ["1030000", "4010001", "2550000"]
    # 관리항목은 매출 라인에만 — 산림조합 870, 3자리는 담보부문 03
    assert lines[1]["usermTy1"] == "870"
    assert lines[1]["userlTy2"] == "03"
    assert "usermTy1" not in lines[0] and "usermTy1" not in lines[2]
    assert all("userlTy2" not in lines[i] for i in (0, 2))
    assert all(line["docuTy"] == "3" for line in lines)
    assert lines[0]["acctAm"] == 2576200.0  # 차변 = 수수료 + 부가세
    assert lines[0]["maNb"] == "01-2605-3-1715"
    assert lines[1]["maNb"] == "01-2605-3-1715"
    assert lines[2]["taxFg"] == "11"
    assert lines[2]["supAm"] == 2342000.0
    # 적요는 재무팀 수기 관행 그대로 (수수료입금/일반 매출/감정평가수수료 {번호})
    assert lines[0]["rmkDc"] == "수수료입금"
    assert lines[1]["rmkDc"] == "일반 매출"
    assert lines[2]["rmkDc"] == "감정평가수수료 01-2605-3-1715"
    assert "maNb" not in lines[2]


def test_약식_400번호는_적요에서_뽑는다():
    assert yak_no_from_jeokyo("400578052/대체입금/") == "400578052"
    assert yak_no_from_jeokyo("400574828/대체입금/") == "400574828"
    # 국민 내부번호(302~)·일반 적요는 약식이 아니다
    assert yak_no_from_jeokyo("302205538/대체입금/") is None
    assert yak_no_from_jeokyo("최유미/타행이체/국민은행/") is None
    assert yak_no_from_jeokyo(None) is None


def test_약식_묶음전표는_수기전표와_같은_모양():
    # 재무팀 수기 관행(2026-08-05 no=00043): 차변 합계 1줄 + 400건별 대변 쌍
    lines = yak_bundle_lines(
        items=[
            {"yak_no": "400578052", "supply": Decimal("50000"),
             "vat": Decimal("5000"), "partner_code": "0000023094",
             "branch_name": "국민은행 상무"},
            {"yak_no": "400578401", "supply": Decimal("80000"),
             "vat": Decimal("8000"), "partner_code": "0000013728",
             "branch_name": "국민은행 신림서종합금융센터"},
        ],
        total=Decimal("143000"),
        voucher_date=date(2026, 8, 4),
        menu_sq=50300,
        division_code="1000",
        account_partner="0000000104",
    )
    assert [line["acctCd"] for line in lines] == [
        "1030000", "4010002", "2550000", "4010002", "2550000"
    ]
    assert [line["menuLnSq"] for line in lines] == [1, 2, 3, 4, 5]
    assert lines[0]["acctAm"] == 143000.0
    assert lines[0]["rmkDc"] == "약식평가수수료 입금"
    assert all(line["docuTy"] == "3" for line in lines)
    # 건별 대변 쌍 — 적요·거래처·관리번호는 각자의 400번호를 따른다
    assert lines[1]["rmkDc"] == "약식평가수수료 400578052"
    assert lines[3]["rmkDc"] == "약식평가수수료 400578401"
    assert lines[1]["maNb"] == "400578052"
    assert lines[3]["maNb"] == "400578401"
    assert lines[3]["trCd"] == "0000013728"
    # 매출구분 09 약식부분 · 은행구분 040 국민 — 매출 라인에만
    assert lines[1]["userlTy2"] == "09"
    assert lines[3]["userlTy2"] == "09"
    assert lines[1]["usermTy1"] == "040"
    assert all("userlTy2" not in lines[i] for i in (0, 2, 4))
    assert "maNb" not in lines[0] and "maNb" not in lines[2]
    assert lines[2]["taxFg"] == "11" and lines[2]["supAm"] == 50000.0
    assert lines[4]["taxFg"] == "11" and lines[4]["supAm"] == 80000.0


def test_부가세가_없으면_두_줄만():
    lines = general_lines(
        doc_id="01-2605-3-1715",
        fee=Decimal("100000"),
        vat=Decimal("0"),
        voucher_date=date(2026, 8, 4),
        menu_sq=50011,
        division_code="1000",
        account_partner="0000000202",
        customer_partner="0000059279",
    )
    assert [line["acctCd"] for line in lines] == ["1030000", "4010001"]


def test_품의내역은_입금_감정서번호_거래처명_형식():
    lines = general_lines(
        doc_id="01-2605-3-1715",
        fee=Decimal("100000"),
        vat=Decimal("10000"),
        voucher_date=date(2026, 8, 6),
        menu_sq=50400,
        division_code="1000",
        account_partner="0000000202",
        customer_partner="0000059279",
        customer_name="상주시산림조합",
    )
    assert all(line["isuDoc"] == "입금 01-2605-3-1715 상주시산림조합" for line in lines)
    bundle = banje_bundle_lines(
        items=[
            {"doc_id": "01-2607-4-0257", "tx_amount": Decimal("500500"),
             "account_partner": "0000000101", "receivable_partner": "0000059118",
             "customer_name": "단국대학교"},
        ],
        voucher_date=date(2026, 8, 6), menu_sq=50401, division_code="1000",
    )
    assert all(line["isuDoc"] == "입금 01-2607-4-0257 단국대학교" for line in bundle)
    bundle2 = banje_bundle_lines(
        items=[
            {"doc_id": "01-2607-4-0257", "tx_amount": Decimal("1"),
             "account_partner": "a", "receivable_partner": "b"},
            {"doc_id": "01-2504-3-1119", "tx_amount": Decimal("1"),
             "account_partner": "a", "receivable_partner": "b"},
        ],
        voucher_date=date(2026, 8, 6), menu_sq=50402, division_code="1000",
    )
    assert all(line["isuDoc"] == "입금 01-2607-4-0257 외 1건" for line in bundle2)
    yak = yak_bundle_lines(
        items=[
            {"yak_no": "400578052", "supply": Decimal("50000"),
             "vat": Decimal("5000"), "partner_code": "x", "branch_name": ""},
            {"yak_no": "400578401", "supply": Decimal("80000"),
             "vat": Decimal("8000"), "partner_code": "y", "branch_name": ""},
        ],
        total=Decimal("143000"), voucher_date=date(2026, 8, 6),
        menu_sq=50403, division_code="1000", account_partner="z",
    )
    assert all(line["isuDoc"] == "약식입금 400578052 외 1건" for line in yak)
