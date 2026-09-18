from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    AccessContext,
    assert_document_access,
    require_menu,
    require_operations_user,
    resolve_office_scope,
    scoped_employee_name,
)
from app.schemas.common import ApiResponse
from app.services.appraisals import AppraisalNotFoundError, AppraisalService
from app.services.excel_export import (
    EXPORT_MAX_ROWS,
    XLSX_MEDIA_TYPE,
    build_xlsx,
    xlsx_headers,
)
from app.services.default_vouchers import (
    DefaultVoucherDuplicateError,
    DefaultVoucherError,
    DefaultVoucherService,
)

router = APIRouter(prefix="/api/appraisals", tags=["appraisals"])


class DefaultVoucherCreateRequest(BaseModel):
    partner_code: str = Field(min_length=1, max_length=10)
    partner_name: str = Field(default="", max_length=100)
    voucher_date: date
    requester_usr_seq: int | None = None
    # 청구액보다 적게 받고 끝난 건 — 실제 증빙 금액으로 전표를 세운다 (2026-09-07).
    use_evidence_amount: bool = False


def get_appraisal_service(db: Session = Depends(get_db)) -> AppraisalService:
    return AppraisalService(db)


def get_default_voucher_service(db: Session = Depends(get_db)) -> DefaultVoucherService:
    return DefaultVoucherService(db)


@router.get("", response_model=ApiResponse)
def list_appraisals(
    doc_id: str | None = None,
    cust_doc_id: str | None = None,
    address: str | None = None,
    customer_name: str | None = None,
    manager: str | None = None,
    charge: str | None = None,
    office_code: Annotated[str, Query(pattern=r"^[0-9A-Za-z]+$", max_length=10)] = "10",
    sort_by: Literal["doc_id", "cust_doc_id", "receipt_date", "address", "customer_name", "manager", "author", "purpose", "eval_purpose", "progress_status", "send_date", "appraisal_amount", "base_fee", "appraisal_cost", "sales_amount", "vat_amount", "gross_total", "owner_name", "debtor", "travel_expense", "special_service_fee", "title"] | None = None,
    sort_order: Literal["asc", "desc"] = "asc",
    progress_status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    bill_from: Annotated[float | None, Query(ge=0)] = None,
    bill_to: Annotated[float | None, Query(ge=0)] = None,
    price_from: Annotated[float | None, Query(ge=0)] = None,
    price_to: Annotated[float | None, Query(ge=0)] = None,
    purpose: str | None = None,
    keyword: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 30,
    service: AppraisalService = Depends(get_appraisal_service),
    access: AccessContext = Depends(require_menu("appraisals")),
) -> ApiResponse:
    today = date.today()
    effective_date_from = date_from or (today - timedelta(days=6))
    effective_date_to = date_to or today
    data = service.list(
        doc_id=doc_id,
        cust_doc_id=cust_doc_id,
        address=address,
        customer_name=customer_name,
        manager=manager,
        charge=charge,
        office_code=resolve_office_scope(access, office_code),
        sort_by=sort_by,
        sort_order=sort_order,
        status=progress_status,
        date_from=effective_date_from,
        date_to=effective_date_to,
        bill_from=bill_from,
        bill_to=bill_to,
        price_from=price_from,
        price_to=price_to,
        purpose=purpose,
        keyword=keyword,
        scope_person=scoped_employee_name(access),
        page=page,
        page_size=page_size,
    )
    return ApiResponse(success=True, code="0000", message="조회 완료", data=data)


# 엑셀 열 순서 — 재무팀 지정 (2026-09-11): 감정서번호·업무구분·거래처명·유치자·조사자·순수수료·감정가액·
# 여비 여섯 칸(화면처럼 '여비및기타실비' 한 칸을 청구서 항목으로 펼침)·매출액·부가세·매출총액·입금액·접수일·발송일·
# 최근 입금일·진행상태·입금상태·세금계산서/현금영수증. 화면 열 순서와는 다르다(엑셀만).
_EXPORT_COLUMNS = [
    ("doc_id", "감정서번호"), ("purpose", "업무구분"), ("customer_name", "거래처명"),
    ("manager", "유치자"), ("author", "조사자"), ("base_fee", "순수수료"), ("appraisal_amount", "감정가액"),
    ("travel_expense", "여비"), ("survey_fee", "물건조사비"), ("document_fee", "공부발급비"),
    ("land_survey_fee", "토지조사비"), ("other_expense", "기타실비"), ("special_service_fee", "특별용역비"),
    ("sales_amount", "매출액"), ("vat_amount", "부가세"), ("gross_total", "매출총액"), ("received_total", "입금액"),
    ("receipt_date", "접수일"), ("send_date", "발송일"), ("last_received_date", "최근 입금일"),
    ("progress_status", "진행상태"), ("payment_status", "입금상태"), ("proof_issued", "세금계산서/현금영수증"),
]


@router.get("/export.xlsx")
def export_appraisals(
    doc_id: str | None = None,
    cust_doc_id: str | None = None,
    address: str | None = None,
    customer_name: str | None = None,
    manager: str | None = None,
    charge: str | None = None,
    office_code: Annotated[str, Query(pattern=r"^[0-9A-Za-z]+$", max_length=10)] = "10",
    sort_by: Literal["doc_id", "cust_doc_id", "receipt_date", "address", "customer_name", "manager", "author", "purpose", "eval_purpose", "progress_status", "send_date", "appraisal_amount", "base_fee", "appraisal_cost", "sales_amount", "vat_amount", "gross_total", "owner_name", "debtor", "travel_expense", "special_service_fee", "title"] | None = None,
    sort_order: Literal["asc", "desc"] = "asc",
    progress_status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    bill_from: Annotated[float | None, Query(ge=0)] = None,
    bill_to: Annotated[float | None, Query(ge=0)] = None,
    price_from: Annotated[float | None, Query(ge=0)] = None,
    price_to: Annotated[float | None, Query(ge=0)] = None,
    purpose: str | None = None,
    keyword: str | None = None,
    service: AppraisalService = Depends(get_appraisal_service),
    access: AccessContext = Depends(require_menu("appraisals")),
) -> Response:
    today = date.today()
    data = service.list(
        doc_id=doc_id,
        cust_doc_id=cust_doc_id,
        address=address,
        customer_name=customer_name,
        manager=manager,
        charge=charge,
        office_code=resolve_office_scope(access, office_code),
        sort_by=sort_by,
        sort_order=sort_order,
        status=progress_status,
        date_from=date_from or (today - timedelta(days=6)),
        date_to=date_to or today,
        bill_from=bill_from,
        bill_to=bill_to,
        price_from=price_from,
        price_to=price_to,
        purpose=purpose,
        keyword=keyword,
        scope_person=scoped_employee_name(access),
        page=1,
        page_size=EXPORT_MAX_ROWS,
    )
    content = build_xlsx("감정서 목록", _EXPORT_COLUMNS, data["items"])
    return Response(
        content=content, media_type=XLSX_MEDIA_TYPE, headers=xlsx_headers("감정서목록")
    )


@router.get("/offices", response_model=ApiResponse)
def list_offices(
    access: AccessContext = Depends(require_menu("appraisals")),
) -> ApiResponse:
    return ApiResponse(
        success=True,
        code="0000",
        message="조회 완료",
        data=access["offices"],
    )


@router.get("/{doc_id}/vouchers", response_model=ApiResponse)
def get_appraisal_vouchers(
    doc_id: str,
    service: AppraisalService = Depends(get_appraisal_service),
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("appraisals")),
) -> ApiResponse | JSONResponse:
    try:
        # 전표 '읽기'는 입금현황·감정서LIST·반제·데이터품질 상세 패널이 공유하는 공용 조회다.
        # 접근 격리는 assert_document_access(지사·개인 범위)로 충분 — 전표 '생성'(default·
        # partner-context)만 본사 재무 전용이고, 여기에 재무 제한을 걸면 평가사·지사가 전부 막힌다.
        assert_document_access(db, doc_id, access)
        data = service.voucher_detail(doc_id)
        return ApiResponse(success=True, code="0000", message="조회 완료", data=data)
    except AppraisalNotFoundError as exc:
        response = ApiResponse(
            success=False, code="APPRAISAL_NOT_FOUND", message=str(exc), data=None
        )
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=response.model_dump(mode="json"),
        )


@router.get("/{doc_id}/partner-context", response_model=ApiResponse)
def get_partner_context(
    doc_id: str,
    service: DefaultVoucherService = Depends(get_default_voucher_service),
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("appraisals")),
) -> ApiResponse | JSONResponse:
    try:
        require_operations_user(access, "전표 기능은 본사 재무·집행부·전산정보팀만 가능합니다.")
        assert_document_access(db, doc_id, access)
        return ApiResponse(success=True, code="0000", message="조회 완료", data=service.partner_context(doc_id))
    except DefaultVoucherError as exc:
        response = ApiResponse(success=False, code="PARTNER_CONTEXT_FAILED", message=str(exc))
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=response.model_dump(mode="json"))


@router.get("/{doc_id}/vouchers/default/status", response_model=ApiResponse)
def default_voucher_status(
    doc_id: str,
    service: DefaultVoucherService = Depends(get_default_voucher_service),
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("appraisals")),
) -> ApiResponse:
    """기본 매출전표 존재 여부 — 발급 팝업의 '전표 생성' 버튼 상태용."""
    # 형제(전표 생성·partner-context)와 같은 관문 — 여기만 무인증이라 doc_id 만 알면
    # 누구나(로그인 없이도) 전표 존재여부를 캘 수 있었다(2026-08-19 감사). 본사 재무 +
    # 소속 문서만.
    require_operations_user(access, "전표 기능은 본사 재무·집행부·전산정보팀만 가능합니다.")
    assert_document_access(db, doc_id, access)
    exists = service.exists(doc_id)
    return ApiResponse(
        success=True, code="0000", message="조회 완료",
        data={
            "exists": exists,
            # 증빙을 취소하고 다시 발행한 건 — '전표 재생성' 버튼용 (2026-09-02)
            "recreate": bool(exists and service.recreate_context(doc_id)["possible"]),
        },
    )


@router.post("/{doc_id}/vouchers/default", response_model=ApiResponse)
def create_default_voucher(
    doc_id: str,
    request: DefaultVoucherCreateRequest,
    service: DefaultVoucherService = Depends(get_default_voucher_service),
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("appraisals")),
) -> ApiResponse | JSONResponse:
    try:
        require_operations_user(access, "전표 생성은 본사 재무·집행부·전산정보팀만 가능합니다.")
        assert_document_access(db, doc_id, access)
        data = service.create(
            doc_id,
            partner_code=request.partner_code,
            partner_name=request.partner_name,
            voucher_date=request.voucher_date,
            requester_usr_seq=request.requester_usr_seq,
            use_evidence_amount=request.use_evidence_amount,
        )
        message = ("전표가 생성되었습니다 (증빙 금액 기준)."
                   if request.use_evidence_amount else "전표가 생성되었습니다.")
        return ApiResponse(success=True, code="0000", message=message, data=data)
    except DefaultVoucherDuplicateError as exc:
        response = ApiResponse(success=False, code="DUPLICATE_VOUCHER", message=str(exc))
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content=response.model_dump(mode="json"))
    except DefaultVoucherError as exc:
        response = ApiResponse(success=False, code="VOUCHER_CREATION_FAILED", message=str(exc))
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=response.model_dump(mode="json"))


@router.post("/{doc_id}/vouchers/default/recreate", response_model=ApiResponse)
def recreate_default_voucher(
    doc_id: str,
    request: DefaultVoucherCreateRequest,
    service: DefaultVoucherService = Depends(get_default_voucher_service),
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("appraisals")),
) -> ApiResponse | JSONResponse:
    """증빙 취소 후 재발행 건 — 마이너스 전표 1장 + 새 매출 전표 1장 (2026-09-02)."""
    try:
        require_operations_user(access, "전표 생성은 본사 재무·집행부·전산정보팀만 가능합니다.")
        assert_document_access(db, doc_id, access)
        data = service.recreate(
            doc_id,
            partner_code=request.partner_code,
            partner_name=request.partner_name,
            voucher_date=request.voucher_date,
            requester_usr_seq=request.requester_usr_seq,
        )
        return ApiResponse(
            success=True, code="0000",
            message="취소 전표와 새 매출전표가 생성되었습니다.", data=data,
        )
    except DefaultVoucherDuplicateError as exc:
        response = ApiResponse(success=False, code="DUPLICATE_VOUCHER", message=str(exc))
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content=response.model_dump(mode="json"))
    except DefaultVoucherError as exc:
        response = ApiResponse(success=False, code="VOUCHER_CREATION_FAILED", message=str(exc))
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=response.model_dump(mode="json"))
