from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    AccessContext,
    require_menu,
    require_operations_user,
    require_same_requester,
    resolve_office_scope,
    scoped_employee_name,
)
from app.schemas.common import ApiResponse
from app.services.excel_export import XLSX_MEDIA_TYPE, build_xlsx, xlsx_headers
from app.services.gaprice_outbox import (
    GapriceApprovalError,
    approve,
    cancel_approval,
    list_outbox,
    reject,
    search_employees,
)
from app.services.users import UserContextError, UserContextService

router = APIRouter(prefix="/api/gaprice", tags=["gaprice"])


class OutboxRowAmount(BaseModel):
    id: int
    in_price: float = Field(ge=0)
    basic_susu: float = Field(ge=0)
    ratio: float | None = Field(default=None, ge=0, le=999.99)


class NewOutboxRow(BaseModel):
    """화면에서 추가한 담당자 (초안에 없던 사람)."""

    manager: str = Field(min_length=1, max_length=30)
    usr_seq: int | None = None
    ratio: float = Field(default=0, ge=0, le=999.99)
    in_price: float = Field(ge=0)
    basic_susu: float = Field(ge=0)


class ApproveRequest(BaseModel):
    approver_usr_seq: int
    rows: list[OutboxRowAmount] = []
    new_rows: list[NewOutboxRow] = Field(default=[], max_length=20)


class DocApprove(BaseModel):
    doc_id: str
    rows: list[OutboxRowAmount] = []
    new_rows: list[NewOutboxRow] = Field(default=[], max_length=20)


class BulkApproveRequest(BaseModel):
    approver_usr_seq: int
    docs: list[DocApprove] = Field(min_length=1, max_length=200)


class RejectRequest(BaseModel):
    approver_usr_seq: int


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    response = ApiResponse(success=False, code=code, message=message, data=None)
    return JSONResponse(status_code=status_code, content=response.model_dump(mode="json"))


def _check_approver(db: Session, usr_seq: int) -> JSONResponse | None:
    """승인은 본사 소속 재직자만 가능하다 (재무팀은 본사)."""
    try:
        context = UserContextService(db)._resolve(str(usr_seq))
    except UserContextError as exc:
        return _error(status.HTTP_403_FORBIDDEN, exc.code, str(exc))
    if context["office_id"] != "10":
        return _error(
            status.HTTP_403_FORBIDDEN, "NOT_HEAD_OFFICE", "배분 승인은 본사만 가능합니다."
        )
    return None


@router.get("/outbox", response_model=ApiResponse)
def get_outbox(
    outbox_status: Annotated[
        Literal["PENDING", "APPROVED", "REJECTED"], Query(alias="status")
    ] = "PENDING",
    date_from: date | None = None,
    date_to: date | None = None,
    doc_id: Annotated[str | None, Query(max_length=50)] = None,
    manager: Annotated[str | None, Query(max_length=30)] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("salesInput")),
) -> ApiResponse:
    items = list_outbox(
        db, status=outbox_status, date_from=date_from, date_to=date_to,
        doc_id=doc_id, manager=manager,
        office_code=resolve_office_scope(access, None),
        scope_person=scoped_employee_name(access),
    )
    return ApiResponse(
        success=True, code="0000", message="조회 완료",
        data={"items": items[:limit], "count": len(items)},
    )


_EXPORT_COLUMNS = [
    ("doc_id", "감정서번호"), ("manager", "유치자"), ("customer_name", "거래처명"),
    ("in_date", "입금일"), ("base_fee", "순수수료"), ("paid_amount", "실입금액"),
    ("ratio", "비율(%)"), ("in_price", "배분액"), ("basic_susu", "실적인정금액"),
]

_APPROVED_EXPORT_COLUMNS = _EXPORT_COLUMNS + [
    ("approved_at", "승인일시"), ("approved_by_name", "승인자"),
    ("applied_ga_seq", "GaPrice Seq"),
]

_EXPORT_FILENAMES = {"PENDING": "매출입력대기", "APPROVED": "매출입력승인", "REJECTED": "매출입력보류"}


@router.get("/outbox/export.xlsx", response_model=None)
def export_outbox(
    outbox_status: Annotated[
        Literal["PENDING", "APPROVED", "REJECTED"], Query(alias="status")
    ] = "PENDING",
    date_from: date | None = None,
    date_to: date | None = None,
    doc_id: Annotated[str | None, Query(max_length=50)] = None,
    manager: Annotated[str | None, Query(max_length=30)] = None,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("salesInput")),
) -> Response:
    """현재 검색 조건 그대로 담당자별 한 행으로 내보낸다 (표시 제한 없이 전체)."""
    docs = list_outbox(
        db, status=outbox_status, date_from=date_from, date_to=date_to,
        doc_id=doc_id, manager=manager,
        office_code=resolve_office_scope(access, None),
        scope_person=scoped_employee_name(access),
    )
    items = [
        {
            "doc_id": doc["doc_id"],
            "customer_name": doc["customer_name"],
            "in_date": doc["in_date"],
            "base_fee": doc["base_fee"],
            "paid_amount": doc["paid_amount"],
            "approved_at": doc.get("approved_at"),
            "approved_by_name": doc.get("approved_by_name"),
            **row,
        }
        for doc in docs
        for row in doc["rows"]
    ]
    filename = _EXPORT_FILENAMES[outbox_status]
    columns = _APPROVED_EXPORT_COLUMNS if outbox_status == "APPROVED" else _EXPORT_COLUMNS
    content = build_xlsx(filename, columns, items)
    return Response(
        content=content, media_type=XLSX_MEDIA_TYPE, headers=xlsx_headers(filename)
    )


@router.get("/employees", response_model=ApiResponse)
def get_employees(
    q: Annotated[str, Query(min_length=1, max_length=30)],
    db: Session = Depends(get_db),
    _access: AccessContext = Depends(require_menu("salesInput")),
) -> ApiResponse:
    """담당자 추가용 재직자 이름 검색 (매출 입력 화면 자동완성)."""
    items = search_employees(db, q)
    return ApiResponse(
        success=True, code="0000", message="조회 완료",
        data={"items": items, "count": len(items)},
    )


@router.post("/outbox/{doc_id}/approve", response_model=ApiResponse)
def approve_outbox(
    doc_id: str,
    request: ApproveRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("salesInput")),
) -> ApiResponse | JSONResponse:
    require_same_requester(access, request.approver_usr_seq)
    require_operations_user(access, "배분 승인은 본사 재무팀·집행부만 가능합니다.")
    amounts: dict[int, dict[str, Any]] = {
        row.id: {"in_price": row.in_price, "basic_susu": row.basic_susu, "ratio": row.ratio}
        for row in request.rows
    }
    try:
        seqs = approve(
            db, doc_id, amounts, request.approver_usr_seq,
            new_rows=[row.model_dump() for row in request.new_rows],
        )
    except GapriceApprovalError as exc:
        return _error(status.HTTP_400_BAD_REQUEST, "APPROVAL_FAILED", str(exc))
    return ApiResponse(
        success=True, code="0000",
        message=f"배분 {len(seqs)}건이 반영되었습니다.", data={"ga_seqs": seqs},
    )


@router.post("/outbox/approve-bulk", response_model=ApiResponse)
def approve_outbox_bulk(
    request: BulkApproveRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("salesInput")),
) -> ApiResponse | JSONResponse:
    require_same_requester(access, request.approver_usr_seq)
    require_operations_user(access, "배분 승인은 본사 재무팀·집행부만 가능합니다.")
    approved, failed = [], []
    for doc in request.docs:
        amounts: dict[int, dict[str, Any]] = {
            row.id: {"in_price": row.in_price, "basic_susu": row.basic_susu, "ratio": row.ratio}
            for row in doc.rows
        }
        try:
            approve(
                db, doc.doc_id, amounts, request.approver_usr_seq,
                new_rows=[row.model_dump() for row in doc.new_rows],
            )
            approved.append(doc.doc_id)
        except GapriceApprovalError as exc:
            db.rollback()
            failed.append({"doc_id": doc.doc_id, "message": str(exc)})
    message = f"{len(approved)}건 승인 완료"
    if failed:
        message += f", {len(failed)}건 실패"
    return ApiResponse(
        success=True, code="0000", message=message,
        data={"approved": approved, "failed": failed},
    )


@router.post("/outbox/{doc_id}/reject", response_model=ApiResponse)
def reject_outbox(
    doc_id: str,
    request: RejectRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("salesInput")),
) -> ApiResponse | JSONResponse:
    require_same_requester(access, request.approver_usr_seq)
    require_operations_user(access, "배분 승인은 본사 재무팀·집행부만 가능합니다.")
    try:
        count = reject(db, doc_id, request.approver_usr_seq)
    except GapriceApprovalError as exc:
        return _error(status.HTTP_400_BAD_REQUEST, "APPROVAL_FAILED", str(exc))
    return ApiResponse(
        success=True, code="0000", message=f"{count}건을 보류했습니다.", data=None
    )


@router.post("/outbox/{doc_id}/cancel", response_model=ApiResponse)
def cancel_outbox(
    doc_id: str,
    request: RejectRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("salesInput")),
) -> ApiResponse | JSONResponse:
    """승인 취소 — 원장(Apw_Mae_GaPrice)에서 지우고 초안을 승인 대기로 되돌린다.

    권한은 승인과 같다 (2026-08-21 사용자 결정: 본사 재무팀·집행부만).
    """
    require_same_requester(access, request.approver_usr_seq)
    require_operations_user(access, "배분 승인 취소는 본사 재무팀·집행부만 가능합니다.")
    try:
        result = cancel_approval(db, doc_id, request.approver_usr_seq)
    except GapriceApprovalError as exc:
        return _error(status.HTTP_400_BAD_REQUEST, "CANCEL_FAILED", str(exc))
    # 원장에서 지운 수가 되돌린 수보다 적으면 이미 손으로 지워진 행이 있던 것이다.
    note = ""
    if result["deleted"] < result["rows"]:
        note = f" (원장에 이미 없던 {result['rows'] - result['deleted']}행 포함)"
    return ApiResponse(
        success=True, code="0000",
        message=f"{result['rows']}건의 승인을 취소했습니다.{note}", data=result,
    )
