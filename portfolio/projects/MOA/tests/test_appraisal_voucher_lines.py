from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.services.appraisals import _cached_vouchers, _mark_offset_lines


def _line(
    line_no: str,
    account_code: str,
    account_name: str,
    debit_credit: str,
    amount: int,
    management_no: str | None = None,
    remark: str = "",
    voucher_date: date = date(2026, 7, 20),
    voucher_no: str = "00052",
) -> SimpleNamespace:
    return SimpleNamespace(
        voucher_date=voucher_date,
        voucher_no=voucher_no,
        division_code="1000",
        line_no=line_no,
        account_code=account_code,
        account_name=account_name,
        debit_credit=debit_credit,
        amount=Decimal(amount),
        management_no=management_no,
        remark=remark,
        partner_code=None,
        partner_name=None,
        document_status="1",
    )


def test_batch_settlement_includes_allocated_bank_line_for_selected_doc() -> None:
    lines = [
        _line("00003", "1030000", "보통예금", "3", 206_972_700, remark="방배15구역 정산"),
        _line("00004", "1080000", "외상매출금", "4", 89_930_500, "01-2604-1-0253"),
        _line("00005", "1080000", "외상매출금", "4", 107_142_200, "01-2604-1-0252"),
        _line("00006", "1080000", "외상매출금", "4", 9_900_000, "01-2603-5-0032"),
    ]

    voucher = _cached_vouchers(lines, "01-2604-1-0253")[0]

    assert voucher["debit_total"] == 89_930_500
    assert voucher["credit_total"] == 89_930_500
    assert [line["account_name"] for line in voucher["lines"]] == ["보통예금", "외상매출금"]
    assert voucher["lines"][0]["amount"] == 89_930_500
    assert voucher["lines"][0]["original_amount"] == 206_972_700
    assert voucher["lines"][0]["allocated"] is True
    assert "일괄 정산 배분" in voucher["lines"][0]["remark"]
    assert voucher["batch_settlement"] is True
    assert voucher["batch_doc_count"] == 3
    assert voucher["allocated_cash_amount"] == 89_930_500
    assert voucher["original_cash_amount"] == 206_972_700
    assert voucher["batch_note"] == (
        "여러 건 묶음 · 3건 · 이 감정서 89,930,500원 / 원전표 206,972,700원"
    )


def test_separate_cash_groups_do_not_leak_other_bank_lines() -> None:
    lines = [
        _line("00001", "1030000", "보통예금", "3", 38_500_000),
        _line("00002", "1080000", "외상매출금", "4", 38_500_000, "01-2604-5-0047"),
        _line("00003", "1030000", "보통예금", "3", 206_972_700),
        _line("00004", "1080000", "외상매출금", "4", 89_930_500, "01-2604-1-0253"),
        _line("00005", "1080000", "외상매출금", "4", 107_142_200, "01-2604-1-0252"),
        _line("00006", "1080000", "외상매출금", "4", 9_900_000, "01-2603-5-0032"),
        _line("00007", "1030000", "보통예금", "3", 5_500_000),
        _line("00008", "1080000", "외상매출금", "4", 5_500_000, "01-2606-5-0085"),
    ]

    voucher = _cached_vouchers(lines, "01-2604-1-0253")[0]

    assert len(voucher["lines"]) == 2
    assert voucher["lines"][0]["line_no"] == "00003"
    assert voucher["lines"][1]["line_no"] == "00004"


# ── 선수금 상계 표시 (01-2606-4-0211 실제 전표 형태) ────────────────────
DOC = "01-2606-4-0211"


def _advance_taken(amount: int = 200_000) -> list[SimpleNamespace]:
    """선수금으로 미리 받은 전표 (보통예금 차변 / 선수금 대변)."""
    return [
        _line("00001", "1030000", "보통예금", "3", amount, DOC, "선수금",
              voucher_date=date(2026, 6, 12), voucher_no="00069"),
        _line("00002", "2590000", "선수금", "4", amount, DOC, "선수금",
              voucher_date=date(2026, 6, 12), voucher_no="00069"),
    ]


def _advance_cleared(amount: int = 200_000) -> list[SimpleNamespace]:
    """잔금 정산 전표 — 매출을 세우면서 선수금을 차변으로 털어낸다."""
    return [
        _line("00001", "4010001", "감정수수료", "4", 1_042_000, DOC, "일반 매출",
              voucher_date=date(2026, 7, 30), voucher_no="00061"),
        _line("00003", "2590000", "선수금", "3", amount, DOC, "선수금",
              voucher_date=date(2026, 7, 30), voucher_no="00061"),
    ]


def _lines_of(items: list[dict]) -> list[dict]:
    return [line for item in items for line in item["lines"]]


def test_fully_offset_advance_lines_are_marked() -> None:
    items = _cached_vouchers(_advance_taken(), DOC) + _cached_vouchers(_advance_cleared(), DOC)

    _mark_offset_lines(items)

    advance = [line for line in _lines_of(items) if line["account_code"] == "2590000"]
    assert len(advance) == 2
    assert all(line["offset"] is True for line in advance)
    assert advance[0]["offset_note"] == "선수금 200,000원을 받았다가 전액 반제 — 잔액 0"
    # 선수금이 아닌 줄은 손대지 않는다.
    assert all(
        "offset" not in line for line in _lines_of(items) if line["account_code"] != "2590000"
    )


def test_partly_cleared_advance_is_not_marked() -> None:
    """일부만 반제된 선수금은 잔액이 남아 있으므로 죽이면 안 된다."""
    items = _cached_vouchers(_advance_taken(200_000), DOC) + _cached_vouchers(
        _advance_cleared(120_000), DOC
    )

    _mark_offset_lines(items)

    assert all("offset" not in line for line in _lines_of(items))


def test_advance_without_clearing_is_not_marked() -> None:
    items = _cached_vouchers(_advance_taken(), DOC)

    _mark_offset_lines(items)

    assert all("offset" not in line for line in _lines_of(items))
