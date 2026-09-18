"""신한은행 발송기한 관리 API — 독립 화면 /desktop/shinhan-delay 전용 (2026-09-02).

개인 예외로만 켜는 메뉴 키(shinhanDelay) — 이일우·유재인·원동하·엄기원
(scripts/seed_shinhan_delay_access.py). 일계표 대사(bankReconcile)와 같은 패턴.
"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import AccessContext, require_menu
from app.schemas.common import ApiResponse
from app.services import shinhan_delay
from app.services.shinhan_delay import ShinhanDelayError

router = APIRouter(prefix="/api/shinhan-delay", tags=["shinhan-delay"])

_MAX_DAYS = 400


def _period(date_from: "date | None", date_to: "date | None") -> "tuple[date, date]":
    end = date_to or date.today()
    start = date_from or end - timedelta(days=30)
    if start > end or (end - start).days > _MAX_DAYS:
        raise ShinhanDelayError(f"기간은 {_MAX_DAYS}일 이내로, 시작이 끝보다 앞이어야 합니다.")
    return start, end


@router.get("/summary", response_model=ApiResponse)
def get_summary(
    date_from: "date | None" = None,
    date_to: "date | None" = None,
    check_gubun: str = "전체",
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("shinhanDelay")),
) -> ApiResponse | JSONResponse:
    try:
        start, end = _period(date_from, date_to)
        rows = shinhan_delay.summary(
            db, date_from=start, date_to=end, check_gubun=check_gubun
        )
    except ShinhanDelayError as exc:
        return _bad_request(str(exc))
    return ApiResponse(
        success=True, code="0000", message="조회 완료",
        data={"items": rows, "date_from": start.isoformat(), "date_to": end.isoformat()},
    )


@router.get("/detail", response_model=ApiResponse)
def get_detail(
    date_from: "date | None" = None,
    date_to: "date | None" = None,
    office: str = "",
    day_gubun: str = "",
    check_gubun: str = "전체",
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("shinhanDelay")),
) -> ApiResponse | JSONResponse:
    try:
        start, end = _period(date_from, date_to)
        rows = shinhan_delay.detail(
            db, date_from=start, date_to=end,
            office=office, day_gubun=day_gubun, check_gubun=check_gubun,
        )
    except ShinhanDelayError as exc:
        return _bad_request(str(exc))
    return ApiResponse(
        success=True, code="0000", message="조회 완료", data={"items": rows}
    )


class MemoRequest(BaseModel):
    doc_id: str = Field(min_length=1, max_length=30)
    edit_yn: bool = False
    memo: str = Field(default="", max_length=1000)


@router.post("/memo", response_model=ApiResponse)
def save_memo(
    request: MemoRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("shinhanDelay")),
) -> ApiResponse | JSONResponse:
    try:
        shinhan_delay.save_memo(
            db, doc_id=request.doc_id, edit_yn=request.edit_yn, memo=request.memo
        )
    except ShinhanDelayError as exc:
        return _bad_request(str(exc))
    return ApiResponse(success=True, code="0000", message="저장 완료", data=None)


def _bad_request(message: str) -> JSONResponse:
    response = ApiResponse(success=False, code="BAD_REQUEST", message=message, data=None)
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=response.model_dump(mode="json"),
    )
