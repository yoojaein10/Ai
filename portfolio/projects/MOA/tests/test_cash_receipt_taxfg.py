"""현금영수증 건의 부가세예수금 세무구분 = 31(현금과세).

그동안 11(과세매출) 고정으로 보내서 재무팀이 아마란스에서 손으로 고쳐 왔다.
2026-08 MOA 생성분 실측: 현금영수증 6건 중 4건이 31로 정정돼 있었고, 나머지
2건은 아직 11로 남아 있었다.
"""

from datetime import date
from decimal import Decimal

from app.services import default_vouchers as dv
from app.services import deposit_vouchers as pv


def _vat_line(lines):
    return next(line for line in lines if line["acctCd"] == "2550000")


def _base(**over):
    values = dict(
        doc_id="01-2608-3-2437", customer_name="홍길동",
        company_code="1000", division_code="1000",
        voucher_date=date(2026, 8, 7), menu_sq=10001,
        base_fee=Decimal("1000000"), vat=Decimal("100000"),
        total=Decimal("1100000"), partner_code="P1", dept_cd="1010",
    )
    values.update(over)
    return values


def test_기본전표_현금영수증이면_현금과세다():
    line = _vat_line(dv._voucher_lines(**_base(cash_receipt=True)))
    assert line["taxFg"] == dv.TAX_FG_CASH == "31"


def test_기본전표_현금영수증이_아니면_과세매출이다():
    line = _vat_line(dv._voucher_lines(**_base(cash_receipt=False)))
    assert line["taxFg"] == dv.TAX_FG_TAXABLE == "11"


def test_기본전표_판정값이_없으면_과세매출이다():
    """호출부가 값을 안 넘겨도 예전 동작(11)을 유지해야 한다."""
    line = _vat_line(dv._voucher_lines(**_base()))
    assert line["taxFg"] == "11"


def test_세무구분만_바뀌고_나머지는_그대로다():
    """부가세 라인의 다른 필드가 함께 흔들리면 전표가 반려된다."""
    cash = _vat_line(dv._voucher_lines(**_base(cash_receipt=True)))
    plain = _vat_line(dv._voucher_lines(**_base(cash_receipt=False)))
    assert {k: v for k, v in cash.items() if k != "taxFg"} == {
        k: v for k, v in plain.items() if k != "taxFg"
    }


def test_입금전표도_같은_기준이다():
    common = dict(
        doc_id="01-2608-3-2437", fee=Decimal("1000000"), vat=Decimal("100000"),
        voucher_date=date(2026, 8, 7), menu_sq=10001, division_code="1000",
        account_partner="A1", customer_partner="C1", customer_name="홍길동",
    )
    assert _vat_line(pv.general_lines(**common, cash_receipt=True))["taxFg"] == "31"
    assert _vat_line(pv.general_lines(**common, cash_receipt=False))["taxFg"] == "11"
    assert _vat_line(pv.general_lines(**common))["taxFg"] == "11"


def test_약식_묶음은_건별로_세무구분을_준다():
    """한 묶음전표에 현금영수증 건과 세금계산서 건이 섞여 들어온다 —
    전표 단위로 하나만 정하면 절반이 틀린다."""
    items = [
        {"yak_no": "01-2608-6-0001", "supply": Decimal("100000"),
         "vat": Decimal("10000"), "partner_code": "P1", "branch_name": "국민은행",
         "cash_receipt": True},
        {"yak_no": "01-2608-6-0002", "supply": Decimal("200000"),
         "vat": Decimal("20000"), "partner_code": "P2", "branch_name": "국민은행",
         "cash_receipt": False},
    ]
    lines = pv.yak_bundle_lines(
        items=items, total=Decimal("330000"), voucher_date=date(2026, 8, 7),
        menu_sq=10001, division_code="1000", account_partner="A1",
    )
    vat_lines = [line for line in lines if line["acctCd"] == "2550000"]
    assert [line["taxFg"] for line in vat_lines] == ["31", "11"]


def test_취소된_현금영수증은_세지_않는다():
    """취소분을 세면 취소된 현금영수증 때문에 세무구분이 바뀐다.
    TAMS 는 취소를 TRAN_TYPE=1 과 AUTH_NO='null' 두 가지로 적는다."""
    import inspect

    sql = inspect.getsource(dv.has_cash_receipt)
    assert "transaction_type = '1'" in sql
    assert "= 'null'" in sql
    # MOA 직접 발급분도 봐야 오늘 발급한 건이 잡힌다 (TAMS 캐시는 수동 동기화).
    assert "a10_issued_taxinvoice" in sql
    assert "a10_tams_cash_receipt_cache" in sql
