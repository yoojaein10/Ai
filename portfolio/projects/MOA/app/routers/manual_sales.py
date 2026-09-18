"""감정서번호 없는 탁상·가격자문 수기 매출 API."""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.dependencies import (
    AccessContext,
    require_menu,
    require_operations_user,
    resolve_office_scope,
)
from app.schemas.common import ApiResponse
from app.services import popbill_tax
from app.services.default_vouchers import issued_tax_invoice_confirm
from app.services.manual_sales import (
    ManualSaleDuplicateError,
    ManualSaleError,
    ManualSaleService,
)


router = APIRouter(prefix="/api/manual-sales", tags=["manual-sales"])
_REFERENCE = r"^MS-\d{8}-[A-Z0-9]{8}$"
_ACCOUNTS = Literal["4010001", "4010002", "4010003", "4010004", "4010005", "9090000"]


class ManualTaxIssueRequest(BaseModel):
    reference: str = Field(pattern=_REFERENCE)
    office_code: str = Field(min_length=1, max_length=10)
    write_date: str = Field(pattern=r"^\d{8}$")
    supply_cost: int = Field(gt=0)
    tax: int = Field(ge=0)
    receiver: dict
    email: str = Field(default="", max_length=100)
    purpose: Literal["영수", "청구"] = "영수"
    item_name: str = Field(default="탁상수수료", min_length=1, max_length=100)
    item_remark: str = Field(default="", max_length=100)
    remark1: str = Field(default="", max_length=120)
    account_code: _ACCOUNTS = "4010002"


class ManualVoucherRequest(BaseModel):
    reference: str = Field(pattern=_REFERENCE)
    office_code: str = Field(min_length=1, max_length=10)
    partner_code: str = Field(min_length=1, max_length=20)
    partner_name: str = Field(min_length=1, max_length=100)
    voucher_date: date
    supply_cost: int = Field(gt=0)
    tax: int = Field(ge=0)
    revenue_account: _ACCOUNTS = "4010002"
    sales_division: str = Field(default="09", max_length=2)
    memo: str = Field(default="탁상수수료", min_length=1, max_length=100)


def _authorize_office(access: AccessContext, office_code: str) -> str:
    require_operations_user(
        access, "수기 매출은 본사 재무·집행부·전산정보팀만 처리할 수 있습니다."
    )
    return str(resolve_office_scope(access, office_code) or office_code)


@router.post("/taxinvoice", response_model=ApiResponse)
def issue_manual_taxinvoice(
    request: ManualTaxIssueRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("appraisals")),
) -> ApiResponse | JSONResponse:
    _authorize_office(access, request.office_code)
    settings = get_settings()
    if not settings.is_popbill_configured:
        return ApiResponse(
            success=False, code="POPBILL_NOT_CONFIGURED",
            message="팝빌 설정이 없습니다.", data=None,
        )
    if not request.receiver.get("corp_num"):
        return ApiResponse(
            success=False, code="NO_RECEIVER",
            message="공급받는자 사업자번호가 없습니다.", data=None,
        )
    if issued_tax_invoice_confirm(db, request.reference) is not None:
        response = ApiResponse(
            success=False, code="DUPLICATE_TAXINVOICE",
            message="이미 세금계산서가 발급된 수기 매출입니다.", data=None,
        )
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=response.model_dump(mode="json"),
        )

    result = popbill_tax.issue_for_appraisal(
        db,
        doc_id=request.reference,
        write_date=request.write_date,
        supply_cost=request.supply_cost,
        tax=request.tax,
        receiver=request.receiver,
        email=request.email,
        purpose=request.purpose,
        item_name=request.item_name,
        item_remark=request.item_remark,
        remark1=request.remark1,
    )
    if not result.get("success"):
        result["is_test"] = settings.popbill_is_test
        return ApiResponse(
            success=False, code="ISSUE_FAILED",
            message=result.get("message", "발급 실패"), data=result,
        )
    mgt_key = result.get("mgt_key") or request.reference
    info = popbill_tax.get_info(mgt_key)
    result["info"] = info
    popbill_tax.save_issued(
        db,
        doc_type="세금계산서",
        doc_id=request.reference,
        mgt_key=mgt_key,
        receiver_corp_num=request.receiver.get("corp_num", ""),
        receiver_name=request.receiver.get("corp_name", ""),
        supply_cost=request.supply_cost,
        tax=request.tax,
        info=info,
        account_code=request.account_code,
    )
    result["is_test"] = settings.popbill_is_test
    return ApiResponse(success=True, code="0000", message="발급 완료", data=result)


@router.post("/voucher", response_model=ApiResponse)
def create_manual_voucher(
    request: ManualVoucherRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("appraisals")),
) -> ApiResponse | JSONResponse:
    office_code = _authorize_office(access, request.office_code)
    service = ManualSaleService(db)
    try:
        data = service.create(
            reference=request.reference,
            office_code=office_code,
            partner_code=request.partner_code,
            partner_name=request.partner_name,
            voucher_date=request.voucher_date,
            supply_cost=request.supply_cost,
            tax=request.tax,
            revenue_account=request.revenue_account,
            sales_division=request.sales_division,
            memo=request.memo,
            tax_invoice_confirm=issued_tax_invoice_confirm(db, request.reference),
        )
        return ApiResponse(
            success=True, code="0000", message="전표가 생성되었습니다.", data=data,
        )
    except ManualSaleDuplicateError as exc:
        response = ApiResponse(
            success=False, code="DUPLICATE_VOUCHER", message=str(exc), data=None,
        )
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=response.model_dump(mode="json"),
        )
    except ManualSaleError as exc:
        response = ApiResponse(
            success=False, code="VOUCHER_CREATION_FAILED", message=str(exc), data=None,
        )
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=response.model_dump(mode="json"),
        )
