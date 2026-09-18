"""세금계산서 전액 취소 — 팝빌 호출 없이 경로 검증.

전송 후=수정세금계산서 사유6, 전송 전=발행취소+삭제, 팝빌에서 이미
발행취소(상태 600)한 건=원장 동기화만. 세 경로 모두 원장에 '세금취소' 행을 남긴다.
"""

from typing import Any

import pytest

from app.services import popbill_tax


class FakeDetail:
    """getDetailInfo 반환 흉내 — 원본 세금계산서."""

    def __init__(self) -> None:
        self.writeDate = "20260811"
        self.purposeType = "청구"
        self.invoicerCorpNum = "2148746436"
        self.invoicerCorpName = "(주)대화감정평가법인"
        self.invoiceeCorpNum = "8978100698"
        self.invoiceeCorpName = "(주)유한디앤씨"
        self.supplyCostTotal = "655000"
        self.taxTotal = "65500"
        self.totalAmount = "720500"
        item = type("Item", (), {})()
        item.purchaseDT = "20260811"
        item.itemName = "감정평가수수료 01-2607-3-2160"
        item.supplyCost = "655000"
        item.tax = "65500"
        self.detailList = [item]


class FakeSvc:
    def __init__(self) -> None:
        self.calls: "list[tuple[str, str]]" = []

    def getDetailInfo(self, corp: str, key_type: str, mgt_key: str) -> FakeDetail:
        return FakeDetail()

    def cancelIssue(self, corp: str, key_type: str, mgt_key: str,
                    memo: "str | None" = None, user_id: "str | None" = None) -> None:
        self.calls.append(("cancelIssue", mgt_key))

    def delete(self, corp: str, key_type: str, mgt_key: str,
               user_id: "str | None" = None) -> None:
        self.calls.append(("delete", mgt_key))


class FakeDb:
    def execute(self, *args: Any, **kwargs: Any) -> "FakeDb":
        return self

    def scalar(self) -> int:
        return 0


# 국세청 전송이 끝난 원본 — 수정세금계산서 경로로 가는 기본 상태.
_SENT_INFO = {
    "nts_confirm": "202608114100020300001740",
    "nts_send_dt": "20260812070000",
    "state_code": 300,
    "supply_cost": 655000, "tax": 65500, "total": 720500,
}


@pytest.fixture
def patched(monkeypatch):
    captured: dict[str, Any] = {"svc": FakeSvc()}
    monkeypatch.setattr(popbill_tax, "_service", lambda: captured["svc"])
    monkeypatch.setattr(
        popbill_tax, "latest_taxinvoice_row",
        lambda db, doc: ("세금계산서", doc),
    )
    monkeypatch.setattr(popbill_tax, "get_info", lambda key: dict(_SENT_INFO))
    monkeypatch.setattr(
        popbill_tax, "register_issue",
        lambda inv, key, memo="": captured.update(inv=inv, key=key) or {"success": True},
    )
    monkeypatch.setattr(popbill_tax, "save_issued", lambda db, **kw: captured.update(saved=kw))
    return captured


def test_cancel_taxinvoice_issues_negative_modify_code_6(patched):
    result = popbill_tax.cancel_taxinvoice(FakeDb(), doc_id="01-2607-3-2160")

    assert result["success"] is True
    inv = patched["inv"].__dict__
    assert inv["modifyCode"] == 6
    assert inv["orgNTSConfirmNum"] == "202608114100020300001740"
    assert inv["supplyCostTotal"] == "-655000"
    assert inv["taxTotal"] == "-65500"
    assert inv["totalAmount"] == "-720500"
    assert inv["invoiceeCorpName"] == "(주)유한디앤씨"
    detail = inv["detailList"][0].__dict__
    assert detail["supplyCost"] == "-655000"
    assert detail["tax"] == "-65500"
    assert patched["key"] == "01-2607-3-2160-M1"
    saved = patched["saved"]
    assert saved["doc_type"] == "세금취소"
    assert saved["supply_cost"] == -655000
    assert saved["mgt_key"] == "01-2607-3-2160-M1"


def test_cancel_taxinvoice_rejects_double_cancel(patched, monkeypatch):
    monkeypatch.setattr(
        popbill_tax, "latest_taxinvoice_row",
        lambda db, doc: ("세금취소", f"{doc}-M1"),
    )

    result = popbill_tax.cancel_taxinvoice(FakeDb(), doc_id="01-2607-3-2160")

    assert result["success"] is False
    assert "이미 취소" in result["message"]


def test_cancel_taxinvoice_requires_nts_confirm(patched, monkeypatch):
    monkeypatch.setattr(
        popbill_tax, "get_info",
        lambda key: dict(_SENT_INFO, nts_confirm=""),
    )

    result = popbill_tax.cancel_taxinvoice(FakeDb(), doc_id="01-2607-3-2160")

    assert result["success"] is False
    assert "승인번호" in result["message"]


def test_cancel_before_nts_transmission_uses_cancel_issue(patched, monkeypatch):
    """전송 전(전송일시 없음)이면 수정발행이 아니라 발행취소+삭제로 취소한다."""
    monkeypatch.setattr(
        popbill_tax, "get_info",
        lambda key: dict(_SENT_INFO, nts_send_dt=None),
    )

    result = popbill_tax.cancel_taxinvoice(FakeDb(), doc_id="01-2606-1-0388")

    assert result["success"] is True
    assert result["cancelled_before_nts"] is True
    assert patched["svc"].calls == [
        ("cancelIssue", "01-2606-1-0388"), ("delete", "01-2606-1-0388"),
    ]
    assert "inv" not in patched  # 수정세금계산서 미발행
    saved = patched["saved"]
    assert saved["doc_type"] == "세금취소"
    assert saved["mgt_key"] == "01-2606-1-0388"
    assert saved["supply_cost"] == -655000


def test_cancel_syncs_popbill_side_cancellation(patched, monkeypatch):
    """팝빌 화면에서 이미 발행취소(상태 600)한 건은 원장에만 취소를 기록한다."""
    monkeypatch.setattr(
        popbill_tax, "get_info",
        lambda key: dict(_SENT_INFO, state_code=600, nts_send_dt=None),
    )

    result = popbill_tax.cancel_taxinvoice(FakeDb(), doc_id="01-2606-1-0388")

    assert result["success"] is True
    assert result["synced"] is True
    assert patched["svc"].calls == []  # 팝빌 호출 없음
    assert patched["saved"]["doc_type"] == "세금취소"


def test_already_treats_popbill_state_600_as_cancelled(patched, monkeypatch):
    """발급 팝업 잠금 판정 — 팝빌 발행취소 상태(600)면 취소로 인정해 잠금을 푼다."""
    monkeypatch.setattr(
        popbill_tax, "get_info",
        lambda key: dict(_SENT_INFO, state_code=600),
    )

    already = popbill_tax._taxinvoice_already(FakeDb(), "01-2606-1-0388")

    assert already["cancelled"] is True
    assert "error" in already
