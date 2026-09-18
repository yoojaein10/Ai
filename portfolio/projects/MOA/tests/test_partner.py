from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.dependencies import get_current_access
from app.main import app
from app.routers.partners import get_partner_service
from app.schemas.partner import PartnerCreate, is_valid_business_number
from app.services.partners import DuplicatePartnerError, PartnerService


def voucher_access() -> dict[str, Any]:
    """거래처 API 는 카드전표 화면 전용이다 — cardVouchers 권한이 있어야 연다."""
    return {
        "usr_seq": 100,
        "usr_id": "tester",
        "emp_name": "김재무",
        "office_id": "10",
        "office_name": "본사",
        "view_all_offices": True,
        "view_other_users": True,
        "menu_permissions": {"cardVouchers": True},
        "offices": [{"office_code": "10"}],
    }


class FakeDb:
    def __init__(self) -> None:
        self.values: list[Any] = []
        self.commits = 0

    def add(self, value: Any) -> None:
        self.values.append(value)

    def commit(self) -> None:
        self.commits += 1


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


def valid_request() -> PartnerCreate:
    return PartnerCreate(
        company_code="2000",
        business_no="120-81-47521",
        name="테스트 거래처",
        representative="홍길동",
        address1="서울시",
    )


def test_business_number_checksum() -> None:
    assert is_valid_business_number("1208147521") is True
    assert is_valid_business_number("1208147522") is False
    with pytest.raises(ValidationError):
        PartnerCreate(
            company_code="2000", business_no="1208147522", name="잘못된 번호"
        )


def test_create_partner_checks_duplicate_then_registers_and_records_sync() -> None:
    db = FakeDb()
    client = FakeClient(
        [
            {"resultCode": 0, "resultData": []},
            {"resultCode": 0, "resultData": [{"trCd": "0000001000"}]},
        ]
    )
    service = PartnerService(db, client=client)  # type: ignore[arg-type]

    result = service.create(valid_request())

    assert result == {
        "business_no": "1208147521",
        "partner_code": "0000001000",
        "name": "테스트 거래처",
        "synced": True,
    }
    assert [call[0] for call in client.calls] == [
        "/apiproxy/api16S11",
        "/apiproxy/api16S12",
    ]
    register_body = client.calls[1][1]
    assert register_body["dupCheck"] is False
    assert register_body["list"][0]["regNb"] == "1208147521"
    assert register_body["list"][0]["attrNm"] == "테스트 거래처"
    assert db.values[-1].status == "S"
    assert db.values[-1].partner_code == "0000001000"


def test_create_partner_with_email_registers_customer_contact() -> None:
    """세금계산서 화면이 담당자정보의 이메일을 쓰므로 기본정보와 같이 등록한다."""
    db = FakeDb()
    client = FakeClient(
        [
            {"resultCode": 0, "resultData": []},
            {"resultCode": 0, "resultData": [{"trCd": "0000001000"}]},
            {"resultCode": 0, "resultData": ["0000001000"]},
        ]
    )
    service = PartnerService(db, client=client)  # type: ignore[arg-type]

    request = valid_request()
    request.email = 'contact@example.com'
    result = service.create(request)

    assert result["contact_synced"] is True
    assert [call[0] for call in client.calls] == [
        "/apiproxy/api16S11",
        "/apiproxy/api16S12",
        "/apiproxy/api16S14",
    ]
    contact = client.calls[2][1]["list"][0]
    assert contact == {
        "coCd": "2000",
        "trCd": "0000001000",
        "empgrpCd": "100",
        "trchargeEmail": 'contact@example.com',
        "defYn": "1",
    }


def test_create_partner_contact_failure_does_not_break_registration() -> None:
    db = FakeDb()
    client = FakeClient(
        [
            {"resultCode": 0, "resultData": []},
            {"resultCode": 0, "resultData": [{"trCd": "0000001000"}]},
            RuntimeError("api16S14 실패"),
        ]
    )
    service = PartnerService(db, client=client)  # type: ignore[arg-type]

    request = valid_request()
    request.email = 'contact@example.com'
    result = service.create(request)

    assert result["synced"] is True
    assert result["contact_synced"] is False
    assert db.values[-1].status == "S"


def _fill_master(**extra: str) -> dict[str, Any]:
    return {"trCd": "0000001000", "trNm": "테스트 거래처", "trFg": "1", **extra}


def test_fill_missing_previews_contact_email_when_no_contact_exists() -> None:
    client = FakeClient([
        {"resultCode": 0, "resultData": [_fill_master()]},
    ])
    service = PartnerService(FakeDb(), client=client)  # type: ignore[arg-type]

    result = service.fill_missing(
        "2000", "0000001000", {"email": 'contact@example.com'}, apply=False
    )

    assert result["contact_email"] == 'contact@example.com'
    assert result["applied"] is False


def test_fill_missing_skips_contact_email_when_contact_exists() -> None:
    """수기 등록된 담당자가 있으면 정(defYn=1) 담당자를 또 만들지 않는다."""
    client = FakeClient([
        {"resultCode": 0, "resultData": [_fill_master(stempgrpTrchargeJop="영업")]},
    ])
    service = PartnerService(FakeDb(), client=client)  # type: ignore[arg-type]

    result = service.fill_missing(
        "2000", "0000001000", {"email": 'contact@example.com'}, apply=False
    )

    assert result["contact_email"] == ""


def test_fill_missing_apply_registers_contact_even_without_master_fields() -> None:
    """기본정보가 다 차 있어도 담당자 이메일이 없으면 api16S14는 호출한다."""
    master = _fill_master(
        regNb="1208147521", ceoNm="홍길동", business="서비스", jongmok="감정평가",
        divAddr1="서울시", tel="020000000", email='contact@example.com',
    )
    client = FakeClient([
        {"resultCode": 0, "resultData": [master]},
        {"resultCode": 0, "resultData": ["0000001000"]},
    ])
    service = PartnerService(FakeDb(), client=client)  # type: ignore[arg-type]

    result = service.fill_missing(
        "2000", "0000001000", {"email": 'contact@example.com'}, apply=True
    )

    assert result["fillable"] == {}
    assert result["applied"] is True
    assert result["contact_synced"] is True
    assert [call[0] for call in client.calls] == [
        "/apiproxy/api16S11",
        "/apiproxy/api16S14",
    ]


def test_create_partner_rejects_existing_business_number_and_records_failure() -> None:
    db = FakeDb()
    client = FakeClient(
        [
            {
                "resultCode": 0,
                "resultData": [
                    {"trCd": "0000001000", "trNm": "기존", "regNb": "1208147521"}
                ],
            }
        ]
    )
    service = PartnerService(db, client=client)  # type: ignore[arg-type]

    with pytest.raises(DuplicatePartnerError):
        service.create(valid_request())

    assert len(client.calls) == 1
    assert db.values[-1].status == "F"
    assert "이미 등록" in db.values[-1].error_msg


def test_list_partner_router_returns_flat_response() -> None:
    class FakeService:
        def list(self, company_code: str, **kwargs: Any) -> dict[str, Any]:
            assert company_code == "2000"
            return {
                "items": [{"partner_code": "0001", "name": "거래처"}],
                "page": 1,
                "page_size": 50,
                "count": 1,
            }

    app.dependency_overrides[get_partner_service] = lambda: FakeService()
    app.dependency_overrides[get_current_access] = voucher_access
    try:
        response = TestClient(app).get("/api/partners?company_code=2000")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "code": "0000",
        "message": "조회 완료",
        "data": {
            "items": [{"partner_code": "0001", "name": "거래처"}],
            "page": 1,
            "page_size": 50,
            "count": 1,
        },
    }


@pytest.mark.parametrize(
    ("search", "expected_filter"),
    [
        ("01000", {"trCd": "0000001000"}),
        ("120-81-47521", {"regNb": "1208147521"}),
        ("테스트 거래처", {"trNm": "테스트 거래처"}),
    ],
)
def test_list_partner_selects_filter_by_search_type(
    search: str, expected_filter: dict[str, str]
) -> None:
    client = FakeClient([{"resultCode": 0, "resultData": []}])
    service = PartnerService(FakeDb(), client=client)  # type: ignore[arg-type]

    service.list("2000", search=search)

    request_body = client.calls[0][1]
    assert all(request_body[key] == value for key, value in expected_filter.items())


def test_list_partner_excludes_unused_by_default() -> None:
    """폐지된 거래처가 후보에 섞이면 잘못된 코드로 전표가 나간다."""
    client = FakeClient([
        {"resultCode": 0, "resultData": []},
        {"resultCode": 0, "resultData": []},
    ])
    service = PartnerService(FakeDb(), client=client)  # type: ignore[arg-type]

    service.list("2000", search="국민은행")
    assert client.calls[0][1]["useYn"] == "1"

    service.list("2000", search="국민은행", include_unused=True)
    assert "useYn" not in client.calls[1][1]


def test_partner_api_is_closed_without_the_card_voucher_menu() -> None:
    """2026-08-08 이전에는 문지기가 없어 로그인 없이 거래처 명부를 훑을 수 있었다."""
    response = TestClient(app).get("/api/partners?company_code=2000")

    assert response.status_code == 401


def test_invalid_partner_router_uses_common_error_shape() -> None:
    app.dependency_overrides[get_current_access] = voucher_access
    response = TestClient(app).post(
        "/api/partners",
        json={
            "company_code": "2000",
            "business_no": "123",
            "name": "잘못된 요청",
        },
    )

    app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json()["success"] is False
    assert response.json()["code"] == "VALIDATION_ERROR"
