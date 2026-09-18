"""세금계산서 팩스 전송 — mgt_key 해석·발신/수신번호 처리 검증."""

from app.services import popbill_tax


class _Response:
    code = 1
    message = "팩스 전송 완료"


class _FaxStub:
    def __init__(self):
        self.calls = []

    def sendFax(self, corp, key_type, mgt_key, sender, receiver, user):
        self.calls.append((corp, key_type, mgt_key, sender, receiver, user))
        return _Response()


def test_팩스는_최신_mgt_key와_정규화한_수신번호로_보낸다(monkeypatch):
    stub = _FaxStub()
    monkeypatch.setattr(popbill_tax, "_service", lambda: stub)
    # 취소 후 재발행 건은 최신 mgt_key(-R1)로 보내야 한다
    monkeypatch.setattr(
        popbill_tax, "latest_taxinvoice_row",
        lambda db, doc: ("세금계산서", f"{doc}-R1"),
    )
    result = popbill_tax.send_taxinvoice_fax(
        None, doc_id="01-2607-3-2317", receive_num="02-123-4567"
    )

    assert result["success"] is True
    assert result["message"] == "팩스 전송 완료"
    _, key_type, mgt_key, sender, receiver, _ = stub.calls[0]
    assert key_type == "SELL"
    assert mgt_key == "01-2607-3-2317-R1"
    assert receiver == '02REDACTED_CONFIGURE_LOCALLY7'  # 하이픈 제거
    assert sender == popbill_tax.get_settings().popbill_fax_sender


def test_원장에_세금계산서가_없으면_감정서번호를_mgt_key로_쓴다(monkeypatch):
    stub = _FaxStub()
    monkeypatch.setattr(popbill_tax, "_service", lambda: stub)
    monkeypatch.setattr(popbill_tax, "latest_taxinvoice_row", lambda db, doc: None)
    result = popbill_tax.send_taxinvoice_fax(
        None, doc_id="01-2607-3-2317", receive_num='02REDACTED_CONFIGURE_LOCALLY78'
    )

    assert result["success"] is True
    assert stub.calls[0][2] == "01-2607-3-2317"


def test_짧은_수신번호는_전송하지_않는다(monkeypatch):
    called = []
    monkeypatch.setattr(popbill_tax, "_service", lambda: called.append(1))
    result = popbill_tax.send_taxinvoice_fax(None, doc_id="X", receive_num="1234")

    assert result["success"] is False
    assert not called
