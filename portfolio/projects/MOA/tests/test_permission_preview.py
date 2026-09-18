import base64
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.access_policy import MENU_KEYS
from app.services.permission_preview import (
    PREVIEW_HEADER,
    PermissionPreviewError,
    apply_preview_policy,
    decode_preview_token,
)


def token(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def preview_payload(**overrides):
    data = {
        "v": 1,
        "usr_seq": 1171,
        "view_all_offices": True,
        "view_other_users": True,
        "menu_keys": list(MENU_KEYS),
    }
    data.update(overrides)
    return data


def access_context(**overrides):
    data = {
        "usr_seq": 1171,
        "usr_id": "4297",
        "emp_name": "장세희",
        "office_id": "10",
        "office_name": "본사",
        "department_code": "jae",
        "department_name": "재무팀",
        "employee_type": "재무팀",
        "is_appraiser": False,
        "is_operations": True,
        "view_all_offices": True,
        "view_other_users": True,
        "menu_permissions": {key: True for key in MENU_KEYS},
        "menu_keys": list(MENU_KEYS),
        "offices": [{"office_code": "10"}],
    }
    data.update(overrides)
    return data


def office(office_id: str, name: str):
    return SimpleNamespace(
        office_id=office_id,
        office_name=name,
        docid_prefix=office_id,
        division_code=office_id,
    )


def test_preview_token_round_trip_and_validation():
    payload = preview_payload()
    assert decode_preview_token(token(payload)) == payload

    with pytest.raises(PermissionPreviewError):
        decode_preview_token(token({**payload, "menu_keys": ["not-a-menu"]}))


def test_preview_policy_uses_ephemeral_finance_scope(monkeypatch):
    monkeypatch.setattr(
        "app.services.permission_preview.active_offices",
        lambda _db: [office("10", "본사"), office("11", "경기지사")],
    )
    result = apply_preview_policy(object(), access_context(), preview_payload())

    assert result["permission_preview"] is True
    assert result["read_only"] is True
    assert result["policy_source"] == "local_preview"
    assert result["view_all_offices"] is True
    assert result["view_other_users"] is True
    assert result["menu_permissions"]["permissionManage"] is True
    assert [item["office_code"] for item in result["offices"]] == ["10", "11"]


def test_preview_policy_cannot_expand_branch_to_hq_only_menu_or_all_offices(monkeypatch):
    monkeypatch.setattr(
        "app.services.permission_preview.get_office",
        lambda _db, _office_id: office("11", "경기지사"),
    )
    branch = access_context(
        usr_seq=200,
        usr_id="branch",
        emp_name="김평가",
        office_id="11",
        office_name="경기지사",
        department_code=None,
        department_name="평가사",
        employee_type="평가사",
        is_appraiser=True,
        is_operations=False,
    )
    payload = preview_payload(
        usr_seq=200,
        menu_keys=["appraisals", "salesInput", "permissionManage"],
    )
    result = apply_preview_policy(object(), branch, payload)

    assert result["view_all_offices"] is False
    assert result["view_other_users"] is True
    assert result["menu_keys"] == ["appraisals", "permissionManage"]
    assert [item["office_code"] for item in result["offices"]] == ["11"]


def test_preview_middleware_blocks_all_write_requests_before_route_execution():
    client = TestClient(
        app,
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 50000),
    )
    response = client.post(
        "/api/auth/login",
        headers={PREVIEW_HEADER: token(preview_payload())},
        json={"usr_id": 'REDACTED_CONFIGURE_LOCALLY', "password": 'REDACTED_CONFIGURE_LOCALLY'},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "PREVIEW_READ_ONLY"


def test_preview_token_is_rejected_outside_loopback():
    client = TestClient(
        app,
        base_url='http://192.0.2.10',
        client=('192.0.2.10', 50000),
    )
    response = client.get(
        "/desktop",
        params={"permission_preview": token(preview_payload())},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "PREVIEW_LOCAL_ONLY"
