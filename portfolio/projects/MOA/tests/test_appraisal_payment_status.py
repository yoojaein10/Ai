"""감정서 목록의 입금상태가 정식 판정과 어긋나지 않는지 검증한다."""

from decimal import Decimal
from unittest.mock import MagicMock

from app.services.appraisals import AppraisalService, _appraisal_payment_label


def _row(**overrides):
    row = {
        "billed_amount": Decimal("19468100"),
        "received_amount": Decimal("19468100"),
        "advance_amount": Decimal("0"),
        "overpaid_amount": Decimal("0"),
        "pay_result": "분할입금",
    }
    row.update(overrides)
    return row


def test_전표상_미수_0이어도_정식_판정이_분할입금이면_일부입금이다():
    """01-2607-2-0080 회귀: 원장보다 381,400원 적게 받은 경우다."""
    assert _appraisal_payment_label(_row()) == "일부입금"


def test_정식_판정이_입금완료일_때만_입금완료다():
    assert _appraisal_payment_label(_row(pay_result="입금완료")) == "입금완료"


def test_목록_조회는_payment_status를_조인한다():
    db = MagicMock()
    db.execute.return_value.mappings.return_value.all.return_value = [
        {"doc_id": "01-2607-2-0080", **_row()}
    ]

    statuses = AppraisalService(db)._payment_statuses(["01-2607-2-0080"])

    sql = str(db.execute.call_args.args[0])
    assert "LEFT JOIN dbo.a10_payment_status" in sql
    assert statuses == ["일부입금"]


def test_정식_판정이_없으면_입금액이_있는_건을_완료로_추정하지_않는다():
    assert _appraisal_payment_label(_row(pay_result=None)) == "일부입금"
