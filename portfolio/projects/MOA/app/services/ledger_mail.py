"""계정별원장 메일 — 지사 담당자 명단과 발송 로그 (2026-08-24).

담당자는 계정(지사)마다 여럿일 수 있다. 받는사람(TO)이 하나도 없는 계정은
**보내지 않는다**(fail-closed) — 빈 주소로 보내다 엉뚱한 데 나가는 것보다 낫다.

발송은 성공·실패를 모두 로그에 남긴다. 실패만 조용히 사라지면 안 보낸 지사를
보낸 줄 안다.
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ledger_mail_log import LedgerMailLog
from app.models.ledger_recipient import LedgerRecipient

KINDS = ("TO", "CC")


def _row(row: LedgerRecipient) -> "dict[str, Any]":
    return {
        "recipient_id": row.recipient_id,
        "account_code": row.account_code,
        "office_id": row.office_id,
        "name": row.name or "",
        "email": row.email,
        "kind": row.kind,
        "memo": row.memo or "",
    }


def list_recipients(db: Session, account_code: "str | None" = None) -> "list[dict[str, Any]]":
    """살아 있는 담당자. account_code 를 주면 그 계정만."""
    query = select(LedgerRecipient).where(LedgerRecipient.active == "Y")
    if account_code:
        query = query.where(LedgerRecipient.account_code == account_code)
    rows = db.scalars(
        query.order_by(
            LedgerRecipient.account_code, LedgerRecipient.kind, LedgerRecipient.recipient_id
        )
    ).all()
    return [_row(row) for row in rows]


def addresses_for(db: Session, account_code: str) -> "dict[str, list[str]]":
    """그 계정의 받는사람·참조 주소. 메일 헤더에 그대로 넣는 값이다."""
    people = list_recipients(db, account_code)
    return {
        "to": [p["email"] for p in people if p["kind"] == "TO"],
        "cc": [p["email"] for p in people if p["kind"] == "CC"],
    }


def save_recipients(
    db: Session,
    account_code: str,
    people: "list[dict[str, Any]]",
    usr_seq: "int | None" = None,
    office_id: "str | None" = None,
) -> "list[dict[str, Any]]":
    """그 계정의 담당자를 넘어온 목록 **그대로** 맞춘다.

    빠진 사람은 지우지 않고 active='N' 으로 둔다 — 누가 언제 빠졌는지 남는다.
    """
    incoming = [
        {
            "email": str(person.get("email", "")).strip(),
            "name": (str(person.get("name") or "")).strip() or None,
            "kind": str(person.get("kind") or "TO").upper(),
            "memo": (str(person.get("memo") or "")).strip() or None,
        }
        for person in people
    ]
    incoming = [p for p in incoming if p["email"]]
    for person in incoming:
        if person["kind"] not in KINDS:
            person["kind"] = "TO"

    current = db.scalars(
        select(LedgerRecipient).where(
            LedgerRecipient.account_code == account_code, LedgerRecipient.active == "Y"
        )
    ).all()
    by_email = {row.email.lower(): row for row in current}
    kept: set[str] = set()

    for person in incoming:
        key = person["email"].lower()
        if key in kept:
            continue          # 같은 주소를 두 번 적으면 메일이 두 통 간다
        kept.add(key)
        row = by_email.get(key)
        if row is None:
            db.add(
                LedgerRecipient(
                    account_code=account_code, office_id=office_id,
                    name=person["name"], email=person["email"], kind=person["kind"],
                    memo=person["memo"], active="Y", updated_by_usr_seq=usr_seq,
                )
            )
            continue
        row.name = person["name"]
        row.kind = person["kind"]
        row.memo = person["memo"]
        if office_id:
            row.office_id = office_id
        row.updated_by_usr_seq = usr_seq

    for email, row in by_email.items():
        if email not in kept:
            row.active = "N"
            row.updated_by_usr_seq = usr_seq

    db.commit()
    return list_recipients(db, account_code)


def log_mail(
    db: Session,
    account_code: str,
    account_name: str,
    date_from: date,
    date_to: date,
    status: str,
    to_email: str = "",
    cc_email: str = "",
    subject: str = "",
    fail_reason: str = "",
    test_mode: bool = False,
    item_count: int = 0,
    closing_balance: "float | None" = None,
    requested_by_usr_seq: "int | None" = None,
) -> None:
    """한 통을 로그에 남긴다. 로그 때문에 발송이 죽으면 안 되므로 부르는 쪽에서 감싼다."""
    db.add(
        LedgerMailLog(
            account_code=account_code, account_name=account_name[:60] or None,
            date_from=date_from, date_to=date_to,
            to_email=(to_email or None), cc_email=(cc_email or None),
            subject=(subject[:300] or None), status=status,
            fail_reason=(fail_reason[:400] or None),
            test_mode="Y" if test_mode else "N",
            item_count=item_count, closing_balance=closing_balance,
            requested_by_usr_seq=requested_by_usr_seq,
        )
    )
    db.commit()


def list_logs(
    db: Session,
    date_from: "date | None" = None,
    date_to: "date | None" = None,
    account_code: "str | None" = None,
    limit: int = 200,
) -> "list[dict[str, Any]]":
    """보낸 기록. 기간은 **보낸 날**(sent_at) 기준이다 — '어제 보냈나' 를 묻기 때문."""
    query = select(LedgerMailLog)
    if date_from:
        query = query.where(LedgerMailLog.sent_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        query = query.where(LedgerMailLog.sent_at < datetime.combine(date_to, datetime.max.time()))
    if account_code:
        query = query.where(LedgerMailLog.account_code == account_code)
    rows = db.scalars(query.order_by(LedgerMailLog.log_id.desc()).limit(limit)).all()
    return [
        {
            "log_id": row.log_id,
            "sent_at": row.sent_at.isoformat(sep=" ", timespec="seconds"),
            "account_code": row.account_code,
            "account_name": row.account_name or "",
            "period": {"from": row.date_from.isoformat(), "to": row.date_to.isoformat()},
            "to_email": row.to_email or "",
            "cc_email": row.cc_email or "",
            "subject": row.subject or "",
            "status": row.status,
            "fail_reason": row.fail_reason or "",
            "test_mode": row.test_mode == "Y",
            "item_count": int(row.item_count or 0),
            "closing_balance": float(row.closing_balance) if row.closing_balance is not None else None,
            "requested_by_usr_seq": row.requested_by_usr_seq,
        }
        for row in rows
    ]
