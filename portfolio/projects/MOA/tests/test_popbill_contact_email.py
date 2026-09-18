"""세금계산서 공급받는자 이메일 = 고객사담당자(api16S24) 중 관리구분 정만."""

from typing import Any

from app.services.popbill_tax import _primary_contact_email


class FakeClient:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, Any]] = []

    def post(self, endpoint: str, *, json_body: Any) -> dict[str, Any]:
        self.calls.append((endpoint, json_body))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_primary_contact_email_picks_only_def_contact() -> None:
    """담당자가 여러 명이면 정(defYn=1)의 이메일만 쓴다 — 부 담당자 메일로 나가면 안 된다."""
    client = FakeClient([
        {"resultCode": 0, "resultData": [
            {"defYn": "0", "trchargeEmail": 'contact@example.com'},
            {"defYn": "1", "trchargeEmail": 'contact@example.com'},
            {"defYn": "0", "trchargeEmail": 'contact@example.com'},
        ]},
    ])

    email = _primary_contact_email(client, "2000", "0000001000")

    assert email == 'contact@example.com'
    assert client.calls == [
        ("/apiproxy/api16S24", {"coCd": "2000", "trCd": "0000001000"}),
    ]


def test_primary_contact_email_empty_when_no_def_contact() -> None:
    client = FakeClient([
        {"resultCode": 0, "resultData": [
            {"defYn": "0", "trchargeEmail": 'contact@example.com'},
        ]},
    ])

    assert _primary_contact_email(client, "2000", "0000001000") == ""


def test_primary_contact_email_empty_on_lookup_failure() -> None:
    """담당자 조회가 죽어도 발급 초안 조립은 계속돼야 한다 — 이메일만 빈칸."""
    client = FakeClient([RuntimeError("api16S24 실패")])

    assert _primary_contact_email(client, "2000", "0000001000") == ""
