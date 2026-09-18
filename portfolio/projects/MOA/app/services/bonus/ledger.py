"""월 공제 원장·오버라이드 (a10_bonus_deduction · a10_bonus_override).

- deductions: {사람: [{item_id, kind, amount, doc_id, memo}]} — 공제 대장(deduction_items)에서 그 달에 적용된 것
- overrides:  {(감정서, 사람): {action: value}}       — INCLUDE/EXCLUDE 는 value 없음, WORK 는 업무분류 문자열
오버라이드 저장은 (달, 감정서, 사람) 단위 통째 교체. 값 검사는 DB 를 건드리기 전에 끝낸다.
"""

from typing import Any

from sqlalchemy import delete, select

from app.models.bonus_ledger import BonusDeduction, BonusOverride
from app.services.bonus.closing import _split
from app.services.bonus.rules import ALLOWED_RATES
from app.services.bonus.schedule import BonusMasterError

OVERRIDE_ACTIONS = ("INCLUDE", "EXCLUDE", "FEE", "RATE", "SHARE", "WORK")


def _check_period(period: str) -> None:
    try:
        _split(period)
    except ValueError as exc:
        raise BonusMasterError(str(exc)) from exc


def load_deductions(db, period: str) -> "dict[str, list[dict[str, Any]]]":
    """그 달에 적용된 공제 대장 항목 — 엔진 입력 모양 {사람: [{item_id, kind, amount, doc_id, memo}]}."""
    rows = db.scalars(
        select(BonusDeduction).where(BonusDeduction.applied_period == period, BonusDeduction.status == "APPLIED")
        .order_by(BonusDeduction.person, BonusDeduction.occurred_on, BonusDeduction.deduction_id)
    ).all()
    result: "dict[str, list[dict[str, Any]]]" = {}
    for row in rows:
        result.setdefault(row.person, []).append({
            "item_id": row.deduction_id, "kind": row.kind, "amount": float(row.amount or 0), "doc_id": row.doc_id, "memo": row.memo,
        })
    return result


def load_overrides(db, period: str) -> "dict[tuple[str, str], dict[str, Any]]":
    rows = db.scalars(select(BonusOverride).where(BonusOverride.period == period)).all()
    result: "dict[tuple[str, str], dict[str, Any]]" = {}
    for row in rows:
        value: Any = float(row.value) if row.value is not None else None
        if row.action == "WORK":
            value = row.memo
        result.setdefault((row.doc_id, row.person), {})[row.action] = value
    return result


def _clean_actions(doc: str, person: str, actions: "dict[str, Any]") -> "dict[str, Any]":
    cleaned: "dict[str, Any]" = {}
    for raw_action, value in actions.items():
        action = str(raw_action or "").strip().upper()
        if action not in OVERRIDE_ACTIONS:
            raise BonusMasterError(f"{doc} {person}: 모르는 오버라이드입니다: {raw_action!r}")
        if action in ("INCLUDE", "EXCLUDE"):
            cleaned[action] = None
        elif action == "WORK":
            work = str(value or "").strip()
            if not work:
                raise BonusMasterError(f"{doc} {person}: 업무분류가 비어 있습니다.")
            cleaned[action] = work
        else:
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise BonusMasterError(f"{doc} {person}: {action} 값이 숫자가 아닙니다: {value!r}") from exc
            if action == "RATE" and number not in ALLOWED_RATES:
                raise BonusMasterError(f"{doc} {person}: 요율은 {ALLOWED_RATES} 중 하나여야 합니다: {number:g}")
            if action == "FEE" and number < 0:
                raise BonusMasterError(f"{doc} {person}: 수수료는 0 이상이어야 합니다.")
            if action == "SHARE" and not (0 < number <= 100):
                raise BonusMasterError(f"{doc} {person}: 지분은 0 초과 100 이하여야 합니다.")
            cleaned[action] = number
    if "INCLUDE" in cleaned and "EXCLUDE" in cleaned:
        raise BonusMasterError(f"{doc} {person}: 포함과 제외를 같이 둘 수 없습니다.")
    return cleaned


def set_overrides(db, period: str, doc_id: str, person: str, actions: "dict[str, Any]", usr_seq: "int | None" = None) -> "dict[str, Any]":
    """한 달·한 감정서·한 사람의 오버라이드를 통째로 바꾼다 (빈 dict 면 전부 지운다)."""
    _check_period(period)
    doc = str(doc_id or "").strip()
    name = str(person or "").strip()
    if not doc or not name:
        raise BonusMasterError("감정서번호와 이름이 있어야 합니다.")
    cleaned = _clean_actions(doc, name, actions or {})
    db.execute(delete(BonusOverride).where(
        BonusOverride.period == period, BonusOverride.doc_id == doc, BonusOverride.person == name
    ))
    for action, value in cleaned.items():
        db.add(BonusOverride(
            period=period, doc_id=doc, person=name, action=action,
            value=None if action in ("INCLUDE", "EXCLUDE", "WORK") else value,
            memo=value if action == "WORK" else None, created_by_usr_seq=usr_seq,
        ))
    db.commit()
    return cleaned
