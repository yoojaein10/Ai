"""성과상여 API (본사 전용 화면). 자동 계산 + 수기 보정(a10_bonus_adjust) 저장."""

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
    scoped_employee_name,
)
from app.schemas.common import ApiResponse
from app.services.bonus_legacy import (
    BonusAdjustError,
    bonus_report,
    save_person_adjustments,
)
from app.services.excel_export import XLSX_MEDIA_TYPE, build_xlsx, xlsx_headers
from app.services.users import UserContextError, UserContextService

router = APIRouter(prefix="/api/bonus", tags=["bonus"])


class FeeOverride(BaseModel):
    doc_id: str = Field(min_length=1, max_length=50)
    fee: float = Field(ge=0)


class AssessedOverride(BaseModel):
    doc_id: str = Field(min_length=1, max_length=50)
    assessed: float = Field(ge=0)


class ManualRow(BaseModel):
    doc_id: str | None = Field(default=None, max_length=50)
    work_type: str | None = Field(default=None, max_length=20)
    customer_name: str | None = Field(default=None, max_length=100)
    amount: float = Field(ge=0)  # 주주=산정금액, 평·동=순수수료
    memo: str | None = Field(default=None, max_length=200)


class Deduction(BaseModel):
    label: str = Field(min_length=1, max_length=30)
    amount: float


class DocRate(BaseModel):
    doc_id: str = Field(min_length=1, max_length=50)
    # 주주 40/45/35/30, 평·동 20 기본(구간 10~40)·공통건 3
    rate: Literal[3, 10, 15, 20, 25, 30, 35, 40, 45]


class FieldValue(BaseModel):
    doc_id: str = Field(min_length=1, max_length=50)
    label: Literal["가변비", "미납비이월", "감정서경비", "화환공제", "기타공제"]
    amount: float


class AdjustRequest(BaseModel):
    requester_usr_seq: int
    year: int = Field(ge=2020, le=2100)
    month: int = Field(ge=1, le=12)
    person: str = Field(min_length=1, max_length=30)
    fees: list[FeeOverride] = Field(default=[], max_length=200)
    assessed_overrides: list[AssessedOverride] = Field(default=[], max_length=200)
    rows: list[ManualRow] = Field(default=[], max_length=100)
    deductions: list[Deduction] = Field(default=[], max_length=30)
    doc_rates: list[DocRate] = Field(default=[], max_length=200)
    fields: list[FieldValue] = Field(default=[], max_length=10)


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
            status.HTTP_403_FORBIDDEN, "NOT_HEAD_OFFICE", "상여 보정은 본사만 가능합니다."
        )
    return None

_DOC_COLUMNS = [
    ("name", "귀속"), ("doc_id", "감정서번호"), ("work_type", "업무분류"),
    ("customer_name", "거래처"), ("manager", "담당자"), ("investigator", "조사자"),
    ("base_fee", "순수수료"), ("travel_fee", "부족출장비"),
    ("land_fee", "토지조사비"), ("assessed", "산정수수료"), ("indemnity", "손해배상충당금"),
    ("association_fee", "협회비공제료"), ("survey_fee", "물건조사비"),
    ("payout_base", "상여기준액"),
    ("rate", "적용률(%)"), ("bonus_amount", "상여액(공제 안분 후)"),
    ("paid_date", "입금일"),
]

_SUMMARY_COLUMNS = [
    ("kind", "구분"), ("name", "성명"), ("dept", "부서"), ("count", "건수"),
    ("base_fee", "순수수료 합계"), ("assessed", "산정금액 합계"),
    ("payout_base", "산출액"), ("bonus_ref", "상여 참고"),
]


@router.get("", response_model=ApiResponse)
def get_bonus(
    year: Annotated[int, Query(ge=2020, le=2100)],
    month: Annotated[int, Query(ge=1, le=12)],
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("bonus")),
) -> ApiResponse:
    data = bonus_report(db, year, month, scope_person=scoped_employee_name(access))
    return ApiResponse(success=True, code="0000", message="조회 완료", data=data)


@router.post("/adjust", response_model=ApiResponse)
def post_adjust(
    request: AdjustRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("bonus")),
) -> ApiResponse | JSONResponse:
    require_same_requester(access, request.requester_usr_seq)
    require_operations_user(access, "상여 보정은 본사 재무팀·집행부만 가능합니다.")
    try:
        count = save_person_adjustments(
            db,
            year=request.year, month=request.month, person=request.person,
            fees=[item.model_dump() for item in request.fees],
            assessed_overrides=[item.model_dump() for item in request.assessed_overrides],
            rows=[item.model_dump() for item in request.rows],
            deductions=[item.model_dump() for item in request.deductions],
            doc_rates=[item.model_dump() for item in request.doc_rates],
            created_by=request.requester_usr_seq,
            fields=[item.model_dump() for item in request.fields],
        )
    except BonusAdjustError as exc:
        return _error(status.HTTP_400_BAD_REQUEST, "ADJUST_FAILED", str(exc))
    return ApiResponse(
        success=True, code="0000",
        message=f"{request.person}의 보정 {count}건을 저장했습니다.", data={"count": count},
    )


def _flatten(groups: "list[dict[str, Any]]") -> "list[dict[str, Any]]":
    rows = []
    for group in groups:
        for doc in group["docs"]:
            rows.append({"name": group["name"], **doc})
    return rows


@router.get("/export.xlsx", response_model=None)
def export_bonus(
    year: Annotated[int, Query(ge=2020, le=2100)],
    month: Annotated[int, Query(ge=1, le=12)],
    tab: Literal["shareholders", "associates", "summary"] = "summary",
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("bonus")),
) -> Response:
    data = bonus_report(db, year, month, scope_person=scoped_employee_name(access))
    if tab == "summary":
        filename = f"상여총괄_{year}{month:02d}"
        content = build_xlsx(filename, _SUMMARY_COLUMNS, data["summary"])
    else:
        filename = (
            f"상여주주_{year}{month:02d}" if tab == "shareholders"
            else f"상여평동_{year}{month:02d}"
        )
        content = build_xlsx(filename, _DOC_COLUMNS, _flatten(data[tab]))
    return Response(
        content=content, media_type=XLSX_MEDIA_TYPE, headers=xlsx_headers(filename)
    )
