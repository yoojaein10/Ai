"""기간별 매출실적 API (본사 전용 화면에서 사용)."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    AccessContext,
    require_menu,
    resolve_office_scope,
)
from app.schemas.common import ApiResponse
from app.services.excel_export import XLSX_MEDIA_TYPE, build_xlsx, xlsx_headers
from app.services.sales_stats import period_sales_stats, sales_detail

router = APIRouter(prefix="/api/sales-stats", tags=["sales-stats"])

# 입금현황과 같은 규칙: "all"이면 전 사업장 합산, 그 외에는 지사 코드.
OfficeCode = Annotated[str, Query(pattern=r"^[0-9A-Za-z]+$", max_length=10)]


def _office_not_mapped(exc: LookupError) -> JSONResponse:
    response = ApiResponse(
        success=False, code="OFFICE_NOT_MAPPED", message=str(exc), data=None
    )
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content=response.model_dump(mode="json"),
    )

_EXPORT_COLUMNS = [
    ("purpose", "구분"),
    ("docs", "당기 건수"), ("amount", "당기 금액"),
    ("prev_docs", "전기 건수"), ("prev_amount", "전기 금액"),
    ("diff", "증감액"), ("rate", "증감률(%)"), ("achievement", "달성률(%)"),
]

_DETAIL_EXPORT_COLUMNS = [
    ("doc_id", "감정서번호"), ("purpose_detail", "감정목적"), ("work_type", "업무구분"),
    ("customer_name", "거래처"), ("manager", "담당자"), ("investigator", "조사자"),
    ("send_date", "발송일자"), ("base_fee", "순수수료"), ("voucher_amount", "전표매출액"),
    ("billed_amount", "청구액"), ("voucher_date", "전표일자"),
]


@router.get("", response_model=ApiResponse)
def get_sales_stats(
    date_from: date,
    date_to: date,
    prev_from: date | None = None,
    prev_to: date | None = None,
    office_code: OfficeCode = "10",
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("salesStats")),
) -> ApiResponse | JSONResponse:
    try:
        data = period_sales_stats(
            db, date_from, date_to, prev_from, prev_to,
            office_code=resolve_office_scope(access, office_code),
            scope_person=None,  # 기간별 매출실적은 재무·관리자용 → 자기데이터만 보기 제외(2026-08-19 사용자)
        )
    except LookupError as exc:
        return _office_not_mapped(exc)
    return ApiResponse(success=True, code="0000", message="조회 완료", data=data)


@router.get("/detail", response_model=ApiResponse)
def get_sales_detail(
    date_from: date,
    date_to: date,
    office_code: OfficeCode = "10",
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("salesStats")),
) -> ApiResponse | JSONResponse:
    try:
        items = sales_detail(
            db, date_from, date_to,
            office_code=resolve_office_scope(access, office_code),
            scope_person=None,  # 기간별 매출실적은 재무·관리자용 → 자기데이터만 보기 제외(2026-08-19 사용자)
        )
    except LookupError as exc:
        return _office_not_mapped(exc)
    return ApiResponse(
        success=True, code="0000", message="조회 완료",
        data={"items": items, "count": len(items)},
    )


@router.get("/export.xlsx", response_model=None)
def export_sales_stats(
    date_from: date,
    date_to: date,
    prev_from: date | None = None,
    prev_to: date | None = None,
    office_code: OfficeCode = "10",
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("salesStats")),
) -> Response | JSONResponse:
    try:
        data = period_sales_stats(
            db, date_from, date_to, prev_from, prev_to,
            office_code=resolve_office_scope(access, office_code),
            scope_person=None,  # 기간별 매출실적은 재무·관리자용 → 자기데이터만 보기 제외(2026-08-19 사용자)
        )
    except LookupError as exc:
        return _office_not_mapped(exc)
    filename = "기간별매출실적"
    content = build_xlsx(filename, _EXPORT_COLUMNS, data["rows"])
    return Response(
        content=content, media_type=XLSX_MEDIA_TYPE, headers=xlsx_headers(filename)
    )


@router.get("/detail-export.xlsx", response_model=None)
def export_sales_detail(
    date_from: date,
    date_to: date,
    office_code: OfficeCode = "10",
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("salesStats")),
) -> Response | JSONResponse:
    try:
        items = sales_detail(
            db, date_from, date_to,
            office_code=resolve_office_scope(access, office_code),
            scope_person=None,  # 기간별 매출실적은 재무·관리자용 → 자기데이터만 보기 제외(2026-08-19 사용자)
        )
    except LookupError as exc:
        return _office_not_mapped(exc)
    filename = "매출실적상세"
    content = build_xlsx(filename, _DETAIL_EXPORT_COLUMNS, items)
    return Response(
        content=content, media_type=XLSX_MEDIA_TYPE, headers=xlsx_headers(filename)
    )
