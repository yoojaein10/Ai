"""상여 v2 API — 새 엔진(bonus_report_v2)의 조회·입력·마감. 구 /api/bonus 는 4단계 컷오버까지 그대로 둔다.

period 는 지급월(YYYYMM). 입금월은 그 전달이다 ("2026-09 지급분 · 입금월 2026-08").
- GET  ""                              리포트 (개인 범위는 본인 것만)
- GET  /journal?period=                총괄표 + 전표 라인 (집행부만)
- PUT  /deductions/{period}/{person}   그 달·그 사람에게 적용할 공제 대장 항목 집합 (빠진 것은 대기로)
- GET/POST/PUT /deduction-items[/{id}], POST /deduction-items/{id}/void  공제 대장
- PUT  /overrides/{period}             (감정서, 사람) 오버라이드 통째 교체
- POST /close/{period} · /reopen/{period}
"""

import re
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    AccessContext,
    require_menu,
    require_menu_write,
    require_operations_user,
    require_same_requester,
    scoped_employee_name,
)
from app.schemas.common import ApiResponse
from app.services.bonus import closing, deduction_import, deduction_items, ledger, sources_apw
from app.services.bonus.report import bonus_report_v2
from app.services.bonus.schedule import BonusMasterError
from app.services.bonus.search import search_bonus
from app.services.bonus.export import build_bonus_workbook
from app.services.bonus.summary import journal_lines
from app.services.excel_export import XLSX_MEDIA_TYPE, build_xlsx, xlsx_headers

router = APIRouter(prefix="/api/bonus/v2", tags=["bonus"])
_PERIOD = re.compile(r"^\d{6}$")
_PERSON = Annotated[str, StringConstraints(min_length=1, max_length=30, strip_whitespace=True)]
_READ_MESSAGE = "총괄표·전표·공제 대장은 본사 재무팀·집행부만 볼 수 있습니다."
_STATUS_LABEL = {"PENDING": "대기", "APPLIED": "적용", "VOID": "무효"}
_SOURCE_LABEL = {"MANUAL": "수기", "EXCEL": "엑셀", "VOUCHER": "전표"}
_DEDUCTION_COLUMNS = [
    ("item_id", "번호"), ("status", "상태"), ("person", "사람"), ("kind", "종류"), ("amount", "금액"), ("doc_id", "감정서"),
    ("occurred_on", "발생일"), ("memo", "메모"), ("source", "출처"), ("applied_period", "적용 지급월"), ("applied_at", "적용일시"),
    ("void_reason", "무효 사유"), ("created_at", "등록일시"),
]
_WRITE_MESSAGE = "상여 입력·마감은 본사 재무팀·집행부만 가능합니다."


class DeductionNewItem(BaseModel):
    kind: str = Field(min_length=1, max_length=16)
    amount: float = Field(ge=0)
    doc_id: str | None = Field(default=None, max_length=50)
    occurred_on: date | None = None
    memo: str | None = Field(default=None, max_length=200)


class DeductionsApplyRequest(BaseModel):
    """이 달·이 사람에게 적용할 공제 집합 — 대장 항목 id 들 + 새로 만들어 바로 적용할 항목들."""
    requester_usr_seq: int
    applied_item_ids: list[int] = Field(default_factory=list, max_length=200)
    new_items: list[DeductionNewItem] = Field(default_factory=list, max_length=50)


class DeductionItemRequest(BaseModel):
    requester_usr_seq: int
    person: _PERSON
    kind: str = Field(min_length=1, max_length=16)
    amount: float = Field(ge=0)
    doc_id: str | None = Field(default=None, max_length=50)
    occurred_on: date | None = None
    memo: str | None = Field(default=None, max_length=200)
    apply_period: str | None = Field(default=None, min_length=6, max_length=6)


class DeductionItemUpdateRequest(BaseModel):
    requester_usr_seq: int
    kind: str | None = Field(default=None, min_length=1, max_length=16)
    amount: float | None = Field(default=None, ge=0)
    doc_id: str | None = Field(default=None, max_length=50)
    occurred_on: date | None = None
    memo: str | None = Field(default=None, max_length=200)


class DeductionVoidRequest(BaseModel):
    requester_usr_seq: int
    reason: str = Field(min_length=1, max_length=200)


class DeductionSplitRequest(BaseModel):
    requester_usr_seq: int
    amount: float = Field(gt=0)


class OverrideSaveRequest(BaseModel):
    requester_usr_seq: int
    doc_id: Annotated[str, StringConstraints(min_length=1, max_length=50, strip_whitespace=True)]
    person: _PERSON
    # {"INCLUDE": null, "FEE": 580000, "WORK": "가격자문"} — 빈 dict 면 전부 지운다
    actions: dict[str, float | str | None] = Field(default_factory=dict)


class RequesterRequest(BaseModel):
    requester_usr_seq: int


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    response = ApiResponse(success=False, code=code, message=message, data=None)
    return JSONResponse(status_code=status_code, content=response.model_dump(mode="json"))


def _ok(message: str, data: "dict[str, Any]") -> ApiResponse:
    return ApiResponse(success=True, code="0000", message=message, data=data)


def _bad_period(period: str) -> "JSONResponse | None":
    if not _PERIOD.match(period or "") or not (1 <= int(period[4:]) <= 12):
        return _error(status.HTTP_400_BAD_REQUEST, "BAD_PERIOD", "지급월은 YYYYMM 이어야 합니다.")
    return None


@router.get("", response_model=ApiResponse)
def get_bonus_v2(
    period: Annotated[str, Query(min_length=6, max_length=6, description="지급월 YYYYMM")],
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("bonus")),
) -> ApiResponse | JSONResponse:
    if (bad := _bad_period(period)) is not None:
        return bad
    # 개인 범위 조회는 본인 것만 — 화면이 hq-only 여도 이 줄이 마지막 울타리다.
    data = bonus_report_v2(db, period, scope_person=scoped_employee_name(access))
    return _ok("조회 완료", data)


@router.get("/search", response_model=ApiResponse)
def get_search(
    period_from: Annotated[str, Query(min_length=6, max_length=6, description="시작 지급월 YYYYMM")],
    period_to: Annotated[str, Query(min_length=6, max_length=6, description="끝 지급월 YYYYMM")],
    doc_id: Annotated[str | None, Query(max_length=50, description="감정서번호 (일부만 넣어도 됨)")] = None,
    person: Annotated[str | None, Query(max_length=30, description="유치자 이름 (일부만 넣어도 됨)")] = None,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("bonus")),
) -> ApiResponse | JSONResponse:
    """여러 달(최대 12) 상여를 감정서번호·유치자로 찾는다 — 마감 달은 스냅샷, 열린 달은 계산."""
    for period in (period_from, period_to):
        if (bad := _bad_period(period)) is not None:
            return bad
    try:
        data = search_bonus(db, period_from, period_to, doc_id=doc_id, person=person, scope_person=scoped_employee_name(access))
    except BonusMasterError as exc:
        return _error(status.HTTP_400_BAD_REQUEST, "BAD_RANGE", str(exc))
    return _ok("조회 완료", data)


@router.get("/status", response_model=ApiResponse)
def get_status(
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("bonus")),
) -> ApiResponse:
    closes = closing.list_closes(db)
    return _ok("조회 완료", {"periods": closes, "next": closing.next_open_period(closes, date.today())})


@router.get("/export.xlsx", response_model=None)
def export_xlsx(
    period: Annotated[str, Query(min_length=6, max_length=6, description="지급월 YYYYMM")],
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("bonus")),
) -> Response | JSONResponse:
    if (bad := _bad_period(period)) is not None:
        return bad
    report = bonus_report_v2(db, period, scope_person=scoped_employee_name(access))
    filename = f"성과상여_{period[:4]}-{period[4:]}지급분"
    return Response(content=build_bonus_workbook(report), media_type=XLSX_MEDIA_TYPE, headers=xlsx_headers(filename))


@router.get("/docs", response_model=ApiResponse)
def get_docs(
    person: Annotated[str, Query(min_length=1, max_length=30)],
    date_from: date,
    date_to: date,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("bonus")),
) -> ApiResponse | JSONResponse:
    """그 사람이 담당(공(X) 포함)인 감정서를 접수일로 찾는다 — 화면 '추가'(못 가져온 감정서 수기 포함)."""
    require_operations_user(access, _READ_MESSAGE)
    if date_from > date_to or (date_to - date_from).days > 1100:
        return _error(status.HTTP_400_BAD_REQUEST, "BAD_RANGE", "접수일 구간은 3년 이내로, 시작이 끝보다 앞이어야 합니다.")
    return _ok("조회 완료", {"items": sources_apw.search_docs(db, person.strip(), date_from, date_to)})


@router.get("/deduction-items/template.xlsx", response_model=None)
def deduction_template(
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("bonus")),
) -> Response:
    require_operations_user(access, _READ_MESSAGE)
    return Response(content=deduction_import.template_workbook(), media_type=XLSX_MEDIA_TYPE, headers=xlsx_headers("상여_공제_올리기_양식"))


@router.post("/deduction-items/import", response_model=ApiResponse)
async def import_deduction_items(
    requester_usr_seq: Annotated[int, Form()],
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu_write("bonus")),
) -> ApiResponse | JSONResponse:
    """엑셀(사람·종류·금액·감정서·발생일·메모·적용월)을 공제 대장에 넣는다. 같은 파일은 두 번 들어가지 않는다."""
    require_same_requester(access, requester_usr_seq)
    require_operations_user(access, _WRITE_MESSAGE)
    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        return _error(status.HTTP_400_BAD_REQUEST, "FILE_TOO_BIG", "5MB 이하 파일만 올릴 수 있습니다.")
    try:
        rows, errors = deduction_import.parse_workbook(content, source_label=f"xlsx:{(file.filename or '')[:40]}")
    except Exception as exc:  # noqa: BLE001 — 깨진 파일은 한 줄로 알린다
        return _error(status.HTTP_400_BAD_REQUEST, "FILE_INVALID", f"엑셀을 읽지 못했습니다: {exc}")
    created = skipped = 0
    for row in rows:
        try:
            item = deduction_items.create_item(db, row, usr_seq=requester_usr_seq, apply_period=row.get("apply_period"))
        except BonusMasterError as exc:
            errors.append(f"{row['person']} {row['kind']} {row['amount']:,.0f}: {exc}")
            continue
        if item.get("skipped"):
            skipped += 1
        else:
            created += 1
    message = f"{created}건 등록" + (f" · 이미 있어 건너뜀 {skipped}건" if skipped else "") + (f" · 오류 {len(errors)}건" if errors else "")
    return _ok(message, {"created": created, "skipped": skipped, "errors": errors[:50]})


@router.get("/journal", response_model=ApiResponse)
def get_journal(
    period: Annotated[str, Query(min_length=6, max_length=6, description="지급월 YYYYMM")],
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("bonus")),
) -> ApiResponse | JSONResponse:
    require_operations_user(access, _READ_MESSAGE)
    if (bad := _bad_period(period)) is not None:
        return bad
    report = bonus_report_v2(db, period)
    return _ok("조회 완료", {
        "period": period, "status": report["status"], "summary": report["summary"],
        "lines": journal_lines(report["summary"]),
    })


@router.put("/deductions/{period}/{person}", response_model=ApiResponse)
def put_deductions(
    period: str,
    person: _PERSON,
    request: DeductionsApplyRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu_write("bonus")),
) -> ApiResponse | JSONResponse:
    """공제 대장에서 이 달에 적용할 항목을 고른다 (빠진 것은 대기로 돌아간다)."""
    require_same_requester(access, request.requester_usr_seq)
    require_operations_user(access, _WRITE_MESSAGE)
    if (bad := _bad_period(period)) is not None:
        return bad
    if closing.close_status(db, period) == "CLOSED":
        return _error(status.HTTP_409_CONFLICT, "PERIOD_CLOSED", f"{period} 은 마감돼 있습니다 — 먼저 재개하세요.")
    try:
        ids = list(request.applied_item_ids)
        for item in request.new_items:
            created = deduction_items.create_item(db, {**item.model_dump(), "person": person}, usr_seq=request.requester_usr_seq)
            ids.append(created["item_id"])
        applied = deduction_items.set_applied(db, period, person, ids, usr_seq=request.requester_usr_seq)
    except BonusMasterError as exc:
        return _error(status.HTTP_400_BAD_REQUEST, "INPUT_INVALID", str(exc))
    return _ok(f"{person}의 공제 {len(applied)}건을 적용했습니다.", {"period": period, "person": person, "applied": applied})


@router.get("/deduction-items", response_model=ApiResponse)
def get_deduction_items(
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("bonus")),
    status_filter: Annotated[str | None, Query(alias="status", max_length=8)] = None,
    person: Annotated[str | None, Query(max_length=30)] = None,
    kind: Annotated[str | None, Query(max_length=16)] = None,
    period: Annotated[str | None, Query(min_length=6, max_length=6)] = None,
) -> ApiResponse:
    require_operations_user(access, _READ_MESSAGE)
    items = deduction_items.list_items(db, status=status_filter, person=person, kind=kind, period=period)
    return _ok("조회 완료", {"items": items, "pending": deduction_items.pending_summary(db)})


@router.get("/deduction-items/export.xlsx", response_model=None)
def export_deduction_items(
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("bonus")),
    status_filter: Annotated[str | None, Query(alias="status", max_length=8)] = None,
    person: Annotated[str | None, Query(max_length=30)] = None,
    kind: Annotated[str | None, Query(max_length=16)] = None,
    period: Annotated[str | None, Query(min_length=6, max_length=6)] = None,
) -> Response:
    require_operations_user(access, _READ_MESSAGE)
    rows = [
        {**item, "status": _STATUS_LABEL.get(item["status"], item["status"]), "source": _SOURCE_LABEL.get(item["source"], item["source"])}
        for item in deduction_items.list_items(db, status=status_filter, person=person, kind=kind, period=period)
    ]
    content = build_xlsx("공제대장", _DEDUCTION_COLUMNS, rows)
    return Response(content=content, media_type=XLSX_MEDIA_TYPE, headers=xlsx_headers("상여_공제대장"))


@router.post("/deduction-items", response_model=ApiResponse)
def post_deduction_item(
    request: DeductionItemRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu_write("bonus")),
) -> ApiResponse | JSONResponse:
    require_same_requester(access, request.requester_usr_seq)
    require_operations_user(access, _WRITE_MESSAGE)
    if request.apply_period and (bad := _bad_period(request.apply_period)) is not None:
        return bad
    try:
        item = deduction_items.create_item(
            db, request.model_dump(exclude={"requester_usr_seq", "apply_period"}),
            usr_seq=request.requester_usr_seq, apply_period=request.apply_period,
        )
    except BonusMasterError as exc:
        return _error(status.HTTP_400_BAD_REQUEST, "INPUT_INVALID", str(exc))
    return _ok("공제 항목을 등록했습니다.", {"item": item})


@router.put("/deduction-items/{item_id}", response_model=ApiResponse)
def put_deduction_item(
    item_id: int,
    request: DeductionItemUpdateRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu_write("bonus")),
) -> ApiResponse | JSONResponse:
    require_same_requester(access, request.requester_usr_seq)
    require_operations_user(access, _WRITE_MESSAGE)
    try:
        item = deduction_items.update_item(
            db, item_id, request.model_dump(exclude={"requester_usr_seq"}, exclude_none=True), usr_seq=request.requester_usr_seq,
        )
    except BonusMasterError as exc:
        return _error(status.HTTP_400_BAD_REQUEST, "INPUT_INVALID", str(exc))
    return _ok("공제 항목을 고쳤습니다.", {"item": item})


@router.post("/deduction-items/{item_id}/void", response_model=ApiResponse)
def post_deduction_item_void(
    item_id: int,
    request: DeductionVoidRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu_write("bonus")),
) -> ApiResponse | JSONResponse:
    require_same_requester(access, request.requester_usr_seq)
    require_operations_user(access, _WRITE_MESSAGE)
    try:
        item = deduction_items.void_item(db, item_id, request.reason, usr_seq=request.requester_usr_seq)
    except BonusMasterError as exc:
        return _error(status.HTTP_400_BAD_REQUEST, "INPUT_INVALID", str(exc))
    return _ok("공제 항목을 무효 처리했습니다.", {"item": item})


@router.post("/deduction-items/{item_id}/split", response_model=ApiResponse)
def post_deduction_item_split(
    item_id: int,
    request: DeductionSplitRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu_write("bonus")),
) -> ApiResponse | JSONResponse:
    """대기 항목을 둘로 나눈다 — 부분 회수(이번 달엔 일부만 빼기). 잔액은 원본에 남는다."""
    require_same_requester(access, request.requester_usr_seq)
    require_operations_user(access, _WRITE_MESSAGE)
    try:
        result = deduction_items.split_item(db, item_id, request.amount, usr_seq=request.requester_usr_seq)
    except BonusMasterError as exc:
        return _error(status.HTTP_400_BAD_REQUEST, "INPUT_INVALID", str(exc))
    return _ok(
        f"{result['split']['amount']:,.0f}원을 떼어 새 대기 항목으로 만들었습니다 (잔액 {result['remainder']['amount']:,.0f}원).",
        result,
    )


@router.put("/overrides/{period}", response_model=ApiResponse)
def put_overrides(
    period: str,
    request: OverrideSaveRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu_write("bonus")),
) -> ApiResponse | JSONResponse:
    require_same_requester(access, request.requester_usr_seq)
    require_operations_user(access, _WRITE_MESSAGE)
    if (bad := _bad_period(period)) is not None:
        return bad
    if closing.close_status(db, period) == "CLOSED":
        return _error(status.HTTP_409_CONFLICT, "PERIOD_CLOSED", f"{period} 은 마감돼 있습니다 — 먼저 재개하세요.")
    try:
        actions = ledger.set_overrides(db, period, request.doc_id, request.person, request.actions, usr_seq=request.requester_usr_seq)
    except BonusMasterError as exc:
        return _error(status.HTTP_400_BAD_REQUEST, "INPUT_INVALID", str(exc))
    return _ok("오버라이드를 저장했습니다.", {"period": period, "doc_id": request.doc_id, "person": request.person, "actions": actions})


@router.post("/close/{period}", response_model=ApiResponse)
def post_close(
    period: str,
    request: RequesterRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu_write("bonus")),
) -> ApiResponse | JSONResponse:
    require_same_requester(access, request.requester_usr_seq)
    require_operations_user(access, _WRITE_MESSAGE)
    if (bad := _bad_period(period)) is not None:
        return bad
    if closing.close_status(db, period) == "CLOSED":
        return _error(status.HTTP_409_CONFLICT, "PERIOD_CLOSED", f"{period} 은 이미 마감돼 있습니다.")
    report = bonus_report_v2(db, period)
    try:
        result = closing.close_period(db, period, report, usr_seq=request.requester_usr_seq)
    except BonusMasterError as exc:
        return _error(status.HTTP_400_BAD_REQUEST, "CLOSE_INVALID", str(exc))
    return _ok(f"{period} 지급분을 마감했습니다 ({result['rows']}행).", result)


@router.post("/reopen/{period}", response_model=ApiResponse)
def post_reopen(
    period: str,
    request: RequesterRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu_write("bonus")),
) -> ApiResponse | JSONResponse:
    require_same_requester(access, request.requester_usr_seq)
    require_operations_user(access, _WRITE_MESSAGE)
    if (bad := _bad_period(period)) is not None:
        return bad
    try:
        result = closing.reopen_period(db, period, usr_seq=request.requester_usr_seq)
    except BonusMasterError as exc:
        return _error(status.HTTP_400_BAD_REQUEST, "REOPEN_INVALID", str(exc))
    return _ok(f"{period} 지급분 마감을 재개했습니다.", result)
