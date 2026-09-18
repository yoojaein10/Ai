"""외부 발행 계산서 수기 등록 API (2026-09-09) — 계산서 일괄발급 화면의 '외부 발행 등록' 탭이 쓴다.

권한은 일괄발급과 같다(taxBulk 메뉴 + 본사 운영부서). 등록은 발급 원장에 쓰는 일이라
쓰기 관문 + 본인 요청 확인까지 건다.
"""

import os
from datetime import date

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import JSONResponse, Response
from typing import Literal
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

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
from app.services import external_issue, issued_ledger
from app.services.excel_export import XLSX_MEDIA_TYPE, build_xlsx, xlsx_headers
from app.services.office_lookup import docid_prefixes

router = APIRouter(prefix="/api/taxinvoice/external", tags=["taxinvoice"])
_MESSAGE = "외부 발행 등록은 본사 재무팀·집행부만 쓸 수 있습니다."
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


class ExternalRow(BaseModel):
    doc_id: str = Field(default="", max_length=50)
    source: str = Field(default="", max_length=20)
    doc_type: str = Field(default="", max_length=10)
    write_date: str = Field(default="", max_length=20)
    nts_confirm: str = Field(default="", max_length=40)
    receiver_corp_num: str = Field(default="", max_length=20)
    receiver_name: str = Field(default="", max_length=200)
    supply_cost: int = 0
    tax: int = 0
    nts: dict[str, str] | None = None   # 국세청 자료 원래 칸 값 — 목록 표시용 (2026-09-11)


class ExternalRowsRequest(BaseModel):
    requester_usr_seq: int
    rows: list[ExternalRow] = Field(min_length=1, max_length=external_issue.MAX_ROWS)


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    body = ApiResponse(success=False, code=code, message=message, data=None)
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


@router.post("/validate", response_model=ApiResponse)
def validate(
    request: ExternalRowsRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("taxBulk")),
) -> ApiResponse | JSONResponse:
    """행마다 막히는 문제·참고 경고를 붙여 돌려준다 (저장 없음)."""
    require_operations_user(access, _MESSAGE)
    try:
        rows = external_issue.validate_rows(db, [r.model_dump() for r in request.rows])
    except external_issue.ExternalIssueError as exc:
        return _error(status.HTTP_400_BAD_REQUEST, "BAD_REQUEST", str(exc))
    return ApiResponse(success=True, code="0000", message="검증 완료", data={"rows": rows})


@router.post("/parse-excel", response_model=ApiResponse)
async def parse_excel(
    file: UploadFile = File(...),
    requester_usr_seq: int = Form(...),
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("taxBulk")),
) -> ApiResponse | JSONResponse:
    """우리 양식(.xlsx) 또는 국세청 매출 자료(.xls·.xlsx)를 읽어 검증까지 붙여 돌려준다 (저장 없음)."""
    require_operations_user(access, _MESSAGE)
    require_same_requester(access, requester_usr_seq)
    name = os.path.basename(file.filename or "external.xlsx")
    if not name.lower().endswith((".xlsx", ".xls")):
        return _error(status.HTTP_400_BAD_REQUEST, "BAD_FILE", "엑셀 파일(.xlsx·.xls)만 올릴 수 있습니다.")
    data = await file.read()
    if not data:
        return _error(status.HTTP_400_BAD_REQUEST, "BAD_FILE", "빈 파일입니다.")
    if len(data) > MAX_UPLOAD_BYTES:
        return _error(status.HTTP_400_BAD_REQUEST, "FILE_TOO_LARGE", "5MB 이하만 올릴 수 있습니다.")
    try:
        raw_rows = external_issue.parse_upload(db, data, name)
        rows = external_issue.validate_rows(db, raw_rows) if raw_rows else []
    except external_issue.ExternalIssueError as exc:
        return _error(status.HTTP_400_BAD_REQUEST, "BAD_REQUEST", str(exc))
    except Exception as exc:  # 손상된 엑셀·확장자 불일치 등
        return _error(status.HTTP_400_BAD_REQUEST, "BAD_FILE", f"엑셀을 읽지 못했습니다: {type(exc).__name__}")
    return ApiResponse(success=True, code="0000", message=f"{len(rows)}행", data={"rows": rows, "filename": name})


@router.post("/register", response_model=ApiResponse)
def register(
    request: ExternalRowsRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu_write("taxBulk")),
) -> ApiResponse | JSONResponse:
    """검증을 통과한 행만 발급 원장에 넣는다. 행마다 결과가 돌아온다."""
    require_same_requester(access, request.requester_usr_seq)
    require_operations_user(access, _MESSAGE)
    try:
        data = external_issue.register_rows(db, [r.model_dump() for r in request.rows])
    except external_issue.ExternalIssueError as exc:
        return _error(status.HTTP_400_BAD_REQUEST, "BAD_REQUEST", str(exc))
    message = f"등록 {data['registered']}건" + (f" · 건너뜀 {data['skipped']}건" if data["skipped"] else "")
    return ApiResponse(success=True, code="0000", message=message, data=data)


@router.get("/template.xlsx", include_in_schema=False)
def template(access: AccessContext = Depends(require_menu("taxBulk"))) -> Response:
    """등록용 엑셀 양식 (머리글 + 보기 행 + 안내 시트)."""
    require_operations_user(access, _MESSAGE)
    return Response(
        content=external_issue.template_xlsx(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="external_issue_template.xlsx"'},
    )


def _ledger_query(
    db: Session, access: AccessContext, *, office_code: "str | None", date_from: "date | None", date_to: "date | None",
    doc_type: str, source: str, keyword: str, missing_doc: bool, sort_by: str, sort_order: str,
) -> "tuple[str, dict, str]":
    """목록·엑셀 공용 조건 — 지사 범위는 로그인 사용자 권한으로 강제한다."""
    scope = resolve_office_scope(access, office_code)
    prefixes = docid_prefixes(db, scope) if scope else None
    where, params = issued_ledger.build_where(
        prefixes=prefixes, include_kb=scope == "10", date_from=date_from, date_to=date_to,
        doc_type=doc_type, source=source, keyword=keyword, missing_doc=missing_doc,
    )
    return where, params, issued_ledger.order_sql(sort_by, sort_order)


@router.get("/ledger", response_model=ApiResponse)
def ledger(
    office_code: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    doc_type: str = "",
    source: str = "",
    keyword: str = Query(default="", max_length=100),
    missing_doc: bool = False,
    sort_by: str = "",
    sort_order: Literal["asc", "desc"] = "desc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=issued_ledger.MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("taxBulk")),
) -> ApiResponse | JSONResponse:
    """계산서 등록 화면 목록 — 발급 원장을 조건으로 거른 한 쪽 + 조건 전체 합계 (2026-09-11)."""
    require_operations_user(access, _MESSAGE)
    try:
        where, params, order = _ledger_query(
            db, access, office_code=office_code, date_from=date_from, date_to=date_to, doc_type=doc_type,
            source=source, keyword=keyword, missing_doc=missing_doc, sort_by=sort_by, sort_order=sort_order,
        )
        data = issued_ledger.list_ledger(db, where, params, page, page_size, order)
    except (issued_ledger.LedgerQueryError, LookupError) as exc:
        return _error(status.HTTP_400_BAD_REQUEST, "BAD_REQUEST", str(exc))
    return ApiResponse(success=True, code="0000", message=f"{data['total']}건", data=data)


@router.get("/ledger/export.xlsx", include_in_schema=False, response_model=None)
def ledger_export(
    office_code: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    doc_type: str = "",
    source: str = "",
    keyword: str = Query(default="", max_length=100),
    missing_doc: bool = False,
    sort_by: str = "",
    sort_order: Literal["asc", "desc"] = "desc",
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("taxBulk")),
) -> Response | JSONResponse:
    """엑셀 추출 — 화면 조건·정렬 그대로 전체 (재무팀 요청 2026-09-11)."""
    require_operations_user(access, _MESSAGE)
    try:
        where, params, order = _ledger_query(
            db, access, office_code=office_code, date_from=date_from, date_to=date_to, doc_type=doc_type,
            source=source, keyword=keyword, missing_doc=missing_doc, sort_by=sort_by, sort_order=sort_order,
        )
        rows = issued_ledger.export_rows(db, where, params, order)
    except (issued_ledger.LedgerQueryError, LookupError) as exc:
        return _error(status.HTTP_400_BAD_REQUEST, "BAD_REQUEST", str(exc))
    content = build_xlsx("발급 원장", issued_ledger.EXPORT_COLUMNS, rows)
    return Response(content=content, media_type=XLSX_MEDIA_TYPE, headers=xlsx_headers("발급원장"))


class LedgerDocRequest(BaseModel):
    requester_usr_seq: int
    doc_id: str = Field(min_length=1, max_length=50)


@router.post("/ledger/{row_id}/doc", response_model=ApiResponse)
def ledger_doc(
    row_id: int,
    request: LedgerDocRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu_write("taxBulk")),
) -> ApiResponse | JSONResponse:
    """감정서번호 고치기 — 엑셀로 등록한 건만 (재무팀 요청 2026-09-11: 세금계산서도 번호 수정)."""
    require_same_requester(access, request.requester_usr_seq)
    require_operations_user(access, _MESSAGE)
    try:
        data = issued_ledger.update_doc(db, row_id, request.doc_id)
    except issued_ledger.LedgerQueryError as exc:
        return _error(status.HTTP_400_BAD_REQUEST, "BAD_REQUEST", str(exc))
    return ApiResponse(success=True, code="0000", message="감정서번호를 고쳤습니다.", data=data)
