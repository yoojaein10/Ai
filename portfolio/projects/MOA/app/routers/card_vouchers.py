"""카드전표 API — 엑셀 업로드·검증, 분개 확정(초안), 아마란스 전송.

전표 등록과 거래처 등록은 외부 회계 시스템에 쓰는 작업이라 본사 권한에서만 허용한다.
"""

import os
import secrets
import tempfile
import time
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.common import ApiResponse
from app.services.card_source import CardSourceError
from app.services.card_vouchers import is_advisory
from app.services.card_voucher_service import CardVoucherError, CardVoucherService
from app.services.excel_export import XLSX_MEDIA_TYPE, build_xlsx, xlsx_headers
from app.services.users import UserContextError, UserContextService

router = APIRouter(prefix="/api/card-vouchers", tags=["card-vouchers"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10MB


def _service(db: Session = Depends(get_db)) -> CardVoucherService:
    return CardVoucherService(db)


def _fail(code: str, message: str, http: int = status.HTTP_400_BAD_REQUEST) -> JSONResponse:
    body = ApiResponse(success=False, code=code, message=message, data=None)
    return JSONResponse(status_code=http, content=body.model_dump(mode="json"))


def _check_hq(db: Session, usr_seq: int | str) -> JSONResponse | None:
    """카드전표는 본사(재무팀) 전용 — 소속과 메뉴 권한을 함께 본다.

    소속 검사만 두면 본사 전 직원이 열 수 있다. 메뉴 권한(cardVouchers)까지 봐야
    권한부여 화면에서 재무팀만 켜 둘 수 있다.
    """
    try:
        context = UserContextService(db)._resolve(str(usr_seq))
    except UserContextError as exc:
        return _fail(exc.code, str(exc), status.HTTP_403_FORBIDDEN)
    if context["office_id"] != "10":
        return _fail("NOT_HEAD_OFFICE", "카드전표는 본사만 사용할 수 있습니다.",
                     status.HTTP_403_FORBIDDEN)
    if not (context.get("menu_permissions") or {}).get("cardVouchers", False):
        return _fail("MENU_ACCESS_DENIED", "이 메뉴를 사용할 권한이 없습니다.",
                     status.HTTP_403_FORBIDDEN)
    return None


@router.post("/analyze", response_model=ApiResponse)
async def analyze(
    file: UploadFile = File(...),
    requester_usr_seq: int = Form(...),
    auto_register: bool = Form(False),
    db: Session = Depends(get_db),
    service: CardVoucherService = Depends(_service),
) -> ApiResponse | JSONResponse:
    """카드 사용내역 엑셀을 읽어 검증 결과와 분개 대상 목록을 돌려준다.

    auto_register=True면 미등록 가맹점을 아마란스 거래처로 등록한다(외부 쓰기).
    """
    denied = _check_hq(db, requester_usr_seq)
    if denied is not None:
        return denied

    name = os.path.basename(file.filename or "card.xls")
    if not name.lower().endswith((".xls", ".xlsx")):
        return _fail("BAD_FILE", "엑셀 파일(.xls, .xlsx)만 올릴 수 있습니다.")
    data = await file.read()
    if not data:
        return _fail("BAD_FILE", "빈 파일입니다.")
    if len(data) > MAX_UPLOAD_BYTES:
        return _fail("FILE_TOO_LARGE",
                     f"파일이 너무 큽니다({len(data) // 1024 // 1024}MB). "
                     f"{MAX_UPLOAD_BYTES // 1024 // 1024}MB 이하만 올릴 수 있습니다.")

    suffix = ".xls" if name.lower().endswith(".xls") else ".xlsx"
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        result = service.analyze(tmp_path, auto_register=auto_register)
    except CardVoucherError as exc:
        return _fail("ANALYZE_FAILED", str(exc))
    except Exception as exc:  # 손상된 엑셀·확장자 불일치 등
        return _fail("BAD_FILE", f"엑셀을 읽지 못했습니다: {type(exc).__name__}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
    result["filename"] = name
    return ApiResponse(success=True, code="0000", message="검증 완료", data=result)


@router.get("/fetch", response_model=ApiResponse)
def fetch_from_db(
    requester_usr_seq: int,
    date_from: date,
    date_to: date,
    auto_register: bool = False,
    db: Session = Depends(get_db),
    service: CardVoucherService = Depends(_service),
) -> ApiResponse | JSONResponse:
    """카드내역 DB(CB2_APPR)를 승인일 기간으로 조회해 엑셀 업로드와 같은
    검증 결과·분개 대상 목록을 돌려준다. 이미 전표를 만든 건은 보류로 표시된다."""
    denied = _check_hq(db, requester_usr_seq)
    if denied is not None:
        return denied
    if date_from > date_to:
        return _fail("BAD_RANGE", "시작일이 종료일보다 늦습니다.")
    if (date_to - date_from).days > 92:
        return _fail("BAD_RANGE", "조회 기간은 3개월 이내로 지정하세요.")
    try:
        result = service.analyze_from_db(
            date_from.strftime("%Y%m%d"), date_to.strftime("%Y%m%d"),
            auto_register=auto_register,
        )
    except CardSourceError as exc:
        return _fail("SOURCE_FAILED", str(exc))
    except CardVoucherError as exc:
        return _fail("ANALYZE_FAILED", str(exc))
    result["filename"] = f"카드내역 {date_from:%Y-%m-%d}~{date_to:%Y-%m-%d}"
    return ApiResponse(success=True, code="0000", message="검증 완료", data=result)


class DraftRequest(BaseModel):
    requester_usr_seq: int
    items: list[dict] = Field(min_length=1, max_length=500)
    source_file: str = Field(default="", max_length=260)
    # 전표일자 = 작업일 (재무팀 관행). 없으면 서버 기준 오늘.
    voucher_date: date | None = None


@router.post("/drafts", response_model=ApiResponse)
def create_draft(
    request: DraftRequest,
    db: Session = Depends(get_db),
    service: CardVoucherService = Depends(_service),
) -> ApiResponse | JSONResponse:
    """선택한 건들을 전표 초안으로 확정한다(아마란스 전송 없음)."""
    denied = _check_hq(db, request.requester_usr_seq)
    if denied is not None:
        return denied
    try:
        data = service.create_draft(
            request.items,
            voucher_date=request.voucher_date,
            source_file=request.source_file,
            created_by=str(request.requester_usr_seq),
        )
    except CardVoucherError as exc:
        return _fail("DRAFT_FAILED", str(exc))
    except (KeyError, TypeError, ValueError) as exc:
        return _fail("BAD_REQUEST", f"요청 형식이 올바르지 않습니다: {type(exc).__name__}")
    return ApiResponse(success=True, code="0000", message="분개를 확정했습니다.", data=data)


@router.get("/drafts", response_model=ApiResponse)
def list_drafts(
    requester_usr_seq: int,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    service: CardVoucherService = Depends(_service),
) -> ApiResponse | JSONResponse:
    """전표일자 기준 기간 조회. 기간을 안 주면 당일치."""
    denied = _check_hq(db, requester_usr_seq)
    if denied is not None:
        return denied
    return ApiResponse(success=True, code="0000", message="조회 완료",
                       data=service.list_drafts(date_from=date_from, date_to=date_to))


@router.get("/drafts/{voucher_id}", response_model=ApiResponse)
def draft_detail(
    voucher_id: int,
    requester_usr_seq: int,
    db: Session = Depends(get_db),
    service: CardVoucherService = Depends(_service),
) -> ApiResponse | JSONResponse:
    denied = _check_hq(db, requester_usr_seq)
    if denied is not None:
        return denied
    try:
        return ApiResponse(success=True, code="0000", message="조회 완료",
                           data=service.draft_detail(voucher_id))
    except CardVoucherError as exc:
        return _fail("NOT_FOUND", str(exc), status.HTTP_404_NOT_FOUND)


@router.delete("/drafts/{voucher_id}", response_model=ApiResponse)
def delete_draft(
    voucher_id: int,
    requester_usr_seq: int,
    db: Session = Depends(get_db),
    service: CardVoucherService = Depends(_service),
) -> ApiResponse | JSONResponse:
    """아직 전송하지 않은 전표를 취소한다(전송된 전표는 아마란스에서 직접 삭제)."""
    denied = _check_hq(db, requester_usr_seq)
    if denied is not None:
        return denied
    try:
        data = service.delete_draft(voucher_id)
    except CardVoucherError as exc:
        return _fail("DELETE_FAILED", str(exc))
    return ApiResponse(success=True, code="0000", message="전표를 취소했습니다.", data=data)


class SendRequest(BaseModel):
    requester_usr_seq: int


@router.post("/sync-amaranth", response_model=ApiResponse)
def sync_amaranth(
    request: SendRequest,
    db: Session = Depends(get_db),
    service: CardVoucherService = Depends(_service),
) -> ApiResponse | JSONResponse:
    """전송완료 전표를 아마란스와 대조해, 아마란스에서 삭제된 전표를 X로 정리한다.

    화면이 목록 로드 후 백그라운드로 호출한다. 한 번에 최근 미검사 전표일자
    몇 개만 검사하고(회차당 수 초), 나머지는 다음 로드에서 이어 검사한다.
    """
    denied = _check_hq(db, request.requester_usr_seq)
    if denied is not None:
        return denied
    try:
        data = service.sync_amaranth_deleted()
    except CardVoucherError as exc:
        return _fail("SYNC_FAILED", str(exc))
    return ApiResponse(success=True, code="0000", message="동기화 완료", data=data)


@router.post("/drafts/{voucher_id}/send", response_model=ApiResponse)
def send(
    voucher_id: int,
    request: SendRequest,
    db: Session = Depends(get_db),
    service: CardVoucherService = Depends(_service),
) -> ApiResponse | JSONResponse:
    """확정된 전표를 아마란스에 등록한다. 취소는 아마란스에서 직접 삭제한다."""
    denied = _check_hq(db, request.requester_usr_seq)
    if denied is not None:
        return denied
    try:
        data = service.send(voucher_id, sent_by=str(request.requester_usr_seq))
    except CardVoucherError as exc:
        return _fail("SEND_FAILED", str(exc))
    return ApiResponse(success=True, code="0000", message="아마란스로 전송했습니다.", data=data)


# ── 검증 목록 엑셀 내보내기 ──────────────────────────────────────
# 화면에서 고친 값(계정·공제·공급가액·적요)까지 담아야 해서 목록을 서버로 받는다.
# 데스크톱 앱(pywebview)은 화면에서 만든 Blob을 저장하지 못하고 GET 내려받기만
# 되므로, 받은 목록을 잠시 보관하고 토큰으로 내려받게 한다 (입금 대사와 같은 방식).
_EXPORT_TTL_SECONDS = 600
_EXPORTS: "dict[str, tuple[float, int, str, list[dict[str, Any]]]]" = {}

# 사용자·사용일자·승인시간·가맹점·승인금액은 반드시 붙여 둔다 — 한 번에 끌어
# 복사해 쓴다 (2026-08-20 사용자 요청, 네 칸). 사이에 다른 칸을 끼우지 말 것.
# 승인시간은 사용일자 바로 뒤에 둔다 (2026-09-08 사용자 요청) — 사용일자 칸에
# 시간을 붙이면 '점 없이 20260902 그대로'(9/2, 아마란스 붙여넣기)가 깨지므로 열로 둔다.
_EXPORT_COLUMNS = [
    ("status_text", "상태"),
    ("hold_reason", "보류사유"),
    ("canceled_text", "정상구분"),
    ("card_company", "카드사"),
    ("card_no", "카드번호"),
    # ── 붙여 두는 다섯 칸 ──
    ("user_name", "사용자"),
    ("use_date_text", "사용일자"),
    ("appr_time", "승인시간"),
    ("merchant", "가맹점"),
    ("total", "승인금액"),
    # ──────────────────────
    ("industry", "업종"),
    ("purpose", "계정(사용용도)"),
    ("deductible_text", "공제"),
    ("tax_info", "과세정보"),
    ("supply", "공급가액"),
    ("vat", "부가세"),
    ("remark", "적요"),
]


def _amount(value: "Any") -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _status_text(item: "dict[str, Any]") -> str:
    """화면 배지와 같은 세 글자 — 정상 / 확인(안내뿐인 보류) / 보류(확정이 막히는 보류)."""
    if item.get("status") != "hold":
        return "정상"
    holds = [str(h) for h in (item.get("holds") or [])]
    return "보류" if any(not is_advisory(h) for h in holds) else "확인"


def _export_row(item: "dict[str, Any]") -> "dict[str, Any]":
    """화면 한 줄을 엑셀 한 줄로 옮긴다 — 보이는 문구를 그대로 쓴다."""
    use_date = str(item.get("use_date") or "")
    return {
        "status_text": _status_text(item),
        "hold_reason": " / ".join(str(h) for h in (item.get("holds") or [])),
        "canceled_text": "취소" if item.get("canceled") else "정상",
        "user_name": item.get("user_name") or "",
        # 화면과 같이 카드사·카드번호를 나눠 담고, 번호는 가리지 않는다
        # (2026-08-20 사용자 요청 — 본사 재무팀 전용 화면·파일이다).
        "card_company": item.get("card_alias") or item.get("card_partner_name") or "",
        "card_no": str(item.get("card_no") or ""),
        # 점 없이 20260902 그대로 (2026-09-02 사용자 요청 — 아마란스 붙여넣기용)
        "use_date_text": use_date,
        "appr_time": item.get("appr_time") or "",
        "merchant": item.get("merchant") or "",
        "industry": item.get("industry") or "",
        "total": _amount(item.get("total")),
        "purpose": item.get("purpose") or "",
        "deductible_text": "공제" if item.get("deductible") else "미공제",
        "tax_info": item.get("tax_info") or "",
        "supply": _amount(item.get("supply")),
        "vat": _amount(item.get("vat")),
        "remark": item.get("remark") or "",
    }


class ExportRequest(BaseModel):
    requester_usr_seq: int
    items: list[dict] = Field(min_length=1, max_length=5000)
    filename: str = Field(default="", max_length=260)


@router.post("/export-prepare", response_model=ApiResponse)
def export_prepare(
    request: ExportRequest,
    db: Session = Depends(get_db),
) -> ApiResponse | JSONResponse:
    """내보낼 목록을 받아 보관하고 내려받기 토큰을 준다."""
    denied = _check_hq(db, request.requester_usr_seq)
    if denied is not None:
        return denied
    now = time.time()
    for old in [t for t, (ts, *_rest) in _EXPORTS.items() if now - ts > _EXPORT_TTL_SECONDS]:
        _EXPORTS.pop(old, None)
    token = secrets.token_urlsafe(16)
    rows = [_export_row(item) for item in request.items]
    _EXPORTS[token] = (now, int(request.requester_usr_seq), request.filename, rows)
    return ApiResponse(success=True, code="0000", message="내보내기 준비 완료",
                       data={"token": token, "count": len(rows)})


@router.get("/export.xlsx", response_model=None)
def export_rows(token: str, usr_seq: int) -> Response:
    stored = _EXPORTS.get(token)
    # 토큰을 만든 사람만 받을 수 있다 — 목록에 카드번호·가맹점이 들어 있다.
    if stored is None or stored[1] != int(usr_seq):
        return Response(
            content="내보내기 자료가 만료되었습니다. 다시 눌러 주세요.",
            status_code=410, media_type="text/plain; charset=utf-8",
        )
    _, _owner, filename, rows = stored
    return Response(
        content=build_xlsx("검증목록", _EXPORT_COLUMNS, rows),
        media_type=XLSX_MEDIA_TYPE,
        headers=xlsx_headers(f"카드전표_검증목록{('_' + filename) if filename else ''}"[:80]),
    )
