from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.models.gaprice_outbox import GapriceOutbox
from app.services.gaprice_outbox import (
    GapriceApprovalError,
    _group_outbox_rows,
    _new_outbox_rows,
)


def _template() -> GapriceOutbox:
    return GapriceOutbox(
        doc_id="01-2607-3-0001",
        masterid=12345,
        manager="이일우",
        usr_seq=813,
        ratio=Decimal("60"),
        pung_price=None,
        basic_susu=Decimal("600000"),
        in_price=Decimal("600000"),
        in_date=date(2026, 7, 20),
    )


def test_new_outbox_rows_built_from_template():
    rows = _new_outbox_rows(
        _template(),
        [{"manager": "김철수", "usr_seq": 901, "ratio": 40, "in_price": 400000, "basic_susu": 400000}],
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.doc_id == "01-2607-3-0001"
    assert row.masterid == 12345
    assert row.manager == "김철수"
    assert row.usr_seq == 901
    assert row.ratio == Decimal("40")
    assert row.in_price == Decimal("400000")
    assert row.basic_susu == Decimal("400000")
    assert row.in_date == date(2026, 7, 20)
    assert row.pung_price is None


def test_new_outbox_rows_allows_missing_usr_seq_and_trims_name():
    rows = _new_outbox_rows(
        _template(),
        [{"manager": "  외부평가사  ", "ratio": 10, "in_price": 0, "basic_susu": 0}],
    )
    assert rows[0].manager == "외부평가사"
    assert rows[0].usr_seq is None


def test_new_outbox_rows_rejects_empty_manager():
    with pytest.raises(GapriceApprovalError):
        _new_outbox_rows(_template(), [{"manager": "  ", "ratio": 10, "in_price": 1000, "basic_susu": 0}])


def test_new_outbox_rows_rejects_negative_amounts():
    with pytest.raises(GapriceApprovalError):
        _new_outbox_rows(_template(), [{"manager": "김철수", "ratio": 10, "in_price": -1, "basic_susu": 0}])


def test_group_outbox_rows_includes_approval_audit_fields():
    row = _template()
    row.id = 77
    row.status = "APPROVED"
    row.approved_by = 813
    row.approved_at = datetime(2026, 8, 5, 9, 30, 45)
    row.applied_ga_seq = 4321

    docs = _group_outbox_rows(
        [row],
        {row.doc_id: {"CustName": "테스트 거래처", "base_fee": Decimal("1000000")}},
        {row.doc_id: 1000000.0},
        {813: "이일우"},
    )

    assert docs == [
        {
            "doc_id": row.doc_id,
            "in_date": "2026-07-20",
            "customer_name": "테스트 거래처",
            "base_fee": 1000000.0,
            "paid_amount": 1000000.0,
            "status": "APPROVED",
            "approved_by": 813,
            "approved_by_name": "이일우",
            "approved_at": "2026-08-05T09:30:45",
            "rows": [
                {
                    "id": 77,
                    "manager": "이일우",
                    "usr_seq": 813,
                    "ratio": 60.0,
                    "in_price": 600000.0,
                    "basic_susu": 600000.0,
                    "applied_ga_seq": 4321,
                }
            ],
        }
    ]


def test_allocation_ui_has_read_only_approved_mode_and_print():
    root = Path(__file__).resolve().parent.parent
    html = (root / "desktop" / "ui" / "allocation.html").read_text(encoding="utf-8")
    script = (root / "desktop" / "ui" / "allocation.js").read_text(encoding="utf-8")

    assert 'id="approvedOnly"' in html
    assert 'id="printButton"' in html
    assert "const currentStatus=()=>isApprovedMode()?'APPROVED':'PENDING'" in script
    assert "if(!approved){" in script
    assert "window.print()" in script
