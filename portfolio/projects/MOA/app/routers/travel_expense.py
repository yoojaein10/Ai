"""출장비 API (2026-09-10) — 출장비 화면(/desktop/travel-expense)이 쓴다.

본사 직원만(travelExpense 메뉴 + 본사 소속). 작성자 이름은 로그인 사용자의 이름(emp_name)이라
델파이가 UserInfo.UserName 으로 적던 Write_Name 과 같은 값이 들어간다.
"""

from datetime import date
from io import BytesIO
from typing import Literal

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import AccessContext, require_menu, require_menu_write, require_same_requester
from app.schemas.common import ApiResponse
from app.services import travel_expense as te

router = APIRouter(prefix="/api/travel-expense", tags=["travel-expense"])
_MESSAGE = "출장비는 본사 직원만 쓸 수 있습니다."


def _error(code: str, message: str, http: int = status.HTTP_400_BAD_REQUEST) -> JSONResponse:
    body = ApiResponse(success=False, code=code, message=message, data=None)
    return JSONResponse(status_code=http, content=body.model_dump(mode="json"))


def _who(access: AccessContext) -> "tuple[str, int | None]":
    """(작성자 이름, 결재 등급). 본사가 아니면 403."""
    if str(access.get("office_id") or "").strip() != te.HEAD_OFFICE:
        from app.dependencies import _deny
        _deny("OFFICE_SCOPE_DENIED", _MESSAGE)
    return str(access.get("emp_name") or "").strip(), None


class SaveRequest(BaseModel):
    requester_usr_seq: int
    seq: int = 0
    doc_id: str = Field(min_length=1, max_length=30)
    cul_date: str = Field(min_length=10, max_length=10)
    cul_in: int = 0
    cul_out: int = 0
    regis_copy: int = 0
    toji_use: int = 0
    toji_dae: int = 0
    build_dae: int = 0
    jijuck: int = 0
    mul_remark: str = Field(default="", max_length=30)
    mul_amt: int = 0
    yebi: int = 0
    muljosabi: int = 0
    tojosabi: int = 0
    gongbu: int = 0
    silbi: int = 0
    yongyeuk: int = 0
    bigo: str = Field(default="", max_length=200)


class DeleteRequest(BaseModel):
    requester_usr_seq: int
    seq: int
    doc_id: str = Field(min_length=1, max_length=30)


class Target(BaseModel):
    seq: int
    doc_id: str = Field(min_length=1, max_length=30)


class ApproveRequest(BaseModel):
    requester_usr_seq: int
    action: Literal["submit", "approve", "reject"]
    targets: list[Target] = Field(min_length=1, max_length=500)
    bigo: str = Field(default="", max_length=250)


@router.get("/me", response_model=ApiResponse)
def me(db: Session = Depends(get_db), access: AccessContext = Depends(require_menu("travelExpense"))) -> ApiResponse:
    name, _ = _who(access)
    grade = te.approver_grade(db, name)
    return ApiResponse(success=True, code="0000", message="확인", data={
        "name": name, "grade": grade, "is_approver": grade is not None,
        "months": te.month_options(), "current_month": te.month_key(date.today()),
        "state_labels": te.STATE_LABELS, "ratios": list(te.RATIOS),
    })


@router.get("/my-docs", response_model=ApiResponse)
def my_docs(db: Session = Depends(get_db), access: AccessContext = Depends(require_menu("travelExpense"))) -> ApiResponse:
    name, _ = _who(access)
    items = te.my_docs(db, name)
    return ApiResponse(success=True, code="0000", message=f"{len(items)}건", data={"items": items})


@router.get("/draft", response_model=ApiResponse)
def draft(
    doc_id: str, seq: int = 0,
    db: Session = Depends(get_db), access: AccessContext = Depends(require_menu("travelExpense")),
) -> ApiResponse | JSONResponse:
    _who(access)
    try:
        data = te.draft(db, doc_id, seq)
    except te.TravelExpenseError as exc:
        return _error("BAD_REQUEST", str(exc))
    return ApiResponse(success=True, code="0000", message="확인", data=data)


@router.post("/save", response_model=ApiResponse)
def save(
    request: SaveRequest,
    db: Session = Depends(get_db), access: AccessContext = Depends(require_menu_write("travelExpense")),
) -> ApiResponse | JSONResponse:
    require_same_requester(access, request.requester_usr_seq)
    name, _ = _who(access)
    try:
        data = te.save(db, name, request.model_dump(exclude={"requester_usr_seq"}))
    except te.TravelExpenseError as exc:
        return _error("BAD_REQUEST", str(exc))
    return ApiResponse(success=True, code="0000", message="저장 완료", data=data)


@router.post("/delete", response_model=ApiResponse)
def delete(
    request: DeleteRequest,
    db: Session = Depends(get_db), access: AccessContext = Depends(require_menu_write("travelExpense")),
) -> ApiResponse | JSONResponse:
    require_same_requester(access, request.requester_usr_seq)
    name, _ = _who(access)
    try:
        te.delete(db, name, request.seq, request.doc_id)
    except te.TravelExpenseError as exc:
        return _error("BAD_REQUEST", str(exc))
    return ApiResponse(success=True, code="0000", message="삭제 완료", data=None)


def _list_args(db: Session, access: AccessContext, **kw) -> "dict":
    name, _ = _who(access)
    grade = te.approver_grade(db, name)
    return {"viewer": name, "is_approver": grade is not None, **kw}


@router.get("/list", response_model=ApiResponse)
def list_rows(
    bungi: str = "", emp: str = "", doc_id: str = "", state: int | None = None,
    date_kind: Literal["", "cul", "receipt", "send"] = "", date_from: date | None = None, date_to: date | None = None,
    db: Session = Depends(get_db), access: AccessContext = Depends(require_menu("travelExpense")),
) -> ApiResponse | JSONResponse:
    try:
        args = _list_args(db, access, bungi=bungi, emp=emp, doc_id=doc_id, state=state,
                          date_kind=date_kind, date_from=date_from, date_to=date_to)
        rows = te.list_rows(db, **args)
    except te.TravelExpenseError as exc:
        return _error("BAD_REQUEST", str(exc))
    name = args["viewer"]
    return ApiResponse(success=True, code="0000", message=f"{len(rows)}건", data={
        "items": rows, "summary": te.summarize(rows), "is_approver": args["is_approver"],
        "grade": te.approver_grade(db, name), "name": name,
        "writers": te.writers(db, bungi) if bungi and args["is_approver"] else [],
    })


@router.get("/export.xlsx", include_in_schema=False)
def export(
    bungi: str = "", emp: str = "", doc_id: str = "", state: int | None = None,
    date_kind: Literal["", "cul", "receipt", "send"] = "", date_from: date | None = None, date_to: date | None = None,
    db: Session = Depends(get_db), access: AccessContext = Depends(require_menu("travelExpense")),
) -> Response:
    from openpyxl import Workbook

    args = _list_args(db, access, bungi=bungi, emp=emp, doc_id=doc_id, state=state,
                      date_kind=date_kind, date_from=date_from, date_to=date_to)
    rows = te.list_rows(db, **args)
    wb = Workbook(); ws = wb.active; ws.title = "출장비"
    header = ["작성자", "결재상태", "접수일자", "출장일자", "감정서번호", "진행상태", "담당평가사", "출장지", "발송일",
              "시내", "시외", "출장비소계", "등기부등본", "토지이용", "토지대장", "건축물", "지적/교통", "물건내역", "물건비용",
              "공부소계", "합계", "여비", "물건조사비", "토지조사비", "공부발급", "기타실비", "특별용역비", "여비합계", "비고"]
    ws.append(header)
    for r in rows:
        ws.append([r["write_name"], r["state_label"], r["receipt_date"], r["cul_date"], r["doc_id"], r["status"], r["manager"],
                   r["address"], r["send_date"], r["cul_in"], r["cul_out"], r["cul_total"], r["regis_copy"], r["toji_use"],
                   r["toji_dae"], r["build_dae"], r["jijuck"], r["mul_remark"], r["mul_amt"], r["gong_total"], r["amount_total"],
                   r["yebi"], r["muljosabi"], r["tojosabi"], r["gongbu"], r["silbi"], r["yongyeuk"], r["bill_total"],
                   " / ".join(s for s in (r["bigo"], r.get("check_note") or "") if s)])
    buf = BytesIO(); wb.save(buf)
    stamp = bungi or date.today().isoformat()
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="travel_expense_{stamp}.xlsx"'},
    )


@router.get("/print", response_model=ApiResponse)
def print_bundle(
    bungi: str = "", emp: str = "", doc_id: str = "", state: int | None = None,
    date_kind: Literal["", "cul", "receipt", "send"] = "", date_from: date | None = None, date_to: date | None = None,
    db: Session = Depends(get_db), access: AccessContext = Depends(require_menu("travelExpense")),
) -> ApiResponse | JSONResponse:
    """작성자별 청구서 인쇄 자료 — 델파이 CulJangList 양식과 같은 묶음(행·합계·비고·한글 금액·직급·결재란)."""
    try:
        args = _list_args(db, access, bungi=bungi, emp=emp, doc_id=doc_id, state=state,
                          date_kind=date_kind, date_from=date_from, date_to=date_to)
        rows = te.list_rows(db, **args)
        data = te.print_data(db, rows)
    except te.TravelExpenseError as exc:
        return _error("BAD_REQUEST", str(exc))
    return ApiResponse(success=True, code="0000", message=f"{len(data['writers'])}명", data=data)


@router.get("/print-summary", response_model=ApiResponse)
def print_summary(
    bungi: str = "", emp: str = "", doc_id: str = "", state: int | None = None,
    date_kind: Literal["", "cul", "receipt", "send"] = "", date_from: date | None = None, date_to: date | None = None,
    db: Session = Depends(get_db), access: AccessContext = Depends(require_menu("travelExpense")),
) -> ApiResponse | JSONResponse:
    """총괄표 — 작성자별 시내·시외·공부발급비·계와 합계. 명단은 최근 6개월 작성자(그 달에 없으면 '-')."""
    try:
        args = _list_args(db, access, bungi=bungi, emp=emp, doc_id=doc_id, state=state,
                          date_kind=date_kind, date_from=date_from, date_to=date_to)
        rows = te.list_rows(db, **args)
        roster = te.recent_writers(db, bungi) if (bungi and not date_kind and args["is_approver"] and not emp) else []
        data = te.summary_sheet(rows, roster, te.summary_title(bungi, date_kind, date_from, date_to))
    except te.TravelExpenseError as exc:
        return _error("BAD_REQUEST", str(exc))
    return ApiResponse(success=True, code="0000", message=f"{len(data['items'])}명", data=data)


@router.post("/approve", response_model=ApiResponse)
def approve(
    request: ApproveRequest,
    db: Session = Depends(get_db), access: AccessContext = Depends(require_menu_write("travelExpense")),
) -> ApiResponse | JSONResponse:
    require_same_requester(access, request.requester_usr_seq)
    name, _ = _who(access)
    grade = te.approver_grade(db, name)
    try:
        data = te.approve(db, name=name, grade=grade, action=request.action,
                          targets=[t.model_dump() for t in request.targets], bigo=request.bigo)
    except te.TravelExpenseError as exc:
        return _error("BAD_REQUEST", str(exc))
    label = {"submit": "제출", "approve": "결재", "reject": "반려"}[request.action]
    message = f"{label} {len(data['done'])}건" + (f" · 건너뜀 {len(data['skipped'])}건" if data["skipped"] else "")
    return ApiResponse(success=True, code="0000", message=message, data=data)


@router.get("/months", response_model=ApiResponse)
def months(db: Session = Depends(get_db), access: AccessContext = Depends(require_menu("travelExpense"))) -> ApiResponse:
    name, _ = _who(access)
    is_approver = te.approver_grade(db, name) is not None
    return ApiResponse(success=True, code="0000", message="확인", data={"items": te.months(db, name, is_approver)})
