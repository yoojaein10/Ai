"""취소 현금영수증 발행(cancel_cashbill) — 팝빌 호출 없이 경로 검증."""

from typing import Any

import pytest

from app.services import popbill_tax


class FakeSvc:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def revokeRegistIssue(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(args)


@pytest.fixture
def patched(monkeypatch):
    svc = FakeSvc()
    saved: dict[str, Any] = {}
    monkeypatch.setattr(popbill_tax, "_cashbill_service", lambda: svc)
    # 원장 상태: 2160은 발행분 1건(원 키 그대로), 그 외 감정서는 원장에 없음
    monkeypatch.setattr(
        popbill_tax, "latest_cashbill_row",
        lambda db, doc: ("현금영수증", doc) if doc == "01-2607-3-2160" else None,
    )
    monkeypatch.setattr(
        popbill_tax, "next_cashbill_cancel_key", lambda db, doc: f"{doc}-C"
    )
    infos = {
        "01-2607-3-2160": {"trade_dt": "20260714120000", "confirm_num": 'REDACTED_CONFIGURE_LOCALLY789',
                           "trade_usage": "소득공제용", "total": "720500"},
        "01-2607-3-2160-C": {"trade_dt": "20260811150000", "confirm_num": "987654321"},
    }
    monkeypatch.setattr(popbill_tax, "get_cashbill_info", lambda key: infos.get(key, {"error": "-14000003: 없음"}))
    monkeypatch.setattr(
        popbill_tax, "save_issued",
        lambda db, **kw: saved.update(kw),
    )
    return svc, saved


def test_cancel_cashbill_issues_revoke_and_records_ledger(patched):
    svc, saved = patched

    result = popbill_tax.cancel_cashbill(None, doc_id="01-2607-3-2160", cancel_type=2)

    assert result["success"] is True
    assert result["confirm_num"] == "987654321"
    assert result["cancel_type"] == "오류발급취소"
    args = svc.calls[0]
    assert args[1] == "01-2607-3-2160-C"   # 취소분 mgtKey
    assert args[2] == 'REDACTED_CONFIGURE_LOCALLY789'          # 원거래 승인번호
    assert args[3] == "20260714"           # 원거래 거래일자(8자리)
    assert args[8] == 2                    # cancelType
    # 원장 기록: doc_type은 VARCHAR(10) 한도 때문에 '현금취소'
    assert saved["doc_type"] == "현금취소"
    assert saved["mgt_key"] == "01-2607-3-2160-C"
    assert saved["doc_id"] == "01-2607-3-2160"


def test_cancel_cashbill_targets_latest_reissue(patched, monkeypatch):
    """취소 후 재발급(-R2) 건 취소는 그 키의 원거래를 상대로, 취소키는 -C2."""
    svc, saved = patched
    monkeypatch.setattr(
        popbill_tax, "latest_cashbill_row",
        lambda db, doc: ("현금영수증", f"{doc}-R2"),
    )
    monkeypatch.setattr(
        popbill_tax, "next_cashbill_cancel_key", lambda db, doc: f"{doc}-C2"
    )
    monkeypatch.setattr(
        popbill_tax, "get_cashbill_info",
        lambda key: {"trade_dt": "20260813170000", "confirm_num": "R2CONF"}
        if key.endswith("-R2") else {"confirm_num": "C2CONF", "trade_dt": "20260813"},
    )

    result = popbill_tax.cancel_cashbill(None, doc_id="01-2601-2-0001", cancel_type=2)

    assert result["success"] is True
    args = svc.calls[0]
    assert args[1] == "01-2601-2-0001-C2"  # 두 번째 취소분 키
    assert args[2] == "R2CONF"             # 재발급분 승인번호가 원거래
    assert saved["mgt_key"] == "01-2601-2-0001-C2"


def test_cancel_cashbill_rejects_unknown_original(patched):
    svc, _ = patched

    result = popbill_tax.cancel_cashbill(None, doc_id="01-9999-9-9999", cancel_type=1)

    assert result["success"] is False
    assert "홈택스" in result["message"]
    assert not svc.calls


def test_cancel_cashbill_rejects_double_cancel(patched, monkeypatch):
    svc, _ = patched
    monkeypatch.setattr(
        popbill_tax, "latest_cashbill_row",
        lambda db, doc: ("현금취소", f"{doc}-C"),
    )

    result = popbill_tax.cancel_cashbill(None, doc_id="01-2607-3-2160", cancel_type=1)

    assert result["success"] is False
    assert "이미 취소" in result["message"]
    assert not svc.calls


def test_cancel_cashbill_rejects_bad_cancel_type(patched):
    svc, _ = patched

    result = popbill_tax.cancel_cashbill(None, doc_id="01-2607-3-2160", cancel_type=9)

    assert result["success"] is False
    assert not svc.calls
