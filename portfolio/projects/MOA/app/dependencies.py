"""FastAPI 공통 사용자·메뉴·데이터 범위 권한 검사."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.services.auth_token import verify as verify_token
from app.services.permission_preview import (
    PREVIEW_HEADER,
    PREVIEW_QUERY,
    PermissionPreviewError,
    apply_preview_policy,
    decode_preview_token,
    is_loopback_preview_request,
)
from app.services.users import UserContextError, UserContextService

AccessContext = dict[str, Any]


def _deny(code: str, message: str, http_status: int = status.HTTP_403_FORBIDDEN) -> None:
    raise HTTPException(
        status_code=http_status,
        detail={"code": code, "message": message},
    )


def get_current_access(
    request: Request,
    db: Session = Depends(get_db),
    header_usr_seq: Annotated[str | None, Header(alias="X-MOA-USR-SEQ")] = None,
    query_usr_seq: Annotated[str | None, Query(alias="usr_seq")] = None,
    query_usr: Annotated[str | None, Query(alias="usr")] = None,
    preview_header: Annotated[str | None, Header(alias=PREVIEW_HEADER)] = None,
    preview_query: Annotated[str | None, Query(alias=PREVIEW_QUERY)] = None,
) -> AccessContext:
    """API 호출 사용자를 한 곳에서 해석한다.

    일반 fetch는 X-MOA-USR-SEQ, 브라우저/데스크톱 다운로드는 usr_seq 쿼리를 쓴다.
    """
    usr_seq = header_usr_seq or query_usr_seq or query_usr
    if not usr_seq or not str(usr_seq).isdigit():
        _deny("AUTH_REQUIRED", "로그인 사용자 정보가 없습니다.", status.HTTP_401_UNAUTHORIZED)
    try:
        access = UserContextService(db)._resolve(str(usr_seq))
    except UserContextError as exc:
        http_status = (
            status.HTTP_404_NOT_FOUND
            if exc.code == "USER_NOT_FOUND"
            else status.HTTP_403_FORBIDDEN
        )
        _deny(exc.code, str(exc), http_status)
    preview_token = preview_header or preview_query
    if not preview_token:
        return access
    if not is_loopback_preview_request(request):
        _deny("PREVIEW_LOCAL_ONLY", "권한 테스트는 로컬에서만 사용할 수 있습니다.")
    if request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
        _deny("PREVIEW_READ_ONLY", "권한 테스트에서는 저장·승인·발급·변경할 수 없습니다.")
    try:
        payload = decode_preview_token(preview_token)
        return apply_preview_policy(db, access, payload)
    except PermissionPreviewError as exc:
        _deny("PREVIEW_INVALID", str(exc), status.HTTP_400_BAD_REQUEST)


def require_menu(menu_key: str) -> Callable[..., AccessContext]:
    def dependency(access: AccessContext = Depends(get_current_access)) -> AccessContext:
        require_menu_access(access, menu_key)
        return access

    return dependency


def require_menu_write(menu_key: str) -> Callable[..., AccessContext]:
    """메뉴 권한 **더하기 로그인 증표**. 무언가를 바꾸는 API 에 쓴다.

    왜 조회와 다르게 다루나 (2026-08-16 진단)
        get_current_access 는 X-MOA-USR-SEQ 헤더의 숫자를 isdigit() 만 보고
        그 사람으로 친다 — 서명도 세션도 없다. EXE 런처가 비밀번호 없이
        ?usr= 로 넘어오는 구조라 그 경로 자체를 지금 끊을 수는 없다.

        하지만 조회가 새는 것과 **전사 권한을 갈아치우는 것**은 무게가 다르다.
        누구든 재무팀 usr_seq 하나만 넣으면 부서 묶음을 바꿀 수 있었다.
        쓰기는 전부 브라우저(로그인 화면을 거친 곳)에서 오므로, 여기서만
        증표를 요구하면 EXE 를 건드리지 않고 그 구멍을 닫는다.

        읽기까지 증표로 막는 것은 EXE 손잡이를 APWorks 쪽과 어떻게 신뢰할지
        정한 뒤의 일이다 — 지금 하면 전 사원이 프로그램을 못 연다.
    """
    def dependency(
        request: Request,
        access: AccessContext = Depends(get_current_access),
        auth_token: Annotated[str | None, Header(alias="X-MOA-AUTH")] = None,
    ) -> AccessContext:
        require_menu_access(access, menu_key)
        if not get_settings().auth_require_token_for_writes:
            return access
        signed_usr_seq = verify_token(auth_token)
        if signed_usr_seq is None:
            _deny(
                "AUTH_TOKEN_REQUIRED",
                "다시 로그인해 주세요. 권한을 바꾸려면 로그인 확인이 필요합니다.",
                status.HTTP_401_UNAUTHORIZED,
            )
        # 증표 속 usr_seq 와 헤더의 usr_seq 가 다르면, 남의 증표를 들고 자기
        # 번호를 적어 보낸 것이다. 증표 쪽을 믿되 요청은 거절한다.
        if int(signed_usr_seq) != int(access.get("usr_seq") or 0):
            _deny(
                "AUTH_TOKEN_MISMATCH",
                "로그인 정보가 맞지 않습니다. 다시 로그인해 주세요.",
                status.HTTP_401_UNAUTHORIZED,
            )
        return access

    return dependency


def require_menu_access(access: AccessContext, menu_key: str) -> None:
    if not access.get("menu_permissions", {}).get(menu_key, False):
        _deny("MENU_ACCESS_DENIED", "이 메뉴를 사용할 권한이 없습니다.")


def resolve_office_scope(
    access: AccessContext,
    requested_office: str | None,
) -> str | None:
    """요청 지사를 로그인 사용자의 허용 범위로 강제한다. None은 전체를 뜻한다."""
    requested = None if requested_office in (None, "all") else str(requested_office)
    own_office = str(access["office_id"])
    if requested is None:
        if access.get("view_all_offices"):
            return None
        if requested_office == "all":
            _deny("OFFICE_SCOPE_DENIED", "전체지사 조회 권한이 없습니다.")
        return own_office
    if requested != own_office and not access.get("view_all_offices"):
        _deny("OFFICE_SCOPE_DENIED", "다른 지사 자료를 조회할 수 없습니다.")
    allowed = {
        str(item["office_code"]) for item in access.get("offices", [])
    }
    if allowed and requested not in allowed:
        _deny("OFFICE_SCOPE_DENIED", "조회할 수 없는 지사입니다.")
    return requested


def scoped_employee_name(access: AccessContext) -> str | None:
    """다른 직원 조회가 없으면 유치자/조사자 범위를 로그인 사용자로 고정한다."""
    return None if access.get("view_other_users") else str(access["emp_name"])


def require_same_requester(access: AccessContext, requester_usr_seq: int) -> None:
    if int(access["usr_seq"]) != int(requester_usr_seq):
        _deny("REQUESTER_MISMATCH", "로그인 사용자와 요청자가 일치하지 않습니다.")


def require_operations_user(access: AccessContext, message: str) -> None:
    if not access.get("is_operations"):
        _deny("OPERATION_ACCESS_DENIED", message)


def require_head_office_finance(access: AccessContext, message: str) -> None:
    """본사 재무팀만 허용한다 (본사 집행부·지사 재무는 제외)."""
    is_head_office_finance = (
        str(access.get("office_id")) == "10"
        and "재무" in str(access.get("department_name") or "")
    )
    if not is_head_office_finance:
        _deny("HEAD_OFFICE_FINANCE_ONLY", message)


def assert_document_access(
    db: Session,
    doc_id: str,
    access: AccessContext,
) -> None:
    """감정서 단건 API가 목록 범위를 우회하지 못하도록 동일 조건을 검사한다."""
    database = get_settings().mssql_source_db
    if not database.replace("_", "").isalnum():
        raise RuntimeError("MSSQL_SOURCE_DB 이름이 올바르지 않습니다.")
    conditions = ["DocID = :doc_id"]
    params: dict[str, Any] = {"doc_id": doc_id}
    if not access.get("view_all_offices"):
        conditions.append("Office = :office_code")
        params["office_code"] = access["office_id"]
    person = scoped_employee_name(access)
    if person:
        conditions.append("(Manager LIKE :scope_person OR Charge LIKE :scope_person)")
        params["scope_person"] = f"%{person}%"
    row = db.execute(
        text(
            f"SELECT TOP 1 DocID FROM [{database}].dbo.apw_masterex "
            f"WHERE {' AND '.join(conditions)}"
        ),
        params,
    ).first()
    if row is None:
        _deny("DOCUMENT_ACCESS_DENIED", "조회할 수 없는 감정서입니다.", status.HTTP_404_NOT_FOUND)
