"""입금 적용용 계산서 관리 API (2026-09-10) — 계산서 일괄발급 화면의 '계산서 적용' 탭이 쓴다.

모계산서 목록·잔액·적용 내역 조회, 지금 적용, 수동 적용·해제. 본사 재무·집행부만(taxBulk).
"""

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    AccessContext,
    require_menu,
    require_menu_write,
    require_operations_user,
    require_same_requester,
)
from app.schemas.common import ApiResponse
from app.services import invoice_pool

router = APIRouter(prefix="/api/taxinvoice/pool", tags=["taxinvoice"])
_MESSAGE = "계산서 적용 관리는 본사 재무팀·집행부만 쓸 수 있습니다."


class ApplyRequest(BaseModel):
    requester_usr_seq: int
    pool_id: int | None = None          # 없으면 잔액 남은 모계산서 전부


class ApplyManualRequest(BaseModel):
    requester_usr_seq: int
    pool_id: int
    doc_id: str = Field(min_length=1, max_length=50)
    amount: int = Field(gt=0)


class UnapplyRequest(BaseModel):
    requester_usr_seq: int
    row_id: int


def _error(code: str, message: str) -> JSONResponse:
    body = ApiResponse(success=False, code=code, message=message, data=None)
    return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=body.model_dump(mode="json"))


@router.get("", response_model=ApiResponse)
def list_pools(
    include_done: bool = False,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("taxBulk")),
) -> ApiResponse:
    require_operations_user(access, _MESSAGE)
    pools = invoice_pool.list_pools(db, include_done=include_done)
    return ApiResponse(success=True, code="0000", message=f"{len(pools)}건", data={"pools": pools})


@router.post("/apply", response_model=ApiResponse)
def apply(
    request: ApplyRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu_write("taxBulk")),
) -> ApiResponse | JSONResponse:
    require_same_requester(access, request.requester_usr_seq)
    require_operations_user(access, _MESSAGE)
    try:
        data = invoice_pool.apply_pool(db, request.pool_id) if request.pool_id else invoice_pool.apply_all(db)
    except invoice_pool.InvoicePoolError as exc:
        return _error("BAD_REQUEST", str(exc))
    count = data["applied"] if isinstance(data["applied"], int) else len(data["applied"])
    return ApiResponse(success=True, code="0000", message=f"적용 {count}건", data=data)


@router.post("/apply-manual", response_model=ApiResponse)
def apply_manual(
    request: ApplyManualRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu_write("taxBulk")),
) -> ApiResponse | JSONResponse:
    require_same_requester(access, request.requester_usr_seq)
    require_operations_user(access, _MESSAGE)
    try:
        data = invoice_pool.apply_manual(db, request.pool_id, request.doc_id, request.amount)
    except invoice_pool.InvoicePoolError as exc:
        return _error("BAD_REQUEST", str(exc))
    return ApiResponse(success=True, code="0000", message="적용 완료", data=data)


@router.post("/unapply", response_model=ApiResponse)
def unapply(
    request: UnapplyRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu_write("taxBulk")),
) -> ApiResponse | JSONResponse:
    require_same_requester(access, request.requester_usr_seq)
    require_operations_user(access, _MESSAGE)
    try:
        data = invoice_pool.unapply(db, request.row_id)
    except invoice_pool.InvoicePoolError as exc:
        return _error("BAD_REQUEST", str(exc))
    return ApiResponse(success=True, code="0000", message="해제 완료", data=data)
