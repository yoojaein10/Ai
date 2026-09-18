"""상여 설정 API — 사람 파라미터·요율 스케줄·감정서 지분 (본사 재무팀·집행부 전용).

상여 화면 안 '설정' 버튼으로 들어오는 딸림 화면이 쓴다. 권한 키는 상여(bonus)를
그대로 쓴다. 저장은 전부 replace-all — 넘어온 목록이 곧 현재 상태다.
"""

from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, status
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
)
from app.schemas.common import ApiResponse
from app.services.bonus import persons, schedule, shares, sources_apw
from app.services.bonus.schedule import BonusMasterError

router = APIRouter(prefix="/api/bonus/settings", tags=["bonus"])

_PERSON = Annotated[str, StringConstraints(min_length=1, max_length=30, strip_whitespace=True)]
_DOC = Annotated[str, StringConstraints(pattern=r"^[0-9A-Za-z\-]{5,50}$")]
_READ_MESSAGE = "상여 설정은 본사 재무팀·집행부만 볼 수 있습니다."
_WRITE_MESSAGE = "상여 설정 변경은 본사 재무팀·집행부만 가능합니다."


class PersonItem(BaseModel):
    person: _PERSON
    kind: Literal["SHAREHOLDER", "ASSOCIATE"]
    pay_ratio: float = Field(default=1.0, gt=0, le=1)
    tax_rate: float = Field(default=0.30, ge=0, lt=1)
    common_rate: float | None = Field(default=None, gt=0, le=100)   # 공통건 요율 % (비우면 규칙/기본 3)
    memo: str = Field(default="", max_length=200)


class PersonsSaveRequest(BaseModel):
    requester_usr_seq: int
    # 목록 **그대로** 맞춘다 — 빠진 사람은 빠진 것으로 본다.
    people: list[PersonItem] = Field(default_factory=list, max_length=300)


class RateItem(BaseModel):
    from_date: date | None = None
    to_date: date | None = None
    rate: float = Field(gt=0, le=100)
    label: str = Field(default="", max_length=100)


class RatesSaveRequest(BaseModel):
    requester_usr_seq: int
    rows: list[RateItem] = Field(default_factory=list, max_length=20)


class ShareItem(BaseModel):
    person: _PERSON
    share_pct: float = Field(gt=0, le=100)
    bc_pct: float | None = Field(default=None, gt=0, le=100)
    note: str = Field(default="", max_length=200)


class SharesSaveRequest(BaseModel):
    requester_usr_seq: int
    rows: list[ShareItem] = Field(default_factory=list, max_length=20)


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    response = ApiResponse(success=False, code=code, message=message, data=None)
    return JSONResponse(status_code=status_code, content=response.model_dump(mode="json"))


def _ok(message: str, data: "dict[str, Any]") -> ApiResponse:
    return ApiResponse(success=True, code="0000", message=message, data=data)


# ── 사람 ────────────────────────────────────────────────────────────────

@router.get("/persons", response_model=ApiResponse)
def get_persons(
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("bonus")),
) -> ApiResponse:
    require_operations_user(access, _READ_MESSAGE)
    return _ok("조회 완료", {"items": persons.list_persons(db)})


@router.put("/persons", response_model=ApiResponse)
def put_persons(
    request: PersonsSaveRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu_write("bonus")),
) -> ApiResponse | JSONResponse:
    require_same_requester(access, request.requester_usr_seq)
    require_operations_user(access, _WRITE_MESSAGE)
    try:
        items = persons.save_persons(
            db, [item.model_dump() for item in request.people], usr_seq=request.requester_usr_seq
        )
    except BonusMasterError as exc:
        return _error(status.HTTP_400_BAD_REQUEST, "MASTER_INVALID", str(exc))
    return _ok(f"{len(items)}명을 저장했습니다.", {"items": items})


# ── 요율 ────────────────────────────────────────────────────────────────

@router.get("/rates", response_model=ApiResponse)
def get_rates(
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("bonus")),
) -> ApiResponse:
    require_operations_user(access, _READ_MESSAGE)
    return _ok("조회 완료", {"items": schedule.list_rates(db)})


@router.put("/rates/{person}", response_model=ApiResponse)
def put_rates(
    person: _PERSON,
    request: RatesSaveRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu_write("bonus")),
) -> ApiResponse | JSONResponse:
    require_same_requester(access, request.requester_usr_seq)
    require_operations_user(access, _WRITE_MESSAGE)
    try:
        items = schedule.save_rates(
            db, person, [row.model_dump() for row in request.rows],
            usr_seq=request.requester_usr_seq, source="MANUAL",
        )
    except BonusMasterError as exc:
        return _error(status.HTTP_400_BAD_REQUEST, "MASTER_INVALID", str(exc))
    return _ok(f"{person}의 요율 {len(items)}구간을 저장했습니다.", {"person": person, "items": items})


# ── 지분 ────────────────────────────────────────────────────────────────

@router.get("/shares/lookup", response_model=ApiResponse)
def lookup_share(
    doc_id: Annotated[str, Query(min_length=5, max_length=50)],
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("bonus")),
) -> ApiResponse:
    """감정서 하나의 지분 근거 — APW 담당자·거래처, APW_Booking 지분, GaPrice 배분, 우리 지분표."""
    require_operations_user(access, _READ_MESSAGE)
    doc = doc_id.strip()
    meta = sources_apw.doc_meta(db, [doc]).get(doc)
    return _ok("조회 완료", {
        "doc_id": doc,
        "meta": meta and {"manager": meta["manager"], "customer_name": meta["customer_name"], "work_type": meta["work_type"],
                          "receipt_date": meta["receipt_date"], "fee": float(meta["base_fee"] or 0) - float(meta["cut_fee"] or 0)},
        "booking": sources_apw.booking_shares(db, [doc]).get(doc, {}),
        "gaprice": sources_apw.gaprice_allocations(db, [doc]).get(doc, {}),
        "manual": shares.list_shares(db, doc),
    })


@router.get("/shares", response_model=ApiResponse)
def get_shares(
    doc_id: _DOC | None = None,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("bonus")),
) -> ApiResponse:
    require_operations_user(access, _READ_MESSAGE)
    return _ok("조회 완료", {"items": shares.list_shares(db, doc_id)})


@router.put("/shares/{doc_id}", response_model=ApiResponse)
def put_shares(
    doc_id: _DOC,
    request: SharesSaveRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu_write("bonus")),
) -> ApiResponse | JSONResponse:
    require_same_requester(access, request.requester_usr_seq)
    require_operations_user(access, _WRITE_MESSAGE)
    try:
        saved = shares.save_shares(
            db, doc_id, [row.model_dump() for row in request.rows],
            usr_seq=request.requester_usr_seq, source="MANUAL",
        )
    except BonusMasterError as exc:
        return _error(status.HTTP_400_BAD_REQUEST, "MASTER_INVALID", str(exc))
    message = f"{doc_id} 지분 {len(saved['items'])}명을 저장했습니다."
    if saved["warning"]:
        message += f" (지분 합 {saved['total']:g}% — 100이 아닙니다)"
    return _ok(message, saved)
