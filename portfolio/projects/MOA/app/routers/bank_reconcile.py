"""일계표 대사 API — 사이버브랜치 입·출금 ↔ 아마란스 보통예금(1030000) 전표.

본사 재무 개별권한(bankReconcile) + 운영부서만. 읽기만 한다 — 사이버브랜치·전표 캐시
어느 쪽에도 쓰지 않는다.
"""

from datetime import date

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import AccessContext, require_menu, require_operations_user
from app.schemas.common import ApiResponse
from app.services.bank_reconcile import build_report, export_sheets
from app.services.deposit_source import DepositSourceError
from app.services.excel_export import XLSX_MEDIA_TYPE, build_xlsx_sheets, xlsx_headers

router = APIRouter(prefix="/api/bank-reconcile", tags=["bank-reconcile"])

MAX_DAYS = 31
_GATE_MESSAGE = "일계표 대사는 본사 재무팀·집행부만 볼 수 있습니다."


def _period_error(date_from: date, date_to: date) -> "str | None":
    if date_to < date_from:
        return "종료일이 시작일보다 앞섭니다."
    if (date_to - date_from).days + 1 > MAX_DAYS:
        return f"조회 기간은 {MAX_DAYS}일 이내로 잡으세요."
    return None


def _fail(code: str, message: str, status_code: int) -> JSONResponse:
    body = ApiResponse(success=False, code=code, message=message, data=None)
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


@router.get("", response_model=ApiResponse)
def get_report(
    date_from: date,
    date_to: date,
    division: str = "",
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("bankReconcile")),
) -> ApiResponse | JSONResponse:
    require_operations_user(access, _GATE_MESSAGE)
    error = _period_error(date_from, date_to)
    if error:
        return _fail("BAD_PERIOD", error, 400)
    try:
        data = build_report(db, date_from, date_to, division.strip() or None)
    except DepositSourceError as exc:
        return _fail("BANK_SOURCE_ERROR", str(exc), 502)
    return ApiResponse(success=True, code="0000", message="조회 완료", data=data)


@router.get("/export.xlsx", response_model=None)
def export_report(
    date_from: date,
    date_to: date,
    division: str = "",
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("bankReconcile")),
) -> Response:
    require_operations_user(access, _GATE_MESSAGE)
    error = _period_error(date_from, date_to)
    if error:
        return Response(content=error, status_code=400, media_type="text/plain; charset=utf-8")
    try:
        report = build_report(db, date_from, date_to, division.strip() or None)
    except DepositSourceError as exc:
        return Response(content=str(exc), status_code=502, media_type="text/plain; charset=utf-8")
    return Response(
        content=build_xlsx_sheets(export_sheets(report)),
        media_type=XLSX_MEDIA_TYPE,
        headers=xlsx_headers(f"일계표대사_{date_from}_{date_to}"),
    )
