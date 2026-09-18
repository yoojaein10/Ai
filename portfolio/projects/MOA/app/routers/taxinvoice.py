"""전자세금계산서 발급 API (팝빌). 감정서 우클릭 → 발급 팝업이 사용한다.

POPBILL_IS_TEST=true인 동안 발급은 팝빌 테스트 서버로만 나간다(국세청·거래처 미전송).
"""

from datetime import date
import json
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.dependencies import AccessContext, assert_document_access, require_menu
from app.schemas.common import ApiResponse
from app.models.api_log import ApiLog
from app.services import combined_issue, invoice_pool, popbill_tax
from app.services.partners import PartnerService

router = APIRouter(prefix="/api/taxinvoice", tags=["taxinvoice"])


def _audit_issue_amount(
    db: Session, *, doc_id: str, evidence_type: str,
    supply_cost: int, tax: int, result: dict,
) -> None:
    """식별번호 없이 발행 금액과 결과만 감사 로그에 남긴다."""
    try:
        db.add(ApiLog(
            direction="INBOUND",
            endpoint=f"/api/taxinvoice/{evidence_type}/issue-amount",
            http_status=200 if result.get("success") else 400,
            req_body=json.dumps({
                "doc_id": doc_id, "supply_cost": supply_cost, "tax": tax,
                "total": supply_cost + tax,
            }, ensure_ascii=False),
            res_body=json.dumps({
                "success": bool(result.get("success")),
                "mgt_key": result.get("mgt_key"), "code": result.get("code"),
            }, ensure_ascii=False),
        ))
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass


class IssueRequest(BaseModel):
    doc_id: str = Field(min_length=1, max_length=100)
    write_date: str = Field(pattern=r"^\d{8}$")  # YYYYMMDD
    supply_cost: int = Field(ge=0)
    tax: int = Field(ge=0)
    email: str = ""
    purpose: str = "영수"
    receiver: dict
    # 화면에서 수정 가능한 표기 항목 — 품목(None이면 기본 문구), 품목 비고, 비고1
    item_name: str | None = Field(default=None, max_length=100)
    item_remark: str = Field(default="", max_length=100)
    remark1: str = Field(default="", max_length=120)
    # 수기 입력 팩스번호 — 있으면 발급 성공 후 자동으로 팩스 전송한다
    fax_no: str = Field(default="", max_length=20)
    # 매출 계정과목 — 원장 기록용 (세금계산서 문서·품목명은 안 바뀐다)
    account_code: Literal[
        "4010001", "4010002", "4010003", "4010004", "4010005", "9090000"
    ] = "4010001"
    # 합산 발행 (2026-09-10): 거래처가 같은 다른 감정서 — 있으면 한 장으로 끊고 원장은 건별로 적는다
    extra_doc_ids: list[str] = Field(default_factory=list, max_length=combined_issue.MAX_DOCS - 1)
    # 입금 적용용 (2026-09-10): 대표 감정서번호로 한 장 크게 끊고, 같은 거래처 입금마다 나눠 붙인다
    pool: bool = False


@router.get("/pool-cap", response_model=ApiResponse)
def pool_cap(
    doc_id: str,
    corp_num: str,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("appraisals")),
) -> ApiResponse:
    """입금 적용용 발행 상한 — 그 거래처 감정서들의 미발행 청구액 합과 건별 내역."""
    assert_document_access(db, doc_id, access)
    data = invoice_pool.pool_cap(db, corp_num, doc_id)
    return ApiResponse(success=True, code="0000", message="확인 완료", data=data)


@router.get("/combined-preview", response_model=ApiResponse)
def combined_preview(
    doc_id: str,
    extra: str,
    corp_num: str,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("appraisals")),
) -> ApiResponse:
    """합산 발행 전에 묶을 감정서마다 남은 청구액·거래처 일치를 보여준다 (저장 없음)."""
    try:
        doc_ids = combined_issue.normalize_doc_ids(doc_id, extra.replace("\n", ",").split(","))
        for doc in doc_ids:
            assert_document_access(db, doc, access)
        data = combined_issue.preview(db, doc_ids, corp_num)
    except combined_issue.CombinedIssueError as exc:
        return ApiResponse(success=False, code="BAD_REQUEST", message=str(exc), data=None)
    return ApiResponse(success=True, code="0000", message="확인 완료", data=data)


@router.get("/customer-search", response_model=ApiResponse)
def customer_search(
    q: str,
    db: Session = Depends(get_db),
    _access: AccessContext = Depends(require_menu("appraisals")),
) -> ApiResponse:
    """거래처명(또는 사업자번호)으로 Amaranth 거래처 검색 — 전표 없는 건 수기 선택용.

    회사코드는 서버가 해석한다. api16S11 결과에 사업자번호·대표·업태·종목·주소가 다 있다.
    """
    from app.amaranth.client import AmaranthClient
    from scripts.find_management_numbers import _company_code

    company_code = _company_code(db, AmaranthClient(db))
    data = PartnerService(db).list(company_code, search=q.strip(), page=1, page_size=30)
    return ApiResponse(success=True, code="0000", message="조회 완료", data=data)


class CustomerRegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    business_no: str = Field(min_length=1)
    representative: str | None = None
    business_type: str | None = None
    business_item: str | None = None
    address1: str | None = None
    telephone: str | None = None
    email: str | None = None


@router.post("/register-customer", response_model=ApiResponse)
def register_customer(
    request: CustomerRegisterRequest,
    db: Session = Depends(get_db),
    _access: AccessContext = Depends(require_menu("appraisals")),
) -> ApiResponse | JSONResponse:
    """발급 팝업에 입력한 공급받는자를 Amaranth 거래처로 등록한다.

    회사코드는 customer-search와 같은 방식으로 서버가 해석한다.
    이미 있으면 그 거래처를 돌려준다(팝업이 선택 상태로 쓴다).

    관문은 2026-08-13 에 달았다 — 이 라우터에서 유일하게 빠져 있었다(병합으로 들어온
    게 아니라 처음부터 없었다). 거래처를 **만드는** 쓰기 작업이라 조회용
    customer-search 보다 더 막아야 할 자리다. 짝인 update-customer 는 이미
    같은 관문을 쓰고 있었다.
    """
    from app.amaranth.client import AmaranthClient
    from app.schemas.partner import PartnerCreate
    from app.services.partners import DuplicatePartnerError
    from scripts.find_management_numbers import _company_code

    company_code = _company_code(db, AmaranthClient(db))
    try:
        create = PartnerCreate(
            company_code=company_code,
            business_no=request.business_no,
            name=request.name,
            short_name=request.name,
            representative=request.representative or None,
            business_type=request.business_type or None,
            business_item=request.business_item or None,
            address1=request.address1 or None,
            telephone=request.telephone or None,
            email=request.email or None,
            partner_type="1",
        )
    except ValueError as exc:
        body = ApiResponse(
            success=False, code="INVALID_BUSINESS_NO", message=str(exc), data=None
        )
        return JSONResponse(status_code=422, content=body.model_dump(mode="json"))
    try:
        data = PartnerService(db).create(create)
        return ApiResponse(success=True, code="0000", message="거래처 등록 완료", data=data)
    except DuplicatePartnerError as exc:
        return ApiResponse(
            success=True, code="PARTNER_DUPLICATE",
            message="이미 등록된 거래처입니다.", data=exc.partner,
        )


class CustomerUpdateRequest(BaseModel):
    tr_cd: str = Field(min_length=1)
    values: dict          # corp_num, ceo_name, biz_type, biz_class, addr, email, tel
    apply: bool = False   # False=미리보기(채울 항목만), True=실제 반영


@router.post("/update-customer", response_model=ApiResponse)
def update_customer(
    request: CustomerUpdateRequest,
    db: Session = Depends(get_db),
    _access: AccessContext = Depends(require_menu("appraisals")),
) -> ApiResponse:
    """거래처 마스터의 빈 항목만 후보값으로 채운다. 발급 시 팝업이 '저장할까요?'로 호출."""
    from app.amaranth.client import AmaranthClient
    from scripts.find_management_numbers import _company_code

    company_code = _company_code(db, AmaranthClient(db))
    data = PartnerService(db).fill_missing(
        company_code, request.tr_cd.strip(), request.values, request.apply
    )
    return ApiResponse(success=True, code="0000", message="조회 완료", data=data)


@router.get("/contact-email", response_model=ApiResponse)
def contact_email(
    tr_cd: str,
    db: Session = Depends(get_db),
    _access: AccessContext = Depends(require_menu("appraisals")),
) -> ApiResponse:
    """거래처의 고객사담당자(정) 이메일 — 발급 팝업이 거래처 선택 시 채운다.

    아마란스 세금계산서 화면과 같은 원천(담당자정보 탭). 기본정보 email은
    은행 지점 거래처 대부분이 빈칸이라 쓰지 않는다 (2026-08-12 사용자 확정).

    관문은 2026-08-13 병합 때 달았다. 상류(19098e2)가 이 라우트를 더할 때 권한
    체계가 없는 브랜치라 없이 들어왔다 — 거래처코드만 알면 담당자 이메일을
    누구나 긁을 수 있었다. test_permission_wiring 의 계약이 잡아냈다.
    """
    from app.amaranth.client import AmaranthClient
    from app.services.popbill_tax import _primary_contact_email
    from scripts.find_management_numbers import _company_code

    client = AmaranthClient(db)
    company_code = _company_code(db, client)
    email = _primary_contact_email(client, company_code, tr_cd.strip())
    return ApiResponse(success=True, code="0000", message="조회 완료",
                       data={"email": email})


@router.get("/draft", response_model=ApiResponse)
def get_draft(
    doc_id: str,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("appraisals")),
) -> ApiResponse:
    """감정서번호로 발급 초안(공급받는자·청구액) 조회. 팝업이 이걸로 채운다."""
    assert_document_access(db, doc_id, access)
    data = popbill_tax.appraisal_tax_draft(db, doc_id)
    data["is_test"] = get_settings().popbill_is_test
    return ApiResponse(success=True, code="0000", message="조회 완료", data=data)


@router.post("/issue", response_model=ApiResponse)
def issue(
    request: IssueRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("appraisals")),
) -> ApiResponse:
    """세금계산서 발급. 공급받는자는 팝업에서 확정한 값 그대로 받는다."""
    settings = get_settings()
    assert_document_access(db, request.doc_id, access)
    if not settings.is_popbill_configured:
        return ApiResponse(success=False, code="POPBILL_NOT_CONFIGURED",
                           message="팝빌 설정이 없습니다.", data=None)
    if not request.receiver.get("corp_num"):
        return ApiResponse(success=False, code="NO_RECEIVER",
                           message="공급받는자 사업자번호가 없습니다. 거래처 정보를 확인하세요.", data=None)
    if request.pool:
        return _issue_pool(request, db, settings)
    if request.extra_doc_ids:
        return _issue_combined(request, db, access, settings)
    amount_error = popbill_tax.evidence_issue_error(
        db, request.doc_id, request.supply_cost, request.tax
    )
    if amount_error:
        return ApiResponse(success=False, code="AMOUNT_EXCEEDS_BILLED",
                           message=amount_error, data=None)
    result = popbill_tax.issue_for_appraisal(
        db, doc_id=request.doc_id, write_date=request.write_date,
        supply_cost=request.supply_cost, tax=request.tax,
        receiver=request.receiver, email=request.email, purpose=request.purpose,
        item_name=request.item_name, item_remark=request.item_remark,
        remark1=request.remark1,
    )
    code = "0000" if result.get("success") else "ISSUE_FAILED"
    msg = "발급 완료" if result.get("success") else result.get("message", "발급 실패")
    if result.get("success"):
        mgt_key = result.get("mgt_key") or request.doc_id
        info = popbill_tax.get_info(mgt_key)
        result["info"] = info
        popbill_tax.save_issued(
            db, doc_type="세금계산서", doc_id=request.doc_id, mgt_key=mgt_key,
            receiver_corp_num=request.receiver.get("corp_num", ""),
            receiver_name=request.receiver.get("corp_name", ""),
            supply_cost=request.supply_cost, tax=request.tax, info=info,
            account_code=request.account_code,
        )
        if request.fax_no.strip():
            # 팩스 실패가 발급 성공을 뒤집으면 안 된다 — 결과만 실어 화면에 알린다
            result["fax"] = popbill_tax.send_taxinvoice_fax(
                db, doc_id=request.doc_id, receive_num=request.fax_no
            )
    _audit_issue_amount(
        db, doc_id=request.doc_id, evidence_type="taxinvoice",
        supply_cost=request.supply_cost, tax=request.tax, result=result,
    )
    result["is_test"] = settings.popbill_is_test
    return ApiResponse(success=bool(result.get("success")), code=code, message=msg, data=result)


def _issue_combined(request: IssueRequest, db: Session, access: AccessContext, settings) -> ApiResponse:
    """합산 발행 — 상한은 묶은 감정서 남은 청구액의 합, 팝빌 한 장, 원장은 건별."""
    try:
        doc_ids = combined_issue.normalize_doc_ids(request.doc_id, request.extra_doc_ids)
        for doc in doc_ids[1:]:
            assert_document_access(db, doc, access)
        result = combined_issue.issue(
            db, doc_ids=doc_ids, write_date=request.write_date,
            supply_cost=request.supply_cost, tax=request.tax, receiver=request.receiver,
            email=request.email, purpose=request.purpose, item_remark=request.item_remark,
            remark1=request.remark1, account_code=request.account_code,
        )
    except combined_issue.CombinedIssueError as exc:
        return ApiResponse(success=False, code="AMOUNT_EXCEEDS_BILLED", message=str(exc), data=None)
    ok = bool(result.get("success"))
    if ok and request.fax_no.strip():
        result["fax"] = popbill_tax.send_taxinvoice_fax(db, doc_id=request.doc_id, receive_num=request.fax_no)
    _audit_issue_amount(
        db, doc_id=f"{request.doc_id}+{len(doc_ids) - 1}", evidence_type="taxinvoice-combined",
        supply_cost=request.supply_cost, tax=request.tax, result=result,
    )
    result["is_test"] = settings.popbill_is_test
    return ApiResponse(success=ok, code="0000" if ok else "ISSUE_FAILED",
                       message=f"발급 완료 ({len(doc_ids)}건 합산)" if ok else result.get("message", "발급 실패"),
                       data=result)


def _issue_pool(request: IssueRequest, db: Session, settings) -> ApiResponse:
    """입금 적용용 — 상한은 거래처 미발행 청구액 합, 발행 후 이미 입금된 건에 바로 적용."""
    result = invoice_pool.issue_pool(
        db, doc_id=request.doc_id, write_date=request.write_date,
        supply_cost=request.supply_cost, tax=request.tax, receiver=request.receiver,
        email=request.email, purpose=request.purpose, item_name=request.item_name,
        item_remark=request.item_remark, remark1=request.remark1, account_code=request.account_code,
    )
    ok = bool(result.get("success"))
    if ok and request.fax_no.strip():
        result["fax"] = popbill_tax.send_taxinvoice_fax(db, doc_id=request.doc_id, receive_num=request.fax_no)
    _audit_issue_amount(
        db, doc_id=request.doc_id, evidence_type="taxinvoice-pool",
        supply_cost=request.supply_cost, tax=request.tax, result=result,
    )
    result["is_test"] = settings.popbill_is_test
    applied = (result.get("pool") or {}).get("applied") or []
    message = f"발급 완료 (입금 적용용 · 즉시 적용 {len(applied)}건)" if ok else result.get("message", "발급 실패")
    return ApiResponse(success=ok, code="0000" if ok else "ISSUE_FAILED", message=message, data=result)


class FaxRequest(BaseModel):
    doc_id: str = Field(min_length=1, max_length=100)
    fax_no: str = Field(min_length=8, max_length=20)


@router.post("/fax", response_model=ApiResponse)
def send_fax(
    request: FaxRequest,
    db: Session = Depends(get_db),
    # 이 라우터는 예외 없이 전부 appraisals 관문을 요구한다(형제 엔드포인트와 동일).
    # 병합으로 새로 들어온 라우트라 관문 없이 왔고, 권한 배선 시험이 먼저 잡았다(2026-08-19).
    access: AccessContext = Depends(require_menu("appraisals")),
) -> ApiResponse:
    """발행된 세금계산서를 수기 입력한 번호로 팩스 전송 — 기발행 건 재전송용."""
    # 메뉴 권한만으로는 부족하다 — 지사 사용자도 appraisals 를 갖는다. 소속 문서인지까지
    # 봐야 한다. 안 그러면 지사가 본사 세금계산서를 아무 번호로 팩스 전송해 유출한다
    # (2026-08-19 감사: 발신처를 부르는 쪽이 정하므로 print-url 보다 위험).
    assert_document_access(db, request.doc_id.strip(), access)
    settings = get_settings()
    if not settings.is_popbill_configured:
        return ApiResponse(success=False, code="POPBILL_NOT_CONFIGURED",
                           message="팝빌 설정이 없습니다.", data=None)
    result = popbill_tax.send_taxinvoice_fax(
        db, doc_id=request.doc_id.strip(), receive_num=request.fax_no
    )
    ok = bool(result.get("success"))
    result["is_test"] = settings.popbill_is_test
    return ApiResponse(success=ok, code="0000" if ok else "FAX_FAILED",
                       message="팩스 전송 접수" if ok else result.get("message", "팩스 전송 실패"),
                       data=result)


class MailResendRequest(BaseModel):
    doc_id: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=5, max_length=100)


@router.post("/email", response_model=ApiResponse)
def send_email(
    request: MailResendRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("appraisals")),
) -> ApiResponse:
    """발행된 세금계산서 안내메일을 수기 입력한 주소로 재전송 — 기발행 건용.

    팩스 전송과 같은 이유로 소속 문서인지까지 본다 (2026-08-19 감사 참조 —
    수신처를 부르는 쪽이 정하므로 지사가 남의 계산서를 유출할 수 있다).
    """
    assert_document_access(db, request.doc_id.strip(), access)
    settings = get_settings()
    if not settings.is_popbill_configured:
        return ApiResponse(success=False, code="POPBILL_NOT_CONFIGURED",
                           message="팝빌 설정이 없습니다.", data=None)
    result = popbill_tax.send_taxinvoice_email(
        db, doc_id=request.doc_id.strip(), email=request.email
    )
    ok = bool(result.get("success"))
    result["is_test"] = settings.popbill_is_test
    return ApiResponse(
        success=ok, code="0000" if ok else "EMAIL_FAILED",
        message="메일 재전송 접수" if ok else result.get("message", "메일 재전송 실패"),
        data=result,
    )


class TaxCorrectionReplacement(BaseModel):
    write_date: str = Field(pattern=r"^\d{8}$")
    supply_cost: int = Field(ge=0)
    tax: int = Field(ge=0)
    receiver: dict
    purpose: str = "영수"
    item_name: str | None = Field(default=None, max_length=100)
    item_remark: str = Field(default="", max_length=100)
    remark1: str = Field(default="", max_length=120)


class TaxCancelRequest(BaseModel):
    doc_id: str = Field(min_length=1, max_length=100)
    reason_code: Literal[1, 2, 3, 4, 5, 6] = 6
    reason_date: date | None = None
    adjust_supply: int | None = None
    adjust_tax: int | None = None
    replacement: TaxCorrectionReplacement | None = None
    memo: str = Field(default="", max_length=120)


@router.post("/cancel", response_model=ApiResponse)
def tax_cancel(
    request: TaxCancelRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("appraisals")),
) -> ApiResponse:
    """세금계산서 수정발급 — 국세청 수정사유 1~6의 발행 규칙을 적용한다.

    관문은 2026-08-13 병합 때 달았다. 상류(main)에서 이 라우트가 들어올 때 권한
    체계가 없는 브랜치라 관문이 없었고, 그대로 두면 **되돌릴 수 없는 발급 취소를
    감정서번호만 알면 누구나** 부를 수 있었다. 같은 라우터의 발급(issue)과 같은
    잣대(appraisals 메뉴 + 그 감정서 열람 권한)를 쓴다.
    """
    assert_document_access(db, request.doc_id, access)
    settings = get_settings()
    if not settings.is_popbill_configured:
        return ApiResponse(success=False, code="POPBILL_NOT_CONFIGURED",
                           message="팝빌 설정이 없습니다.", data=None)
    # 입금 적용용 (2026-09-10): 적용 행(자식)에서는 취소 불가 — 모계산서는 대표 감정서에서 전액 취소만
    pool_state = invoice_pool.pool_state_of(db, request.doc_id.strip())
    if pool_state["child"]:
        return ApiResponse(success=False, code="POOL_CHILD",
                           message="입금 적용으로 붙은 계산서입니다. 대표 감정서에서 취소하거나 적용 현황에서 해제하세요.", data=None)
    if pool_state["pool"] and request.reason_code not in (4, 6):
        return ApiResponse(success=False, code="POOL_FULL_CANCEL_ONLY",
                           message="입금 적용용 계산서는 전액 취소(계약의 해제·이중발급)만 할 수 있습니다.", data=None)
    # 합산 발행 한 장은 전액 취소(4·6)만 — 증감·재발행은 감정서별 몫을 나눌 수 없다 (2026-09-10)
    combined_key = None if pool_state["pool"] else combined_issue.combined_mgt_key(db, request.doc_id.strip())
    if combined_key and request.reason_code not in (4, 6):
        return ApiResponse(success=False, code="COMBINED_FULL_CANCEL_ONLY",
                           message="합산 발행 건은 전액 취소(계약의 해제·이중발급)만 할 수 있습니다.", data=None)
    before_id = int(db.execute(text("SELECT ISNULL(MAX(id), 0) FROM dbo.a10_issued_taxinvoice")).scalar() or 0)
    result = popbill_tax.cancel_taxinvoice(
        db,
        doc_id=request.doc_id.strip(),
        reason_code=request.reason_code,
        reason_date=request.reason_date,
        adjust_supply=request.adjust_supply,
        adjust_tax=request.adjust_tax,
        replacement=request.replacement.model_dump() if request.replacement else None,
        memo=request.memo.strip(),
    )
    ok = bool(result.get("success"))
    result["is_test"] = settings.popbill_is_test
    if ok and pool_state["pool"]:
        result["pool_cancelled"] = invoice_pool.record_pool_cancel(
            db, request.doc_id.strip(), int(pool_state["pool_id"]), before_id,
        )
    if ok and combined_key:
        result["combined_cancelled"] = combined_issue.record_combined_cancel(
            db, request.doc_id.strip(), combined_key, before_id,
        )
    # 수정발급(재발행)이 성공하면 전표도 곧바로 자동 재생성한다 — 예전엔 발급 팝업의
    # '전표 재생성'을 따로 눌러야 했다(2026-09-04 사용자 요청). 전액취소(cancelled)나
    # 재생성 대상이 아닌 건(기존 전표 없음·이미 재생성 등)은 건너뛴다. 전표는 본사
    # 재무·집행부·전산정보팀만 만들 수 있으므로 그 권한일 때만 시도하고, 실패해도
    # 수정발급 자체는 성공으로 둔다 — save_issued가 이미 커밋했고, 팝업의 '전표
    # 재생성' 버튼으로 다시 시도할 수 있다.
    if ok and result.get("cancelled") is False and access.get("is_operations"):
        result["voucher_recreated"] = _auto_recreate_voucher(db, request.doc_id.strip())
    return ApiResponse(success=ok, code="0000" if ok else "CANCEL_FAILED",
                       message="취소(수정발행) 완료" if ok else result.get("message", "취소 실패"),
                       data=result)


def _auto_recreate_voucher(db: Session, doc_id: str) -> dict:
    """수정발급 직후 취소 전표 + 새 매출전표를 자동으로 만든다 (best-effort).

    성공 {done:True} / 대상 아님·실패 {done:False, reason}. 어느 쪽이든 예외를
    던지지 않아 수정발급 응답을 막지 않는다. 거래처는 기존 외상매출금 라인에서
    recreate_context가 뽑으므로 화면 입력이 필요 없다.
    """
    from app.services.default_vouchers import (
        DefaultVoucherService,
        DefaultVoucherError,
        DefaultVoucherDuplicateError,
    )

    service = DefaultVoucherService(db)
    ctx = service.recreate_context(doc_id)
    if not ctx["possible"]:
        return {"done": False, "reason": ctx["reason"] or "전표 재생성 대상이 아닙니다."}
    if not ctx["partner_code"]:
        return {"done": False,
                "reason": "전표 거래처를 찾지 못했습니다 — 팝업에서 '전표 재생성'을 눌러 주세요."}
    try:
        service.recreate(
            doc_id,
            partner_code=ctx["partner_code"], partner_name=ctx["partner_name"],
            voucher_date=date.today(),
        )
    except (DefaultVoucherError, DefaultVoucherDuplicateError) as exc:
        return {"done": False, "reason": str(exc)}
    return {"done": True}


def _auto_cash_cancel_voucher(db: Session, doc_id: str, cancel_mgt_key: str) -> dict:
    """현금영수증 취소 직후 상쇄 전표를 자동 생성한다 (best-effort)."""
    from app.services.default_vouchers import (
        DefaultVoucherService,
        DefaultVoucherError,
        DefaultVoucherDuplicateError,
    )

    try:
        result = DefaultVoucherService(db).create_cash_cancel_voucher(
            doc_id,
            cancel_mgt_key=cancel_mgt_key,
            voucher_date=date.today(),
        )
    except (DefaultVoucherError, DefaultVoucherDuplicateError) as exc:
        return {"done": False, "reason": str(exc)}
    return {"done": True, "voucher_no": result.get("cancel_voucher_no")}


@router.get("/status", response_model=ApiResponse)
def status(
    doc_id: str,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("appraisals")),
) -> ApiResponse:
    assert_document_access(db, doc_id, access)
    return ApiResponse(success=True, code="0000", message="조회 완료",
                       data=popbill_tax.get_info(doc_id))


@router.get("/print-url", response_model=ApiResponse)
def print_url(
    doc_id: str,
    doc_type: Literal["세금계산서", "현금영수증"] = "세금계산서",
    # 둘 다 필요하다 (2026-08-13 병합). main 은 본문에서 최신 발행분을 찾으려고
    # db 를 받았고(취소 후 재발행이면 mgt_key 가 감정서번호와 다르다), 이 브랜치는
    # 무인증 구멍을 막으려고 관문을 달았다. 하나만 남기면 다른 하나가 깨진다.
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("appraisals")),
) -> ApiResponse:
    """발행 건의 인쇄 팝업 URL — 유형별 양식으로 열린다 (30초 내 접속, 재사용 불가).

    이 라우터의 다른 엔드포인트는 모두 appraisals 메뉴 권한을 요구하는데 여기만
    빠져 있었다. doc_id 만 알면 로그인 없이 남의 세금계산서 인쇄본을 열 수 있었다.
    """
    # 메뉴 권한만으로는 부족하다 — 지사 사용자도 appraisals 를 갖는다. 형제
    # (status/cancel/issue)처럼 소속 문서인지까지 본다. 안 그러면 doc_id 만 알면
    # 지사가 본사 세금계산서 인쇄본을 연다(2026-08-19 감사).
    assert_document_access(db, doc_id, access)
    if not get_settings().is_popbill_configured:
        return ApiResponse(success=False, code="POPBILL_NOT_CONFIGURED",
                           message="팝빌 설정이 없습니다.", data=None)
    mgt_key = doc_id
    # 취소 후 재발행 건은 mgt_key가 감정서번호와 다르다(-R{차수}) — 최신 발행분으로.
    if doc_type == "세금계산서":
        state = popbill_tax.latest_taxinvoice_row(db, doc_id)
        if state and state[0] == "세금계산서":
            mgt_key = state[1]
    else:
        state = popbill_tax.latest_cashbill_row(db, doc_id)
        if state and state[0] == "현금영수증":
            mgt_key = state[1]
    try:
        url = popbill_tax.print_url(doc_type, mgt_key)
    except RuntimeError as exc:
        return ApiResponse(success=False, code="PRINT_URL_FAILED", message=str(exc), data=None)
    return ApiResponse(success=True, code="0000", message="조회 완료", data={"url": url})


class CashbillRequest(BaseModel):
    doc_id: str = Field(min_length=1, max_length=100)
    trade_usage: str = "소득공제용"  # 소득공제용 / 지출증빙용
    identity_num: str = Field(min_length=1)  # 휴대폰번호(소득공제) 또는 사업자번호(지출증빙)
    supply_cost: int = Field(ge=0)
    tax: int = Field(ge=0)
    customer_name: str = ""
    email: str = ""
    hp: str = ""


@router.post("/cashbill/issue", response_model=ApiResponse)
def cashbill_issue(
    request: CashbillRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("appraisals")),
) -> ApiResponse:
    """현금영수증 발급. 식별번호(휴대폰/사업자번호)는 재무팀이 팝업에서 수기 입력."""
    settings = get_settings()
    assert_document_access(db, request.doc_id, access)
    if not settings.is_popbill_configured:
        return ApiResponse(success=False, code="POPBILL_NOT_CONFIGURED",
                           message="팝빌 설정이 없습니다.", data=None)
    amount_error = popbill_tax.evidence_issue_error(
        db, request.doc_id, request.supply_cost, request.tax
    )
    if amount_error:
        return ApiResponse(success=False, code="AMOUNT_EXCEEDS_BILLED",
                           message=amount_error, data=None)
    result = popbill_tax.issue_cashbill(
        db, doc_id=request.doc_id, trade_usage=request.trade_usage,
        identity_num=request.identity_num.replace("-", ""),
        supply_cost=request.supply_cost, tax=request.tax,
        customer_name=request.customer_name, email=request.email, hp=request.hp,
    )
    ok = bool(result.get("success"))
    if ok:
        mgt_key = result.get("mgt_key") or request.doc_id
        info = popbill_tax.get_cashbill_info(mgt_key)
        result["info"] = info
        popbill_tax.save_issued(
            db, doc_type="현금영수증", doc_id=request.doc_id, mgt_key=mgt_key,
            receiver_corp_num=request.identity_num.replace("-", ""),
            receiver_name=request.customer_name,
            supply_cost=request.supply_cost, tax=request.tax, info=info,
            trade_usage=request.trade_usage,
        )
    _audit_issue_amount(
        db, doc_id=request.doc_id, evidence_type="cashbill",
        supply_cost=request.supply_cost, tax=request.tax, result=result,
    )
    result["is_test"] = settings.popbill_is_test
    return ApiResponse(success=ok, code="0000" if ok else "ISSUE_FAILED",
                       message="발급 완료" if ok else result.get("message", "발급 실패"),
                       data=result)


class CashbillCancelRequest(BaseModel):
    doc_id: str = Field(min_length=1, max_length=100)
    cancel_type: int = Field(default=1, ge=1, le=3)  # 1.거래취소 2.오류발급취소 3.기타
    memo: str = ""


@router.post("/cashbill/cancel", response_model=ApiResponse)
def cashbill_cancel(
    request: CashbillCancelRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("appraisals")),
) -> ApiResponse:
    """취소 현금영수증 발행 — MOA(팝빌)로 발급한 건만. 국세청 전송 후에도 가능.

    관문은 2026-08-13 병합 때 달았다 — 위 tax_cancel 과 같은 이유다.
    """
    assert_document_access(db, request.doc_id, access)
    settings = get_settings()
    if not settings.is_popbill_configured:
        return ApiResponse(success=False, code="POPBILL_NOT_CONFIGURED",
                           message="팝빌 설정이 없습니다.", data=None)
    result = popbill_tax.cancel_cashbill(
        db, doc_id=request.doc_id.strip(), cancel_type=request.cancel_type,
        memo=request.memo.strip(),
    )
    ok = bool(result.get("success"))
    result["is_test"] = settings.popbill_is_test
    # 팝빌 취소가 확정된 뒤 기존 매출을 상쇄하는 전표도 곧바로 만든다. 전표 권한이
    # 있는 운영 사용자만 시도하고, Amaranth 실패가 현금영수증 취소 자체를 되돌리지는 않는다.
    if ok and access.get("is_operations"):
        cancel_mgt_key = str(result.get("mgt_key") or f"{request.doc_id.strip()}-C")
        result["cancel_voucher_created"] = _auto_cash_cancel_voucher(
            db, request.doc_id.strip(), cancel_mgt_key
        )
    return ApiResponse(success=ok, code="0000" if ok else "CANCEL_FAILED",
                       message="취소 완료" if ok else result.get("message", "취소 실패"),
                       data=result)
