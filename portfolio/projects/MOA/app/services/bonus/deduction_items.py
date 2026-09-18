"""공제 대장 (a10_bonus_deduction) — 발생 → 대기 → 지급월 적용 → 마감 잠금.

비유: 청구서함. 화환·감정서경비 같은 공제는 생길 때 함에 넣어 두고(PENDING), 그 달 상여를
만들 때 넣을 것을 골라 도장을 찍는다(APPLIED, applied_period). 도장 찍힌 달이 마감되면 못 고친다.
상여가 0이라 못 뺀 화환류는 마감 때 다시 함으로 돌아간다(revert_unconsumed) — 엑셀의 '공제못함'.
삭제는 없다. 잘못 넣은 것은 VOID + 사유.
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import select

from app.models.bonus_ledger import BonusDeduction
from app.services.bonus import closing
from app.services.bonus.engine import DEDUCTION_KINDS, Y_SUB
from app.services.bonus.schedule import BonusMasterError

STATUSES = ("PENDING", "APPLIED", "VOID")
SOURCES = ("MANUAL", "EXCEL", "VOUCHER")
CARRY_KINDS = tuple(kind for kind, bucket in Y_SUB.items() if bucket == "wreath")   # 상여 0 이면 이월되는 종류
_EDITABLE = ("person", "kind", "doc_id", "amount", "occurred_on", "memo")


def as_dict(row: BonusDeduction) -> "dict[str, Any]":
    return {
        "item_id": row.deduction_id, "person": row.person, "kind": row.kind, "doc_id": row.doc_id,
        "amount": float(row.amount or 0), "occurred_on": row.occurred_on, "memo": row.memo,
        "source": row.source, "source_key": row.source_key, "status": row.status,
        "applied_period": row.applied_period, "applied_at": row.applied_at,
        "void_reason": row.void_reason, "created_at": row.created_at,
    }


def _date(value: Any) -> "date | None":
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise BonusMasterError(f"발생일을 읽을 수 없습니다: {value!r}") from exc


def _clean(data: "dict[str, Any]", *, partial: bool = False) -> "dict[str, Any]":
    cleaned: "dict[str, Any]" = {}
    if "person" in data or not partial:
        person = str(data.get("person") or "").strip()
        if not person:
            raise BonusMasterError("이름이 비어 있습니다.")
        cleaned["person"] = person
    if "kind" in data or not partial:
        kind = str(data.get("kind") or "").strip().upper()
        if kind not in DEDUCTION_KINDS:
            raise BonusMasterError(f"모르는 공제 종류입니다: {data.get('kind')!r}")
        cleaned["kind"] = kind
    if "amount" in data or not partial:
        try:
            amount = float(data.get("amount") or 0)
        except (TypeError, ValueError) as exc:
            raise BonusMasterError(f"금액이 숫자가 아닙니다: {data.get('amount')!r}") from exc
        if amount < 0:
            raise BonusMasterError(f"공제 금액은 0 이상이어야 합니다 (환입은 VARIABLE_CREDIT): {amount:g}")
        cleaned["amount"] = amount
    if "doc_id" in data:
        cleaned["doc_id"] = str(data.get("doc_id") or "").strip() or None
    if "occurred_on" in data:
        cleaned["occurred_on"] = _date(data.get("occurred_on"))
    if "memo" in data:
        cleaned["memo"] = (str(data.get("memo") or "").strip() or None)
    if not partial:
        source = str(data.get("source") or "MANUAL").strip().upper()
        if source not in SOURCES:
            raise BonusMasterError(f"모르는 출처입니다: {source!r}")
        cleaned["source"] = source
        cleaned["source_key"] = (str(data.get("source_key") or "").strip() or None)
    return cleaned


def _assert_open(db, period: str) -> None:
    try:
        closing._split(period)
    except ValueError as exc:
        raise BonusMasterError(str(exc)) from exc
    if closing.close_status(db, period) == "CLOSED":
        raise BonusMasterError(f"{period} 은 마감돼 있습니다 — 먼저 재개하세요.")


def _get(db, item_id: int) -> BonusDeduction:
    row = db.get(BonusDeduction, int(item_id))
    if row is None:
        raise BonusMasterError(f"공제 항목이 없습니다: {item_id}")
    return row


def _apply(row: BonusDeduction, period: str, usr_seq: "int | None") -> None:
    row.status, row.applied_period = "APPLIED", period
    row.applied_by_usr_seq, row.applied_at = usr_seq, datetime.now()


def _release(row: BonusDeduction) -> None:
    row.status, row.applied_period, row.applied_by_usr_seq, row.applied_at = "PENDING", None, None, None


def list_items(
    db, *, status: "str | None" = None, person: "str | None" = None, kind: "str | None" = None,
    doc_id: "str | None" = None, period: "str | None" = None,
) -> "list[dict[str, Any]]":
    query = select(BonusDeduction)
    if status:
        query = query.where(BonusDeduction.status == status)
    if person:
        query = query.where(BonusDeduction.person == person)
    if kind:
        query = query.where(BonusDeduction.kind == kind)
    if doc_id:
        query = query.where(BonusDeduction.doc_id == doc_id)
    if period:
        query = query.where(BonusDeduction.applied_period == period, BonusDeduction.status == "APPLIED")
    query = query.order_by(BonusDeduction.person, BonusDeduction.occurred_on, BonusDeduction.deduction_id)
    return [as_dict(row) for row in db.scalars(query).all()]


def create_item(db, data: "dict[str, Any]", usr_seq: "int | None" = None, *, apply_period: "str | None" = None) -> "dict[str, Any]":
    """새 항목. apply_period 를 주면 그 달(열려 있어야 함)에 바로 적용. 같은 출처 키가 있으면 그것을 돌려준다(skipped)."""
    cleaned = _clean(data)
    apply_period = apply_period or (str(data.get("apply_period") or "").strip() or None)
    if cleaned["source_key"]:
        existing = db.scalar(select(BonusDeduction).where(
            BonusDeduction.source == cleaned["source"], BonusDeduction.source_key == cleaned["source_key"],
        ))
        if existing is not None:
            return {**as_dict(existing), "skipped": True}
    if apply_period:
        _assert_open(db, apply_period)
    row = BonusDeduction(**cleaned, status="PENDING", created_by_usr_seq=usr_seq)
    if apply_period:
        _apply(row, apply_period, usr_seq)
    db.add(row)
    db.commit()
    return {**as_dict(row), "skipped": False}


def update_item(db, item_id: int, data: "dict[str, Any]", usr_seq: "int | None" = None) -> "dict[str, Any]":
    """대기 중인 항목만 고친다 — 적용된 것은 먼저 적용을 풀어야 한다."""
    row = _get(db, item_id)
    if row.status != "PENDING":
        raise BonusMasterError(f"항목 {item_id} 은 {row.status} 상태라 고칠 수 없습니다 (대기 중만 가능).")
    for key, value in _clean({k: v for k, v in data.items() if k in _EDITABLE}, partial=True).items():
        setattr(row, key, value)
    row.updated_at = datetime.now()
    db.commit()
    return as_dict(row)


def split_item(db, item_id: int, amount: Any, usr_seq: "int | None" = None) -> "dict[str, Any]":
    """대기 항목을 둘로 나눈다 — 엑셀 미수금 탭의 부분 회수(273,500 중 4,000만 이번 달) 방식.

    떼어낸 금액이 새 대기 항목이 되고 원본에는 잔액이 남는다. 출처 키(유니크)는 원본에만 남긴다.
    """
    row = _get(db, item_id)
    if row.status != "PENDING":
        raise BonusMasterError(f"항목 {item_id} 은 {row.status} 상태라 나눌 수 없습니다 (대기 중만 가능 — 적용은 먼저 대기로 돌리세요).")
    try:
        part = float(amount or 0)
    except (TypeError, ValueError) as exc:
        raise BonusMasterError(f"금액이 숫자가 아닙니다: {amount!r}") from exc
    total = float(row.amount or 0)
    if not 0 < part < total:
        raise BonusMasterError(f"분할 금액은 0보다 크고 원래 금액({total:,.0f}원)보다 작아야 합니다: {part:,.0f}")
    def _note(memo, text):
        return (f"{memo} {text}" if memo else text)[:200]
    split = BonusDeduction(
        person=row.person, kind=row.kind, doc_id=row.doc_id, amount=part, occurred_on=row.occurred_on,
        memo=_note(row.memo, f"({total:,.0f}원 중 {part:,.0f}원 분할)"),
        source=row.source, source_key=None, status="PENDING", created_by_usr_seq=usr_seq,
    )
    row.amount = total - part
    row.memo = _note(row.memo, f"({total:,.0f}원 중 {total - part:,.0f}원 남음)")
    row.updated_at = datetime.now()
    db.add(split)
    db.commit()
    return {"split": as_dict(split), "remainder": as_dict(row)}


def void_item(db, item_id: int, reason: str, usr_seq: "int | None" = None) -> "dict[str, Any]":
    """무효 처리(삭제 대신). 마감된 달에 적용된 항목은 재개 전엔 못 건드린다."""
    text = str(reason or "").strip()
    if not text:
        raise BonusMasterError("무효 사유를 적어야 합니다.")
    row = _get(db, item_id)
    if row.status == "APPLIED" and closing.close_status(db, row.applied_period) == "CLOSED":
        raise BonusMasterError(f"항목 {item_id} 은 {row.applied_period} 마감에 들어 있어 무효 처리할 수 없습니다.")
    _release(row)
    row.status, row.void_reason, row.voided_at, row.updated_at = "VOID", text, datetime.now(), datetime.now()
    db.commit()
    return as_dict(row)


def set_applied(db, period: str, person: str, item_ids: "list[int]", usr_seq: "int | None" = None) -> "list[dict[str, Any]]":
    """한 달·한 사람의 적용 집합을 통째로 맞춘다. 빠진 항목은 대기로 돌아간다."""
    _assert_open(db, period)
    name = str(person or "").strip()
    wanted = [int(i) for i in dict.fromkeys(item_ids or [])]
    rows = [_get(db, item_id) for item_id in wanted]
    for row in rows:
        if row.person != name:
            raise BonusMasterError(f"항목 {row.deduction_id} 은 {row.person} 의 것입니다 ({name} 아님).")
        if row.status == "VOID":
            raise BonusMasterError(f"항목 {row.deduction_id} 은 무효 처리된 항목입니다.")
        if row.status == "APPLIED" and row.applied_period != period:
            raise BonusMasterError(f"항목 {row.deduction_id} 은 이미 {row.applied_period} 에 적용돼 있습니다.")
    current = db.scalars(select(BonusDeduction).where(
        BonusDeduction.applied_period == period, BonusDeduction.person == name, BonusDeduction.status == "APPLIED",
    )).all()
    for row in current:
        if row.deduction_id not in wanted:
            _release(row)
            row.updated_at = datetime.now()
    for row in rows:
        if row.status != "APPLIED":
            _apply(row, period, usr_seq)
    db.commit()
    return [as_dict(row) for row in rows]


def revert_unconsumed(db, period: str, persons: "list[str]", usr_seq: "int | None" = None) -> "list[int]":
    """상여가 0이라 못 뺀 사람들의 화환류(CARRY_KINDS)를 다시 대기로 — 엑셀의 '공제못함' 목록."""
    if not persons:
        return []
    rows = db.scalars(select(BonusDeduction).where(
        BonusDeduction.applied_period == period, BonusDeduction.status == "APPLIED",
        BonusDeduction.person.in_(list(persons)), BonusDeduction.kind.in_(list(CARRY_KINDS)),
    )).all()
    note = f"({period} 상여 0 → 이월)"
    for row in rows:
        _release(row)
        row.memo = f"{row.memo} {note}" if row.memo else note
        row.updated_at = datetime.now()
    db.commit()
    return [row.deduction_id for row in rows]


def pending_summary(db) -> "dict[str, dict[str, float]]":
    summary: "dict[str, dict[str, float]]" = {}
    for row in db.scalars(select(BonusDeduction).where(BonusDeduction.status == "PENDING")).all():
        entry = summary.setdefault(row.person, {"count": 0, "amount": 0.0})
        entry["count"] += 1
        entry["amount"] += float(row.amount or 0)
    return summary


def pending_by_person(db) -> "dict[str, list[dict[str, Any]]]":
    result: "dict[str, list[dict[str, Any]]]" = {}
    for item in list_items(db, status="PENDING"):
        result.setdefault(item["person"], []).append(item)
    return result


def sync_voucher_candidates(
    db, voucher_rows: "list[dict[str, Any]]", ratios: "dict[tuple[str, str], float]", *, apply_period: "str | None" = None,
) -> "list[dict[str, Any]]":
    """경비 전표(적요에 감정서번호)를 그 감정서 사람들의 **대기 후보**(source=VOUCHER)로 올린다.

    엔진이 전표를 스스로 빼던 것(자동 반영)을 대신한다 — 재무팀이 사람별 공제에서 골라 적용해야 빠진다.
    금액은 적요의 감정서 수로 나눈 뒤 사람 지분(ratios[(감정서, 사람)] %)을 곱한다.
    같은 전표 키가 있으면 건너뛰고, 같은 (사람, 감정서, 금액)이 이미 대장에 있으면(엑셀·수기) 중복으로 보고 건너뛴다.
    """
    created: "list[dict[str, Any]]" = []
    # 감정서 관련 공제는 전부 뺀다 — 열린 달이면 만들면서 바로 적용(재무팀이 사람별 공제에서 풀 수 있다)
    applying = bool(apply_period) and closing.close_status(db, apply_period) != "CLOSED"
    by_doc: "dict[str, list[tuple[str, float]]]" = {}
    for (doc, person), pct in ratios.items():
        by_doc.setdefault(doc, []).append((person, float(pct or 0)))
    for row in voucher_rows:
        docs = [doc for doc in row.get("doc_ids", []) if doc in by_doc]
        # 감정서번호는 없지만 적요에 사람이 있는 전표('… 수입인지-김형식') → 그 사람의 감정서 없는 후보
        targets = ([(doc, person, pct) for doc in docs for person, pct in by_doc[doc]] if docs
                   else [(None, person, 100.0 / len(row["persons"])) for person in row.get("persons") or []])
        if not targets:
            continue
        per_doc = float(row["amount"] or 0) / (len(row["doc_ids"]) if docs else 1)
        for doc, person, pct in targets:
            amount = round(per_doc * pct / 100)
            if amount <= 0:
                continue
            source_key = f"vch:{row['key']}:{doc or ''}:{person}"
            if db.scalar(select(BonusDeduction).where(BonusDeduction.source == "VOUCHER", BonusDeduction.source_key == source_key)):
                continue
            twin = db.scalar(select(BonusDeduction).where(
                BonusDeduction.person == person, BonusDeduction.doc_id == doc, BonusDeduction.status != "VOID",
                BonusDeduction.kind == "DOC_EXPENSE", BonusDeduction.amount >= amount - 1, BonusDeduction.amount <= amount + 1,
            ))
            if twin is not None:
                continue
            item = BonusDeduction(
                person=person, kind="DOC_EXPENSE", doc_id=doc, amount=amount, occurred_on=row.get("voucher_date"),
                memo=" ".join(x for x in (row.get("account_name"), row.get("remark")) if x)[:200] or None,
                source="VOUCHER", source_key=source_key, status="PENDING",
            )
            if applying:
                _apply(item, apply_period, None)
            db.add(item)
            created.append(item)
    if created:
        db.commit()
    return [as_dict(item) for item in created]


def insert_seeded(db, items: "list[dict[str, Any]]") -> "tuple[int, int]":
    """엑셀·전표에서 만든 항목을 그대로 넣는다 — 마감된 달에도 이력으로 (열림 검사 없음). 같은 출처 키는 건너뛴다."""
    written = skipped = 0
    for item in items:
        existing = db.scalar(select(BonusDeduction).where(
            BonusDeduction.source == item["source"], BonusDeduction.source_key == item["source_key"],
        )) if item.get("source_key") else None
        if existing is not None:
            skipped += 1
            continue
        row = BonusDeduction(
            person=item["person"], kind=item["kind"], doc_id=item.get("doc_id"), amount=item["amount"],
            occurred_on=item.get("occurred_on"), memo=item.get("memo"), source=item["source"], source_key=item.get("source_key"),
            status=item["status"], applied_period=item.get("applied_period"),
            applied_at=datetime.now() if item["status"] == "APPLIED" else None,
        )
        db.add(row)
        written += 1
    db.commit()
    return written, skipped
