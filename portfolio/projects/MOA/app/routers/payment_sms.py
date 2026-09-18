"""입금문자내역 API — 입금완료 건 조회와 문자 전송 기록. 전송 처리/취소는 본사만."""

from collections import Counter
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    AccessContext,
    get_current_access,
    require_menu_access,
    resolve_office_scope,
)
from app.schemas.common import ApiResponse
from app.services.excel_export import XLSX_MEDIA_TYPE, build_xlsx, xlsx_headers
from app.services.payment_sms import (
    NO_BILL_TEXT,
    PaymentSmsError,
    list_queue,
    mark_sent,
    send_alimtalk,
)
from app.services.users import UserContextError, UserContextService

router = APIRouter(prefix="/api/payment-sms", tags=["payment-sms"])


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    response = ApiResponse(success=False, code=code, message=message, data=None)
    return JSONResponse(status_code=status_code, content=response.model_dump(mode="json"))


def _check_hq(db: Session, usr_seq: int) -> JSONResponse | None:
    try:
        context = UserContextService(db)._resolve(str(usr_seq))
    except UserContextError as exc:
        return _error(status.HTTP_403_FORBIDDEN, exc.code, str(exc))
    if context["office_id"] != "10":
        return _error(
            status.HTTP_403_FORBIDDEN, "NOT_HEAD_OFFICE", "전송 처리는 본사만 가능합니다."
        )
    return None


class MarkRequest(BaseModel):
    requester_usr_seq: int
    doc_ids: list[Annotated[str, StringConstraints(min_length=1, max_length=50)]] = Field(
        min_length=1, max_length=200
    )
    sent: bool


class SendRequest(BaseModel):
    requester_usr_seq: int
    doc_ids: list[Annotated[str, StringConstraints(min_length=1, max_length=50)]] = Field(
        min_length=1, max_length=100
    )


@router.get("", response_model=ApiResponse)
def list_payment_sms(
    date_from: date,
    date_to: date,
    office_code: Annotated[str, Query(pattern=r"^[0-9A-Za-z]+$", max_length=10)] = "10",
    sent: Literal["all", "sent", "unsent"] = "all",
    pay_status: Literal["all", "full", "partial"] = "all",
    query: Annotated[str | None, Query(max_length=100)] = None,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(get_current_access),
) -> ApiResponse | JSONResponse:
    # 조회 범위는 로그인 사용자로 강제한다 — 지사는 자기 지사만. 예전에는 검사가 없어
    # office_code=all 로 전 지사 입금내역이 그대로 나왔다.
    require_menu_access(access, "paymentSms")
    try:
        data = list_queue(
            db,
            date_from=date_from, date_to=date_to,
            office_code=resolve_office_scope(access, office_code),
            sent=sent, query=query, pay_status=pay_status,
        )
    except LookupError as exc:
        return _error(status.HTTP_404_NOT_FOUND, "OFFICE_NOT_MAPPED", str(exc))
    return ApiResponse(success=True, code="0000", message="조회 완료", data=data)


@router.post("/mark", response_model=ApiResponse)
def post_mark(request: MarkRequest, db: Session = Depends(get_db)) -> ApiResponse | JSONResponse:
    denied = _check_hq(db, request.requester_usr_seq)
    if denied:
        return denied
    try:
        count = mark_sent(
            db, doc_ids=request.doc_ids, sent=request.sent,
            usr_seq=request.requester_usr_seq,
        )
    except PaymentSmsError as exc:
        return _error(status.HTTP_400_BAD_REQUEST, "MARK_FAILED", str(exc))
    label = "전송 처리" if request.sent else "미전송 처리"
    skipped = len(request.doc_ids) - count
    note = f" (이미 전송됐거나 대상이 아닌 {skipped}건 제외)" if skipped > 0 else ""
    return ApiResponse(
        success=True, code="0000",
        message=f"{count}건을 {label}했습니다.{note}", data={"count": count},
    )


@router.post("/send", response_model=ApiResponse)
def post_send(request: SendRequest, db: Session = Depends(get_db)) -> ApiResponse | JSONResponse:
    """선택 건 알림톡 발송 (본사 전용) — 미전송 건만 큐잉되고 전송 기록이 남는다."""
    denied = _check_hq(db, request.requester_usr_seq)
    if denied:
        return denied
    try:
        result = send_alimtalk(
            db, doc_ids=request.doc_ids, usr_seq=request.requester_usr_seq
        )
    except PaymentSmsError as exc:
        return _error(status.HTTP_400_BAD_REQUEST, "SEND_FAILED", str(exc))
    parts = [f"{result['docs_sent']}건 발송 큐잉(메시지 {result['messages_queued']}건)"]
    if result["test_mode"]:
        parts.append("테스트 번호로 발송")
    if result["skipped"]:
        # 사유를 뭉뚱그리면 '전화번호 없음'과 '이미 발송됨'이 구별되지 않는다.
        by_reason = Counter(item["reason"] for item in result["skipped"])
        parts.append(
            "제외 " + ", ".join(f"{reason} {count}건"
                               for reason, count in by_reason.most_common())
        )
    requested = len(request.doc_ids)
    already = requested - result["docs_sent"] - len(result["skipped"])
    if already > 0:
        parts.append(f"이미 전송됐거나 대상 아님 {already}건")
    return ApiResponse(
        success=True, code="0000", message=" · ".join(parts), data=result,
    )


_COLUMNS = [
    ("doc_id", "감정서번호"), ("customer_name", "거래처"), ("manager", "담당자"),
    ("recipients", "문자수신"), ("detected_at", "감지시각"), ("paid_date", "입금일"),
    ("total_amount", "매출총액"), ("bill_amount", "청구금액"),
    ("delta_amount", "입금액(증가분)"), ("received_amount", "누적입금"),
    ("status", "입금상태"), ("queue_label", "처리"), ("queue_result", "처리결과"),
    ("queue_at", "처리시각"),
]


@router.get("/export.xlsx", response_model=None)
def export_payment_sms(
    date_from: date,
    date_to: date,
    office_code: Annotated[str, Query(pattern=r"^[0-9A-Za-z]+$", max_length=10)] = "10",
    sent: Literal["all", "sent", "unsent"] = "all",
    pay_status: Literal["all", "full", "partial"] = "all",
    query: Annotated[str | None, Query(max_length=100)] = None,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(get_current_access),
) -> Response | JSONResponse:
    # 엑셀도 화면과 같은 범위로 막는다 — 여기만 열려 있으면 우회 통로가 된다.
    require_menu_access(access, "paymentSms")
    try:
        data = list_queue(
            db,
            date_from=date_from, date_to=date_to,
            office_code=resolve_office_scope(access, office_code),
            sent=sent, query=query, pay_status=pay_status,
            max_rows=100_000,  # 엑셀은 화면 한도(1000건)와 달리 전체를 내보낸다
        )
    except LookupError as exc:
        return _error(status.HTTP_404_NOT_FOUND, "OFFICE_NOT_MAPPED", str(exc))
    # 매출총액이 비면 0원이 아니라 청구서 미작성이다 — 화면과 같은 글자를 쓴다.
    rows = [
        {**item,
         "queue_label": "처리" if item["queue_done"] else "미처리",
         "total_amount": (
             NO_BILL_TEXT if item["total_amount"] is None else item["total_amount"]
         ),
         "bill_amount": (
             NO_BILL_TEXT if item["bill_amount"] is None else item["bill_amount"]
         )}
        for item in data["items"]
    ]
    filename = f"입금발송내역_{date_from.isoformat()}_{date_to.isoformat()}"
    content = build_xlsx(filename, _COLUMNS, rows)
    return Response(
        content=content, media_type=XLSX_MEDIA_TYPE, headers=xlsx_headers(filename)
    )
