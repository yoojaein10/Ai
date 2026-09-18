"""사람 파라미터(a10_bonus_person) 조회·저장.

save_persons 는 ledger_mail.save_recipients 와 같은 replace-all: 넘어온 목록이 현재
상태고, 빠진 사람은 active='N' 으로 남긴다. 값 검사는 DB 를 건드리기 전에 끝낸다 —
절반만 저장되면 화면이 잘못된 상태를 맞는다.
"""

from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.bonus_person import BonusPerson
from app.services.bonus.schedule import BonusMasterError

KINDS = ("SHAREHOLDER", "ASSOCIATE")
DEFAULT_TAX_RATE = {"SHAREHOLDER": Decimal("0.30"), "ASSOCIATE": Decimal("0.15")}


def _row(person: BonusPerson) -> "dict[str, Any]":
    return {
        "person": person.person,
        "kind": person.kind,
        "pay_ratio": float(person.pay_ratio),
        "tax_rate": float(person.tax_rate),
        "common_rate": float(person.common_rate) if person.common_rate is not None else None,
        "memo": person.memo,
    }


def _decimal(value: Any, name: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise BonusMasterError(f"{name} 값이 숫자가 아닙니다: {value!r}") from exc


def _clean(rows: "list[dict[str, Any]]") -> "dict[str, dict[str, Any]]":
    """검증된 입력을 사람 이름 순서대로 — 같은 이름이 두 번이면 앞의 것."""
    incoming: "dict[str, dict[str, Any]]" = {}
    for raw in rows:
        name = str(raw.get("person") or "").strip()
        if not name:
            raise BonusMasterError("이름이 비어 있습니다.")
        kind = str(raw.get("kind") or "").strip().upper()
        if kind not in KINDS:
            raise BonusMasterError(f"{name}: 구분은 주주(SHAREHOLDER)/소속(ASSOCIATE)만 됩니다: {raw.get('kind')!r}")
        pay_ratio = _decimal(raw.get("pay_ratio") if raw.get("pay_ratio") is not None else 1, f"{name} 지급률")
        if not (0 < pay_ratio <= 1):
            raise BonusMasterError(f"{name}: 지급률은 0 초과 1 이하여야 합니다: {pay_ratio}")
        tax_rate = (
            _decimal(raw.get("tax_rate"), f"{name} 소득세율")
            if raw.get("tax_rate") is not None else DEFAULT_TAX_RATE[kind]
        )
        if not (0 <= tax_rate < 1):
            raise BonusMasterError(f"{name}: 소득세율은 0 이상 1 미만이어야 합니다: {tax_rate}")
        common_rate = None
        if raw.get("common_rate") not in (None, ""):
            common_rate = _decimal(raw.get("common_rate"), f"{name} 공통건 요율")
            if not (0 < common_rate <= 100):
                raise BonusMasterError(f"{name}: 공통건 요율은 0 초과 100 이하(%)여야 합니다: {common_rate}")
        if name in incoming:
            continue
        incoming[name] = {
            "kind": kind, "pay_ratio": pay_ratio, "tax_rate": tax_rate, "common_rate": common_rate,
            "memo": (str(raw.get("memo") or "").strip() or None),
        }
    return incoming


def list_persons(db: Session) -> "list[dict[str, Any]]":
    rows = db.scalars(
        select(BonusPerson).where(BonusPerson.active == "Y").order_by(BonusPerson.person)
    ).all()
    return [_row(row) for row in rows]


def save_persons(
    db: Session, rows: "list[dict[str, Any]]", usr_seq: "int | None" = None
) -> "list[dict[str, Any]]":
    incoming = _clean(rows)
    current = {row.person: row for row in db.scalars(select(BonusPerson)).all()}
    for name, values in incoming.items():
        row = current.get(name)
        if row is None:
            db.add(BonusPerson(person=name, active="Y", updated_by_usr_seq=usr_seq, **values))
            continue
        row.kind, row.pay_ratio, row.tax_rate, row.common_rate, row.memo = (
            values["kind"], values["pay_ratio"], values["tax_rate"], values["common_rate"], values["memo"]
        )
        row.active = "Y"
        row.updated_by_usr_seq = usr_seq
    for name, row in current.items():
        if name not in incoming and row.active == "Y":
            row.active = "N"  # 지우지 않는다 — 누가 언제 뺐는지 남는다
            row.updated_by_usr_seq = usr_seq
    db.commit()
    return list_persons(db)
