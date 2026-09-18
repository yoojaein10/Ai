"""데이터 품질 점검 API (본사 관리 화면)."""

from datetime import date

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import AccessContext, require_menu, resolve_office_scope
from app.schemas.common import ApiResponse
from app.services.data_quality import run_checks
from app.services.excel_export import XLSX_MEDIA_TYPE, build_xlsx, xlsx_headers

router = APIRouter(prefix="/api/data-quality", tags=["data-quality"])


@router.get("", response_model=ApiResponse)
def get_checks(
    date_from: date,
    date_to: date,
    office_code: str = "10",
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("dataQuality")),
) -> ApiResponse:
    data = run_checks(db, date_from, date_to, resolve_office_scope(access, office_code))
    return ApiResponse(success=True, code="0000", message="조회 완료", data=data)


@router.get("/export.xlsx", response_model=None)
def export_check(
    date_from: date,
    date_to: date,
    check: str,
    office_code: str = "10",
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("dataQuality")),
) -> Response:
    """점검 항목 하나를 엑셀로 (데스크톱 앱은 Blob 다운로드가 안 되어 서버가 생성)."""
    data = run_checks(db, date_from, date_to, resolve_office_scope(access, office_code))
    found = next((c for c in data["checks"] if c["key"] == check), None)
    if found is None:
        return Response(content="해당 점검 항목이 없습니다.", status_code=404)
    columns = [
        ("doc", "관리번호/감정서번호"), ("amount", "금액"), ("lines", "행수"),
        ("remark", "적요"), ("reason", "문제 원인"),
    ]
    name = f"데이터품질_{found['title']}_{date_from}_{date_to}"
    return Response(
        content=build_xlsx(str(found["title"])[:31], columns, found["items"]),
        media_type=XLSX_MEDIA_TYPE,
        headers=xlsx_headers(name),
    )
