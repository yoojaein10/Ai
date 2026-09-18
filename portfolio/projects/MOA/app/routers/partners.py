from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.amaranth.exceptions import AmaranthError
from app.database import get_db
from app.dependencies import AccessContext, require_menu
from app.schemas.common import ApiResponse
from app.schemas.partner import PartnerCreate
from app.services.partners import (
    DuplicatePartnerError,
    PartnerNotFoundError,
    PartnerService,
)

router = APIRouter(prefix="/api/partners", tags=["partners"])

# 거래처 조회·등록은 카드전표 화면(dashboard.js voucherContext)에서만 쓴다.
# 2026-08-08 까지 아무 문지기도 없어서, 로그인하지 않아도 거래처 명부 전체를
# 페이지당 1000건씩 훑고 Amaranth 에 새 거래처를 만들 수 있었다.
_REQUIRE_VOUCHER_MENU = require_menu("cardVouchers")


def get_partner_service(db: Session = Depends(get_db)) -> PartnerService:
    return PartnerService(db)


@router.post("", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
def create_partner(
    request: PartnerCreate,
    service: PartnerService = Depends(get_partner_service),
    _access: AccessContext = Depends(_REQUIRE_VOUCHER_MENU),
) -> ApiResponse | JSONResponse:
    try:
        data = service.create(request)
        return ApiResponse(
            success=True, code="0000", message="거래처 등록 완료", data=data
        )
    except DuplicatePartnerError as exc:
        return _error_response(
            status.HTTP_409_CONFLICT,
            "PARTNER_DUPLICATE",
            str(exc),
            exc.partner,
        )
    except AmaranthError as exc:
        return _error_response(
            status.HTTP_502_BAD_GATEWAY, "A10_ERROR", str(exc)
        )


@router.get("", response_model=ApiResponse)
def list_partners(
    company_code: Annotated[str, Query(min_length=4, max_length=4)],
    search: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=1000)] = 50,
    service: PartnerService = Depends(get_partner_service),
    _access: AccessContext = Depends(_REQUIRE_VOUCHER_MENU),
) -> ApiResponse | JSONResponse:
    try:
        data = service.list(
            company_code, search=search, page=page, page_size=page_size
        )
        return ApiResponse(success=True, code="0000", message="조회 완료", data=data)
    except AmaranthError as exc:
        return _error_response(
            status.HTTP_502_BAD_GATEWAY, "A10_ERROR", str(exc)
        )


@router.get("/{business_no}", response_model=ApiResponse)
def get_partner(
    business_no: str,
    company_code: Annotated[str, Query(min_length=4, max_length=4)],
    service: PartnerService = Depends(get_partner_service),
    _access: AccessContext = Depends(_REQUIRE_VOUCHER_MENU),
) -> ApiResponse | JSONResponse:
    normalized = "".join(character for character in business_no if character.isdigit())
    if len(normalized) != 10:
        return _error_response(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "INVALID_BUSINESS_NO",
            "사업자번호는 10자리여야 합니다.",
        )
    try:
        data = service.get(company_code, normalized)
        return ApiResponse(success=True, code="0000", message="조회 완료", data=data)
    except PartnerNotFoundError as exc:
        return _error_response(status.HTTP_404_NOT_FOUND, "PARTNER_NOT_FOUND", str(exc))
    except AmaranthError as exc:
        return _error_response(
            status.HTTP_502_BAD_GATEWAY, "A10_ERROR", str(exc)
        )


def _error_response(
    http_status: int,
    code: str,
    message: str,
    data: object = None,
) -> JSONResponse:
    body = ApiResponse(success=False, code=code, message=message, data=data)
    return JSONResponse(status_code=http_status, content=body.model_dump(mode="json"))

