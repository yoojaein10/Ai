from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from pydantic import BaseModel, Field

from app.database import get_db
from app.dependencies import (
    AccessContext,
    get_current_access,
    require_menu_access,
    require_operations_user,
    resolve_office_scope,
    scoped_employee_name,
)
from app.schemas.common import ApiResponse
from app.services import expense_close
from app.services.expense_close import ExpenseCloseError
from app.services.excel_export import (
    EXPORT_MAX_ROWS,
    XLSX_MEDIA_TYPE,
    build_xlsx,
    xlsx_headers,
)
from app.services.receivables import ReceivableService

router = APIRouter(prefix="/api/receivables", tags=["receivables"])


def get_service(db: Session = Depends(get_db)) -> ReceivableService:
    return ReceivableService(db)


@router.get("", response_model=ApiResponse)
def list_receivables(
    mode: Literal["received", "outstanding"] = "received",
    office_code: Annotated[str, Query(pattern=r"^[0-9A-Za-z]+$", max_length=10)] = "10",
    doc_id: str | None = None,
    customer_name: str | None = None,
    manager: str | None = None,
    # 상태는 여러 개 고를 수 있다 (pay_status=완납&pay_status=과입금).
    pay_status: Annotated[
        list[Literal["완납", "부분입금", "미입금", "과입금", "선수금"]] | None, Query()
    ] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    # 기간 기준 (2026-09-02): received=입금일(기본) / send=발송일(원장 SendDate)
    date_basis: Literal["received", "send"] = "received",
    bill_from: Annotated[float | None, Query(ge=0)] = None,
    bill_to: Annotated[float | None, Query(ge=0)] = None,
    outstanding_from: Annotated[float | None, Query(ge=0)] = None,
    outstanding_to: Annotated[float | None, Query(ge=0)] = None,
    sort_by: Literal["doc_id", "customer_name", "address", "manager", "receipt_date", "purpose", "eval_purpose", "category", "send_date", "base_fee", "travel_expense", "other_expense", "last_received_date", "billed_amount", "received_amount", "outstanding_amount", "overpaid_amount"] | None = None,
    sort_order: Literal["asc", "desc"] = "asc",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 30,
    service: ReceivableService = Depends(get_service),
    access: AccessContext = Depends(get_current_access),
) -> ApiResponse | JSONResponse:
    require_menu_access(access, "payments" if mode == "received" else "receivables")
    try:
        data = service.list(
            mode=mode,
            office_code=resolve_office_scope(access, office_code),
            doc_id=doc_id, customer_name=customer_name,
            manager=manager, pay_statuses=pay_status,
            date_from=date_from, date_to=date_to,
            date_basis=date_basis,
            bill_from=bill_from, bill_to=bill_to,
            outstanding_from=outstanding_from, outstanding_to=outstanding_to,
            sort_by=sort_by, sort_order=sort_order,
            page=page, page_size=page_size,
            scope_person=scoped_employee_name(access),
        )
    except LookupError as exc:
        response = ApiResponse(
            success=False, code="OFFICE_NOT_MAPPED", message=str(exc), data=None
        )
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=response.model_dump(mode="json"),
        )
    return ApiResponse(success=True, code="0000", message="조회 완료", data=data)


_RECEIVED_EXPORT_COLUMNS = [
    ("doc_id", "감정서번호"), ("status", "입금상태"),
    ("purpose", "업무구분"), ("eval_purpose", "평가목적"),
    ("customer_name", "거래처명"),
    ("address", "소재지"), ("manager", "유치자"), ("charge", "조사자"), ("receipt_date", "접수일"),
    ("send_date", "발송일"), ("last_received_date", "최근 입금일"),
    ("appraisal_amount", "감정가액"), ("base_fee", "순수수료"),
    # 2026-09-11: 화면처럼 '여비및기타실비' 한 칸을 청구서 항목 여섯 칸으로
    ("travel_expense", "여비"), ("survey_fee", "물건조사비"), ("document_fee", "공부발급비"),
    ("land_survey_fee", "토지조사비"), ("other_expense", "기타실비"), ("special_service_fee", "특별용역비"),
    ("sales_amount", "매출액"), ("vat_amount", "부가세"),
    ("invoice_total", "매출총액"),
    # 선수금(기) = 받은 금액, 선수금 = 남은 잔액(전액 상계면 0).
    # 예전처럼 두 칸 다 기간별 순액을 찍으면 상계한 날 음수가 떠
    # '선수금을 두 번 인식한다'로 읽힌다. 받은 금액은 입금액에 이미 포함돼
    # 있으므로 합계를 낼 때 따로 더하면 안 된다.
    ("advance_received", "선수금(기)"),
    ("existing_received_amount", "입금액(기)"),
    ("daily_received_amount", "입금액"),
    ("advance_amount", "선수금"),
    ("outstanding_amount", "미수금"),
    ("progress_status", "진행상태"),
    # 증빙 발행여부 — 화면 목록의 맨 오른쪽 칸과 같은 값
    # ('계산서'/'현금영수증'/'계산서+현금영수증' 또는 빈칸).
    ("proof_issued", "세금계산서/현금영수증"),
]

_OUTSTANDING_EXPORT_COLUMNS = [
    ("doc_id", "감정서번호"), ("purpose", "업무구분"), ("eval_purpose", "평가목적"),
    ("customer_name", "거래처명"),
    ("address", "소재지"), ("manager", "유치자"), ("charge", "조사자"), ("receipt_date", "접수일"),
    ("send_date", "발송일"), ("last_received_date", "최근 입금일"),
    ("appraisal_amount", "감정가액"), ("base_fee", "순수수료"), ("travel_expense", "여비"), ("other_expense", "기타실비"),
    ("billed_amount", "청구액"), ("received_amount", "입금액"),
    ("outstanding_amount", "미수금"), ("overpaid_amount", "과입금"), ("status", "상태"),
    # 증빙 발행여부 — 선발행 미수(발행됐는데 미입금)를 엑셀에서도 거르게 한다.
    ("proof_issued", "세금계산서/현금영수증"),
]


def _status_label(item: "dict[str, Any]") -> str:
    """화면 상태 배지와 같은 판정 (receivables.js와 동일한 우선순위)."""
    billed = float(item.get("billed_amount") or 0)
    received = float(item.get("received_amount") or 0)
    outstanding = float(item.get("outstanding_amount") or 0)
    overpaid = float(item.get("overpaid_amount") or 0)
    advance = float(item.get("advance_amount") or 0)
    # 입금현황은 매출총액(원장 [매출총액]) 기준으로 미수를 내므로 그 값을 쓴다.
    # 청구금액은 담당자가 선수금을 뺀 값으로 적는 관행이 있어 기준으로 쓸 수 없다.
    assessed = float(item.get("invoice_total") or item.get("assessed_billed") or 0)
    received = received + float(item.get("settled_advance") or 0)
    if advance > 0 and billed == 0:
        return "선수금"
    if overpaid > 0:
        return "과입금"
    if outstanding <= 0 and billed > 0:
        return "부분입금" if assessed - received > 1000 else "완납"
    if received > 0:
        return "부분입금"
    return "미입금"


@router.get("/export.xlsx", response_model=None)
def export_receivables(
    mode: Literal["received", "outstanding"] = "received",
    office_code: Annotated[str, Query(pattern=r"^[0-9A-Za-z]+$", max_length=10)] = "10",
    doc_id: str | None = None,
    customer_name: str | None = None,
    manager: str | None = None,
    # 상태는 여러 개 고를 수 있다 (pay_status=완납&pay_status=과입금).
    pay_status: Annotated[
        list[Literal["완납", "부분입금", "미입금", "과입금", "선수금"]] | None, Query()
    ] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    # 기간 기준 (2026-09-02): received=입금일(기본) / send=발송일(원장 SendDate)
    date_basis: Literal["received", "send"] = "received",
    bill_from: Annotated[float | None, Query(ge=0)] = None,
    bill_to: Annotated[float | None, Query(ge=0)] = None,
    outstanding_from: Annotated[float | None, Query(ge=0)] = None,
    outstanding_to: Annotated[float | None, Query(ge=0)] = None,
    sort_by: Literal["doc_id", "customer_name", "address", "manager", "receipt_date", "purpose", "eval_purpose", "category", "send_date", "base_fee", "travel_expense", "other_expense", "last_received_date", "billed_amount", "received_amount", "outstanding_amount", "overpaid_amount"] | None = None,
    sort_order: Literal["asc", "desc"] = "asc",
    service: ReceivableService = Depends(get_service),
    access: AccessContext = Depends(get_current_access),
) -> Response | JSONResponse:
    require_menu_access(access, "payments" if mode == "received" else "receivables")
    try:
        data = service.list(
            mode=mode,
            office_code=resolve_office_scope(access, office_code),
            doc_id=doc_id, customer_name=customer_name,
            manager=manager, pay_statuses=pay_status,
            date_from=date_from, date_to=date_to,
            date_basis=date_basis,
            bill_from=bill_from, bill_to=bill_to,
            outstanding_from=outstanding_from, outstanding_to=outstanding_to,
            sort_by=sort_by, sort_order=sort_order,
            page=1, page_size=EXPORT_MAX_ROWS,
            force_meta_join=True,
            scope_person=scoped_employee_name(access),
        )
    except LookupError as exc:
        response = ApiResponse(
            success=False, code="OFFICE_NOT_MAPPED", message=str(exc), data=None
        )
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=response.model_dump(mode="json"),
        )
    items = data["items"]
    for item in items:
        item["status"] = _status_label(item)
    # 입금현황은 조회한 기간 기준(입금일/발송일)을 시트명·파일명에 넣는다 (2026-09-03)
    # — 발송일 기준으로 뽑은 파일이 나중에 무슨 기준인지 헷갈리지 않게.
    if mode == "received":
        basis = "발송일 기준" if date_basis == "send" else "입금일 기준"
        filename = f"입금현황({basis})"
    else:
        filename = "미수금현황"
    columns = (
        _RECEIVED_EXPORT_COLUMNS if mode == "received" else _OUTSTANDING_EXPORT_COLUMNS
    )
    content = build_xlsx(filename, columns, items)
    return Response(
        content=content, media_type=XLSX_MEDIA_TYPE, headers=xlsx_headers(filename)
    )


class ExpenseCloseRequest(BaseModel):
    doc_id: str = Field(min_length=1, max_length=50)


@router.post("/expense-close", response_model=ApiResponse)
def mark_expense_close(
    request: ExpenseCloseRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(get_current_access),
) -> ApiResponse | JSONResponse:
    """입금현황 우클릭 '실비 처리' — 지금 수금액을 최종 매출로 확정하고 완납 종결."""
    require_menu_access(access, "payments")
    require_operations_user(
        access, "실비 처리는 본사 재무·집행부·전산정보팀만 할 수 있습니다."
    )
    try:
        data = expense_close.mark(db, request.doc_id, int(access["usr_seq"]))
    except ExpenseCloseError as exc:
        response = ApiResponse(
            success=False, code="EXPENSE_CLOSE_FAILED", message=str(exc), data=None
        )
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=response.model_dump(mode="json"),
        )
    return ApiResponse(success=True, code="0000", message="실비 처리 완료", data=data)


@router.post("/expense-close/release", response_model=ApiResponse)
def release_expense_close(
    request: ExpenseCloseRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(get_current_access),
) -> ApiResponse | JSONResponse:
    """실비 처리 해제 — 판정을 원래대로 되돌린다 (이력은 남는다)."""
    require_menu_access(access, "payments")
    require_operations_user(
        access, "실비 처리는 본사 재무·집행부·전산정보팀만 할 수 있습니다."
    )
    try:
        data = expense_close.release(db, request.doc_id, int(access["usr_seq"]))
    except ExpenseCloseError as exc:
        response = ApiResponse(
            success=False, code="EXPENSE_CLOSE_FAILED", message=str(exc), data=None
        )
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=response.model_dump(mode="json"),
        )
    return ApiResponse(
        success=True, code="0000", message="실비 처리를 해제했습니다.", data=data
    )
