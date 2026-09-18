"""세금계산서 일괄 발급 API (2026-08-27) — 계산서 일괄발급 화면(/desktop/tax-bulk)이 쓴다.

본사 재무·집행부만(taxBulk 메뉴 + 운영부서). 발급은 실제 국세청 전송이라 쓰기 관문 +
본인 요청 확인까지 건다. 한 번에 MAX_ISSUE 건.
"""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.dependencies import (
    AccessContext,
    require_menu,
    require_menu_write,
    require_operations_user,
    require_same_requester,
    resolve_office_scope,
)
from app.schemas.common import ApiResponse
from app.services import tax_bulk

router = APIRouter(prefix="/api/taxinvoice/bulk", tags=["taxinvoice"])
_MESSAGE = "계산서 일괄발급은 본사 재무팀·집행부만 쓸 수 있습니다."


class BulkItem(BaseModel):
    kind: Literal["general", "syndicate", "kb"]
    doc_id: str = Field(min_length=1, max_length=50)
    tr_cd: str = Field(default="", max_length=10)
    corp_num: str = Field(default="", max_length=12)
    partner_name: str = Field(default="", max_length=200)
    supply_cost: int = Field(ge=0)
    tax: int = Field(ge=0)
    write_date: str = Field(min_length=8, max_length=10)      # YYYYMMDD 또는 YYYY-MM-DD
    email: str = Field(default="", max_length=100)
    item_name: str | None = Field(default=None, max_length=100)


class BulkIssueRequest(BaseModel):
    requester_usr_seq: int
    items: list[BulkItem] = Field(min_length=1, max_length=tax_bulk.MAX_ISSUE)


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    body = ApiResponse(success=False, code=code, message=message, data=None)
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


@router.get("/candidates", response_model=ApiResponse)
def candidates(
    kind: Literal["general", "syndicate", "kb"],
    date_from: date,
    date_to: date,
    pay_status: Literal["전체", "완납", "부분입금"] = "전체",
    only_unissued: bool = True,
    office_code: Annotated[str, Query(pattern=r"^[0-9A-Za-z]+$", max_length=10)] = "10",
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("taxBulk")),
) -> ApiResponse | JSONResponse:
    """입금된 건 중 발급 후보 — 일반·대주단·국민약식 탭."""
    require_operations_user(access, _MESSAGE)
    try:
        data = tax_bulk.list_candidates(
            db, kind=kind, date_from=date_from, date_to=date_to,
            office_code=resolve_office_scope(access, office_code),
            pay_status=pay_status, only_unissued=only_unissued,
        )
    except tax_bulk.TaxBulkError as exc:
        return _error(status.HTTP_400_BAD_REQUEST, "BAD_REQUEST", str(exc))
    data["is_test"] = get_settings().popbill_is_test
    data["default_email"] = tax_bulk.DEFAULT_EMAIL
    return ApiResponse(success=True, code="0000", message="조회 완료", data=data)


@router.post("/issue", response_model=ApiResponse)
def issue(
    request: BulkIssueRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu_write("taxBulk")),
) -> ApiResponse | JSONResponse:
    """체크한 건을 한 장씩 팝빌로 발행한다. 행마다 결과(승인번호·실패 사유)를 돌려준다."""
    require_same_requester(access, request.requester_usr_seq)
    require_operations_user(access, _MESSAGE)
    if not get_settings().is_popbill_configured:
        return _error(status.HTTP_400_BAD_REQUEST, "POPBILL_NOT_CONFIGURED", "팝빌 설정이 없습니다.")
    try:
        data = tax_bulk.issue_bulk(db, [item.model_dump() for item in request.items])
    except tax_bulk.TaxBulkError as exc:
        return _error(status.HTTP_400_BAD_REQUEST, "BAD_REQUEST", str(exc))
    message = f"발급 {data['issued']}건" + (f" · 건너뜀 {data['skipped']}건" if data["skipped"] else "") \
        + (f" · 실패 {data['failed']}건" if data["failed"] else "")
    return ApiResponse(success=True, code="0000", message=message, data=data)
