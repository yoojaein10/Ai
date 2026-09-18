from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.common import ApiResponse
from app.services.permission_preview import (
    PREVIEW_QUERY,
    PermissionPreviewError,
    apply_preview_policy,
    decode_preview_token,
    is_loopback_preview_request,
)
from app.services.users import UserContextError, UserContextService

router = APIRouter(prefix="/api/users", tags=["users"])


def get_service(db: Session = Depends(get_db)) -> UserContextService:
    return UserContextService(db)


@router.get("/{usr_seq}/context", response_model=ApiResponse)
def get_user_context(
    request: Request,
    usr_seq: Annotated[str, Path(pattern=r"^[0-9]{1,10}$")],
    service: UserContextService = Depends(get_service),
) -> ApiResponse | JSONResponse:
    client_ip = request.client.host if request.client else None
    try:
        data = service.context(usr_seq, client_ip)
    except UserContextError as exc:
        status_code = (
            status.HTTP_404_NOT_FOUND
            if exc.code == "USER_NOT_FOUND"
            else status.HTTP_403_FORBIDDEN
        )
        response = ApiResponse(success=False, code=exc.code, message=str(exc), data=None)
        return JSONResponse(
            status_code=status_code, content=response.model_dump(mode="json")
        )
    return ApiResponse(success=True, code="0000", message="조회 완료", data=data)


@router.get("/{usr_seq}/context-preview", response_model=ApiResponse)
def get_user_context_preview(
    request: Request,
    usr_seq: Annotated[str, Path(pattern=r"^[0-9]{1,10}$")],
    preview_token: Annotated[str, Query(alias=PREVIEW_QUERY)],
    service: UserContextService = Depends(get_service),
) -> ApiResponse | JSONResponse:
    """감사로그·권한 저장 없이 로컬에서만 사용하는 읽기 전용 컨텍스트."""
    if not is_loopback_preview_request(request):
        response = ApiResponse(
            success=False,
            code="PREVIEW_LOCAL_ONLY",
            message="권한 테스트는 로컬에서만 사용할 수 있습니다.",
            data=None,
        )
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content=response.model_dump(mode="json"),
        )
    try:
        payload = decode_preview_token(preview_token)
        if int(usr_seq) != int(payload["usr_seq"]):
            raise PermissionPreviewError(
                "선택한 직원과 권한 테스트 사용자가 일치하지 않습니다."
            )
        data = apply_preview_policy(
            service.db,
            service._resolve(usr_seq),
            payload,
        )
    except UserContextError as exc:
        status_code = (
            status.HTTP_404_NOT_FOUND
            if exc.code == "USER_NOT_FOUND"
            else status.HTTP_403_FORBIDDEN
        )
        response = ApiResponse(success=False, code=exc.code, message=str(exc), data=None)
        return JSONResponse(
            status_code=status_code,
            content=response.model_dump(mode="json"),
        )
    except PermissionPreviewError as exc:
        response = ApiResponse(
            success=False,
            code="PREVIEW_INVALID",
            message=str(exc),
            data=None,
        )
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=response.model_dump(mode="json"),
        )
    return ApiResponse(
        success=True,
        code="0000",
        message="로컬 읽기 전용 권한 테스트",
        data=data,
    )
