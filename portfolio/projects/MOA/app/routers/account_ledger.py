"""계정별원장 API — 조회·미리보기·메일 발송 (본사 전용).

지사 계정 원장을 뽑아 지사 담당자에게 메일로 보낸다. 지금은 출력해 팩스로 보낸다
(2026-08-21 사용자 요청).

메일은 fail-closed 다 — SMTP 설정이 없으면 안 보낸다. 지사 주소가 정리되기 전이라
LEDGER_MAIL_TEST_TO 가 있으면 누구에게 보내든 그 주소로만 간다.

받는 사람은 **지사별 담당자 표**(a10_ledger_recipient)에서 읽는다 — 계정마다 여럿일
수 있고, 사람이 바뀌면 표만 고친다. 보낸 것은 성공·실패 모두
a10_ledger_mail_log 에 남는다 (2026-08-24).

그 해 전기이월(a10_account_opening)이 없는 계정은 **보내지 않는다.** 없으면
전일이월이 0 에서 시작해 원장이 통째로 틀리는데 화면에는 아무 표시도 없다
(2026-08-24). 새해 이월은 scripts/roll_account_opening.py 가 만든다.
"""

import logging
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import AccessContext, require_menu, require_operations_user
from app.schemas.common import ApiResponse
from app.services.account_ledger import build_ledger, list_accounts, render_html
from app.services.ledger_mail import (
    addresses_for, list_logs, list_recipients, log_mail, save_recipients,
)
from app.services.mailer import MailError, send_html_mail

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/account-ledger", tags=["account-ledger"])

_ACCOUNT = Annotated[str, StringConstraints(pattern=r"^\d{7}$")]


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    response = ApiResponse(success=False, code=code, message=message, data=None)
    return JSONResponse(status_code=status_code, content=response.model_dump(mode="json"))


def _log(db: Session, **fields) -> int:
    """로그 한 줄. 이미 나간 메일을 로그 실패로 되돌릴 수는 없으므로, 실패하면
    발송을 죽이는 대신 1을 돌려 결과 메시지에 몇 건 실패했는지 얹는다."""
    try:
        log_mail(db, **fields)
    except SQLAlchemyError as exc:      # 표가 없거나 연결이 끊긴 경우
        db.rollback()
        logger.exception("계정별원장 발송 로그 기록 실패: %s", exc)
        return 1
    return 0


class SendRequest(BaseModel):
    requester_usr_seq: int
    date_from: date
    date_to: date
    accounts: list[_ACCOUNT] = Field(min_length=1, max_length=30)
    # 비우면 지사별 담당자 표에서 읽는다. 넣으면 그 주소로만 간다(한 번 쓰는 덮어쓰기).
    to: str = ""


class RecipientItem(BaseModel):
    name: str = ""
    email: str = Field(min_length=3, max_length=200)
    kind: Literal["TO", "CC"] = "TO"
    memo: str = ""


class RecipientSaveRequest(BaseModel):
    requester_usr_seq: int
    office_id: str = ""
    # 넘어온 목록 **그대로** 맞춘다 — 빠진 사람은 빠진 것으로 본다(빈 목록이면 전부).
    people: list[RecipientItem] = Field(default_factory=list, max_length=20)


@router.get("/accounts", response_model=ApiResponse)
def get_accounts(
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("accountLedger")),
) -> ApiResponse:
    require_operations_user(access, "계정별원장은 본사 재무팀·집행부만 볼 수 있습니다.")
    return ApiResponse(
        success=True, code="0000", message="조회 완료",
        data={"items": list_accounts(db)},
    )


@router.get("", response_model=ApiResponse)
def get_ledger(
    account_code: _ACCOUNT,
    date_from: date,
    date_to: date,
    carry_from: date | None = None,
    fmt: Literal["json", "html"] = "json",
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("accountLedger")),
) -> ApiResponse:
    require_operations_user(access, "계정별원장은 본사 재무팀·집행부만 볼 수 있습니다.")
    ledger = build_ledger(db, account_code, date_from, date_to, carry_from=carry_from)
    if fmt == "html":
        ledger["html"] = render_html(ledger)
    return ApiResponse(success=True, code="0000", message="조회 완료", data=ledger)


@router.post("/send", response_model=ApiResponse)
def post_send(
    request: SendRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("accountLedger")),
) -> ApiResponse | JSONResponse:
    """고른 계정의 원장을 메일로 보낸다 — 계정 하나에 한 통.

    받는 사람은 지사별 담당자 표에서 읽는다. request.to 를 넣으면 그 주소로만 간다.
    성공·실패를 모두 로그에 남긴다 — 안 보낸 지사를 보낸 줄 알면 안 된다.
    """
    require_operations_user(access, "계정별원장 발송은 본사 재무팀·집행부만 가능합니다.")
    override = request.to.strip()
    sent: list[dict] = []
    failed: list[dict] = []
    log_failed = 0
    for account_code in request.accounts:
        ledger = build_ledger(db, account_code, request.date_from, request.date_to)
        addresses = (
            {"to": [override], "cc": []} if override else addresses_for(db, account_code)
        )
        subject = (
            f"[계정별원장] {ledger['account_code']}.{ledger['account_name']} "
            f"{request.date_from} ~ {request.date_to}"
        )
        # 원장을 무엇으로 보냈는지 나중에 대조할 요약 — 본문은 안 남긴다.
        balance = (
            ledger["items"][-1]["balance"] if ledger["items"] else ledger["carry"]["balance"]
        )
        common = {
            "account_code": account_code, "account_name": ledger["account_name"],
            "date_from": request.date_from, "date_to": request.date_to,
            "subject": subject, "item_count": len(ledger["items"]),
            "closing_balance": balance,
            "requested_by_usr_seq": request.requester_usr_seq,
        }
        # 그 해 전기이월이 없으면 전일이월이 통째로 틀린 원장이 나간다. 화면에는
        # 아무 표시도 없어 아무도 모른다 — 그래서 보내지 않는다(fail-closed).
        if not ledger["opening"]["known"]:
            reason = (f"{ledger['carry_from'][:4]}년 전기이월이 없습니다 — "
                      "전일이월이 틀립니다. scripts/roll_account_opening.py 로 채우세요.")
            failed.append({
                "account_code": account_code,
                "account_name": ledger["account_name"],
                "reason": reason,
            })
            log_failed += _log(
                db, **common, status="FAILED",
                to_email=", ".join(addresses["to"]), cc_email=", ".join(addresses["cc"]),
                fail_reason=reason,
            )
            continue
        try:
            result = send_html_mail(
                addresses["to"], subject, render_html(ledger), cc=addresses["cc"]
            )
        except MailError as exc:
            reason = str(exc)
            if not addresses["to"]:
                reason = "담당자가 없습니다 — 담당자 관리에서 주소를 넣어 주세요."
            failed.append({
                "account_code": account_code,
                "account_name": ledger["account_name"],
                "reason": reason,
            })
            log_failed += _log(
                db, **common, status="FAILED",
                to_email=", ".join(addresses["to"]), cc_email=", ".join(addresses["cc"]),
                fail_reason=reason,
            )
            continue
        sent.append({
            "account_code": account_code,
            "account_name": ledger["account_name"],
            "to": result["to"],
            "cc": result["cc"],
            "test_mode": result["test_mode"],
        })
        log_failed += _log(
            db, **common, status="SENT",
            to_email=result["to"], cc_email=result["cc"], test_mode=result["test_mode"],
        )
    if not sent and failed:
        return _error(
            status.HTTP_400_BAD_REQUEST, "MAIL_FAILED", failed[0]["reason"]
        )
    note = ""
    if sent and sent[0]["test_mode"]:
        note = f" (테스트 수신자 {sent[0]['to']} 로만 보냈습니다)"
    if failed:
        note += f" · 실패 {len(failed)}건"
    if log_failed:
        note += f" · 로그 기록 실패 {log_failed}건"
    return ApiResponse(
        success=True, code="0000",
        message=f"{len(sent)}건을 보냈습니다.{note}",
        data={"sent": sent, "failed": failed},
    )


@router.get("/recipients", response_model=ApiResponse)
def get_recipients(
    account_code: _ACCOUNT | None = None,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("accountLedger")),
) -> ApiResponse:
    """지사별 담당자 명단."""
    require_operations_user(access, "계정별원장은 본사 재무팀·집행부만 볼 수 있습니다.")
    return ApiResponse(
        success=True, code="0000", message="조회 완료",
        data={"items": list_recipients(db, account_code)},
    )


@router.put("/recipients/{account_code}", response_model=ApiResponse)
def put_recipients(
    account_code: _ACCOUNT,
    request: RecipientSaveRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("accountLedger")),
) -> ApiResponse:
    """그 계정의 담당자를 넘어온 목록 그대로 맞춘다 — 빠진 사람은 뺀다."""
    require_operations_user(access, "담당자 변경은 본사 재무팀·집행부만 가능합니다.")
    people = save_recipients(
        db, account_code,
        [item.model_dump() for item in request.people],
        usr_seq=request.requester_usr_seq,
        office_id=request.office_id.strip() or None,
    )
    return ApiResponse(
        success=True, code="0000",
        message=f"담당자 {len(people)}명을 저장했습니다.",
        data={"items": people},
    )


@router.get("/logs", response_model=ApiResponse)
def get_logs(
    date_from: date | None = None,
    date_to: date | None = None,
    account_code: _ACCOUNT | None = None,
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("accountLedger")),
) -> ApiResponse:
    """보낸 기록 — 기간은 **보낸 날** 기준이다."""
    require_operations_user(access, "계정별원장은 본사 재무팀·집행부만 볼 수 있습니다.")
    return ApiResponse(
        success=True, code="0000", message="조회 완료",
        data={"items": list_logs(db, date_from, date_to, account_code, limit)},
    )
