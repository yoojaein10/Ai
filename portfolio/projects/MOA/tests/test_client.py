import json
from typing import Any

import pytest
import requests
from pydantic import SecretStr

from app.amaranth.auth import AmaranthSigner
from app.amaranth.client import AmaranthClient
from app.amaranth.exceptions import DuplicateVoucherError
from app.config import Settings


class FakeDb:
    def __init__(self) -> None:
        self.logs: list[Any] = []
        self.commits = 0

    def add(self, value: Any) -> None:
        self.logs.append(value)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        pass


class FakeHttp:
    def __init__(self, outcomes: list[requests.Response | Exception]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict[str, Any]] = []

    def request(self, **kwargs: Any) -> requests.Response:
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make_response(status: int, payload: dict[str, Any]) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    response.headers["Content-Type"] = "application/json"
    return response


def make_settings() -> Settings:
    return Settings(
        a10_base_url="https://example.invalid",
        a10_caller_name="bridge-test",
        a10_access_token=SecretStr("access-token"),
        a10_hash_key=SecretStr("hash-key"),
        a10_group_seq="group-1",
    )


def make_signer(settings: Settings) -> AmaranthSigner:
    counter = iter(("a" * 30, "b" * 30, "c" * 30))
    return AmaranthSigner(
        settings,
        clock=lambda: 1_700_000_000,
        transaction_id_factory=lambda: next(counter),
    )


def test_client_retries_5xx_and_logs_every_attempt() -> None:
    settings = make_settings()
    db = FakeDb()
    http = FakeHttp(
        [
            make_response(503, {"resultCode": -1}),
            make_response(200, {"resultCode": 0, "resultData": []}),
        ]
    )
    sleeps: list[float] = []
    client = AmaranthClient(
        db,  # type: ignore[arg-type]
        settings=settings,
        http=http,  # type: ignore[arg-type]
        signer=make_signer(settings),
        sleep=sleeps.append,
    )

    result = client.post("/apiproxy/api16S08", json_body={"groupSeq": "group-1"})

    assert result["resultCode"] == 0
    assert len(http.calls) == 2
    assert len(db.logs) == 2
    assert db.commits == 2
    assert sleeps == [1]
    assert http.calls[0]["headers"]["transaction-id"] != http.calls[1]["headers"][
        "transaction-id"
    ]


def test_client_maps_documented_duplicate_voucher_error() -> None:
    settings = make_settings()
    db = FakeDb()
    response = make_response(
        200,
        {
            "resultCode": 21010,
            "resultMsg": "데이터 전송중 문제가 발생하였습니다.",
            "resultData": [{"errorMsg": "동일한 작성번호가 존재합니다."}],
        },
    )
    client = AmaranthClient(
        db,  # type: ignore[arg-type]
        settings=settings,
        http=FakeHttp([response]),  # type: ignore[arg-type]
        signer=make_signer(settings),
        sleep=lambda _: None,
    )

    with pytest.raises(DuplicateVoucherError) as exc_info:
        client.post("/apiproxy/api11A10", json_body={"coCd": "2000"})

    assert exc_info.value.code == 21010
    assert len(db.logs) == 1
    assert "동일한 작성번호" in (db.logs[0].res_body or "")


def test_client_retries_network_error() -> None:
    settings = make_settings()
    db = FakeDb()
    http = FakeHttp(
        [
            requests.ConnectionError("temporary"),
            make_response(200, {"resultCode": 0, "resultData": {}}),
        ]
    )
    client = AmaranthClient(
        db,  # type: ignore[arg-type]
        settings=settings,
        http=http,  # type: ignore[arg-type]
        signer=make_signer(settings),
        sleep=lambda _: None,
    )

    assert client.get("/apiproxy/test")["resultCode"] == 0
    assert len(db.logs) == 2
