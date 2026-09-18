"""배분/수금 진행 API.

주의: 이 독스트링은 오래 "(본사)" 라고 적혀 있었지만 사실이 아니다 —
SQL 이 m.Office 로 지사를 가르고 지사 자료가 실제로 나온다(2026-08-17 실측:
강원 19건·부산경남 4건·경기 1건). 그 표기를 근거로 지사를 빼면 안 된다. 산정액(masterex 청구금액) 대비 입금 진행률."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    AccessContext,
    require_menu,
    resolve_office_scope,
    scoped_employee_name,
)
from app.schemas.common import ApiResponse
from app.services.collection import collection_progress
from app.services.excel_export import XLSX_MEDIA_TYPE, build_xlsx, xlsx_headers

router = APIRouter(prefix="/api/collection-progress", tags=["collection"])


@router.get("", response_model=ApiResponse)
def get_progress(
    date_from: date,
    date_to: date,
    office_code: str = "10",
    doc_id: Annotated[str | None, Query(max_length=50)] = None,
    manager: Annotated[str | None, Query(max_length=30)] = None,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("allocation")),
) -> ApiResponse:
    data = collection_progress(
        db, date_from, date_to,
        resolve_office_scope(access, office_code) or "10",
        doc_id, manager,
        scope_person=scoped_employee_name(access),
    )
    return ApiResponse(success=True, code="0000", message="조회 완료", data=data)


@router.get("/export.xlsx", response_model=None)
def export_progress(
    date_from: date,
    date_to: date,
    office_code: str = "10",
    doc_id: Annotated[str | None, Query(max_length=50)] = None,
    manager: Annotated[str | None, Query(max_length=30)] = None,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("allocation")),
) -> Response:
    """화면과 같은 조건으로 서버가 엑셀 생성 (데스크톱 앱은 Blob 다운로드가 안 됨)."""
    data = collection_progress(
        db, date_from, date_to,
        resolve_office_scope(access, office_code) or "10",
        doc_id, manager,
        scope_person=scoped_employee_name(access),
    )
    columns = [
        ("doc", "감정서번호"), ("cust", "거래처"), ("send_date", "발송일"),
        ("assessed", "산정액"), ("received", "입금액"), ("unpaid", "미입금"),
        ("rate", "진행률(%)"),
    ]
    name = f"배분수금진행_{date_from}_{date_to}"
    return Response(
        content=build_xlsx(name[:31], columns, data["items"]),
        media_type=XLSX_MEDIA_TYPE,
        headers=xlsx_headers(name),
    )
