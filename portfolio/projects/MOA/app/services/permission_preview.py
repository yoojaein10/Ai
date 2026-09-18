"""로컬 개발용 임시 권한 테스트.

권한 시안의 값을 DB에 저장하지 않고 실제 조회 화면에 적용한다. 토큰은 서명된
자격증명이 아니므로 루프백 요청에서만 허용하며, 테스트 모드의 변경 요청은
미들웨어와 프런트 양쪽에서 차단한다.
"""

from __future__ import annotations

import base64
import binascii
import json
from ipaddress import ip_address
from typing import Any, Mapping

from fastapi import Request
from sqlalchemy.orm import Session

from app.services.access_policy import (
    BRANCH_FINANCE_MENU_KEYS,
    HEAD_OFFICE_ID,
    MENU_KEYS,
    PolicyIdentity,
    available_menu_keys,
)
from app.services.office_lookup import active_offices, get_office

PREVIEW_HEADER = "X-MOA-PREVIEW-POLICY"
PREVIEW_QUERY = "permission_preview"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
MAX_TOKEN_LENGTH = 4096


class PermissionPreviewError(ValueError):
    pass


def is_loopback_preview_request(request: Request) -> bool:
    """URL 호스트와 실제 접속 주소가 모두 루프백일 때만 테스트 토큰을 허용한다."""
    hostname = (request.url.hostname or "").lower()
    if hostname not in {"127.0.0.1", "localhost", "::1"}:
        return False
    if not request.client:
        return False
    try:
        return ip_address(request.client.host).is_loopback
    except ValueError:
        return False


def decode_preview_token(raw: str) -> dict[str, Any]:
    if not raw or len(raw) > MAX_TOKEN_LENGTH:
        raise PermissionPreviewError("권한 테스트 값이 없거나 너무 깁니다.")
    try:
        padding = "=" * (-len(raw) % 4)
        decoded = base64.urlsafe_b64decode((raw + padding).encode("ascii"))
        payload = json.loads(decoded.decode("utf-8"))
    except (binascii.Error, UnicodeError, ValueError, TypeError) as exc:
        raise PermissionPreviewError("권한 테스트 값을 해석할 수 없습니다.") from exc
    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise PermissionPreviewError("지원하지 않는 권한 테스트 형식입니다.")
    usr_seq = payload.get("usr_seq")
    menu_keys = payload.get("menu_keys")
    if (
        not isinstance(usr_seq, int)
        or usr_seq <= 0
        or not isinstance(menu_keys, list)
        or len(menu_keys) > len(MENU_KEYS)
        or any(not isinstance(key, str) or key not in MENU_KEYS for key in menu_keys)
        or not isinstance(payload.get("view_all_offices"), bool)
        or not isinstance(payload.get("view_other_users"), bool)
    ):
        raise PermissionPreviewError("권한 테스트 항목이 올바르지 않습니다.")
    return {
        "v": 1,
        "usr_seq": usr_seq,
        "menu_keys": list(dict.fromkeys(menu_keys)),
        "view_all_offices": payload["view_all_offices"],
        "view_other_users": payload["view_other_users"],
    }


def _identity_from_access(access: Mapping[str, Any]) -> PolicyIdentity:
    return PolicyIdentity(
        usr_seq=int(access["usr_seq"]),
        usr_id=str(access["usr_id"]),
        emp_name=str(access["emp_name"]),
        office_id=str(access["office_id"]),
        department_code=access.get("department_code"),
        department_name=str(access["department_name"]),
        employee_type=str(access["employee_type"]),
        is_appraiser=bool(access.get("is_appraiser")),
    )


def apply_preview_policy(
    db: Session,
    access: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """검증된 임시 정책을 사용자 기본 컨텍스트에 덮어쓴다."""
    if int(access["usr_seq"]) != int(payload["usr_seq"]):
        raise PermissionPreviewError("선택한 직원과 권한 테스트 사용자가 일치하지 않습니다.")

    identity = _identity_from_access(access)
    available = available_menu_keys(identity)
    menu_keys = {
        key for key in payload["menu_keys"]
        if key in available
    }
    view_all = (
        identity.office_id == HEAD_OFFICE_ID
        and bool(payload["view_all_offices"])
    )
    is_branch_finance = (
        identity.office_id != HEAD_OFFICE_ID
        and not identity.is_appraiser
        and bool(menu_keys.intersection(BRANCH_FINANCE_MENU_KEYS))
    )
    can_view_other_users = (
        bool(access.get("is_operations"))
        or identity.is_appraiser
        or is_branch_finance
    )
    view_other_users = (
        can_view_other_users and bool(payload["view_other_users"])
    )

    office_rows = active_offices(db) if view_all else [get_office(db, identity.office_id)]
    offices = [
        {
            "office_code": item.office_id,
            "office_name": item.office_name,
            "docid_prefix": item.docid_prefix,
            "division_code": item.division_code,
        }
        for item in office_rows
        if item is not None
    ]

    result = dict(access)
    result.update(
        view_all_offices=view_all,
        view_other_users=view_other_users,
        menu_permissions={key: key in menu_keys for key in MENU_KEYS},
        menu_keys=[key for key in MENU_KEYS if key in menu_keys],
        policy_source="local_preview",
        permission_preview=True,
        read_only=True,
        offices=offices,
    )
    return result
