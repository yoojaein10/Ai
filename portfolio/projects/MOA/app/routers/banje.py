"""반제 리스트 API (본사 관리 화면). 외상매출금 반제 / 선수금 반제."""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    AccessContext,
    get_current_access,
    require_menu_access,
    resolve_office_scope,
)
from app.schemas.common import ApiResponse
from app.services.banje import banje_export, banje_list, banje_open_list
from app.services.excel_export import XLSX_MEDIA_TYPE, build_xlsx, xlsx_headers

router = APIRouter(prefix="/api/banje", tags=["banje"])


def _menu_key(kind: str) -> str:
    return "receivableReconcile" if kind == "receivable" else "advanceReconcile"


@router.get("", response_model=ApiResponse)
def get_banje(
    kind: Literal["receivable", "advance"],
    date_from: date | None = None,
    date_to: date | None = None,
    mode: Literal["settled", "open"] = "settled",
    date_basis: Literal["settle", "gen"] = "settle",
    office_code: str = "10",
    include_nonstd: bool = False,
    as_of: date | None = None,
    doc: str = "",
    db: Session = Depends(get_db),
    access: AccessContext = Depends(get_current_access),
) -> ApiResponse:
    """mode=settled면 반제 내역(기간=반제일/생성일 필수), mode=open이면 미반제 잔액.

    open 모드의 조회 조건은 잔액 기준일(as_of) 하나다 — 발생일 기간은 걸지 않는다.
    date_basis는 settled 모드의 기간 기준(settle=반제일, gen=생성일).
    as_of는 open 모드 전용 잔액 기준일(미지정 시 오늘).
    doc는 감정서번호 검색어 — 주면 기간을 안 걸고 전 기간에서 찾는다.
    """
    require_menu_access(access, _menu_key(kind))
    office_code = resolve_office_scope(access, office_code) or "10"
    doc = doc.strip()
    if mode == "open":
        data = banje_open_list(db, kind, None, None, office_code, include_nonstd, as_of, doc)
    else:
        # 번호 검색은 기간을 대신하는 조건이라 기간이 없어도 된다.
        if not doc and (date_from is None or date_to is None):
            return ApiResponse(
                success=False, code="VALIDATION_ERROR",
                message="기간(date_from, date_to)을 선택하거나 감정서번호를 입력하세요.",
                data=None,
            )
        data = banje_list(db, kind, date_from, date_to, office_code, date_basis, doc)
    return ApiResponse(success=True, code="0000", message="조회 완료", data=data)


@router.get("/export.xlsx", response_model=None)
def export_banje(
    kind: Literal["receivable", "advance"],
    date_from: date | None = None,
    date_to: date | None = None,
    mode: Literal["settled", "open"] = "settled",
    date_basis: Literal["settle", "gen"] = "settle",
    office_code: str = "10",
    include_nonstd: bool = False,
    as_of: date | None = None,
    doc: str = "",
    db: Session = Depends(get_db),
    access: AccessContext = Depends(get_current_access),
) -> Response:
    """화면 조회 조건 그대로 엑셀로 내보낸다 (데스크톱 앱에서도 받을 수 있게 서버가 생성)."""
    require_menu_access(access, _menu_key(kind))
    office_code = resolve_office_scope(access, office_code) or "10"
    doc = doc.strip()
    if mode == "open":
        date_from = date_to = None  # 미반제 잔액은 잔액 기준일만 쓴다
    elif not doc and (date_from is None or date_to is None):
        return Response(
            content="기간(date_from, date_to)을 선택하거나 감정서번호를 입력하세요.",
            status_code=422,
        )
    name, columns, rows = banje_export(
        db, kind, mode, date_from, date_to, office_code, date_basis, include_nonstd, as_of, doc
    )
    return Response(
        content=build_xlsx(name[:31], columns, rows),  # 시트명은 31자 제한
        media_type=XLSX_MEDIA_TYPE,
        headers=xlsx_headers(name),
    )
