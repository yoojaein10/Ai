"""마감·이월 읽기 (a10_bonus_close · a10_bonus_result).

- already_paid: 마감된(CLOSED) 달의 행(감정서×사람)만 기지급으로 센다 → 이번 달은 차액만.
- carry_in: 전월이 CLOSED 일 때만 사람 합계 행의 미납비용(AE)을 다음 달 미납비이월(M)로.
  전월 마감이 없으면 None 을 돌려주고 화면이 경고한다 — 0 으로 조용히 넘어가지 않는다.
쓰기: close_period(스냅샷 저장+잠금) / reopen_period / snapshot_from_rows(스냅샷 → 리포트 모양).
"""

import calendar
import json
import re
from datetime import date, datetime
from typing import Any

from sqlalchemy import delete, select

from app.models.bonus_ledger import BonusClose, BonusResult
from app.services.bonus.schedule import BonusMasterError

_PERIOD = re.compile(r"^(\d{4})(\d{2})$")
_CHUNK = 500


def _split(period: str) -> "tuple[int, int]":
    match = _PERIOD.match(str(period or ""))
    if not match or not (1 <= int(match.group(2)) <= 12):
        raise ValueError(f"지급월은 YYYYMM 이어야 합니다: {period!r}")
    return int(match.group(1)), int(match.group(2))


def prev_period(period: str) -> str:
    year, month = _split(period)
    if month == 1:
        return f"{year - 1}12"
    return f"{year}{month - 1:02d}"


def period_bounds(period: str) -> "tuple[date, date]":
    """지급월 → 입금월(전월)의 첫날·말일."""
    year, month = _split(prev_period(period))
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def close_status(db, period: str) -> "str | None":
    row = db.get(BonusClose, period)
    return row.status if row else None


def close_source(db, period: str) -> "str | None":
    row = db.get(BonusClose, period)
    return row.source if row else None


def list_closes(db) -> "list[dict[str, Any]]":
    """마감 표 전부 (화면 상태 배지·기본 지급월용)."""
    rows = db.scalars(select(BonusClose).order_by(BonusClose.period)).all()
    return [{"period": row.period, "status": row.status, "source": row.source, "closed_at": row.closed_at} for row in rows]


def next_open_period(closes: "list[dict[str, Any]]", today: date) -> str:
    """마지막 CLOSED 의 다음 달 — 없으면 이번 달."""
    closed = sorted(row["period"] for row in closes if row["status"] == "CLOSED")
    if not closed:
        return f"{today:%Y%m}"
    year, month = _split(closed[-1])
    return f"{year + 1}01" if month == 12 else f"{year}{month + 1:02d}"


def _closed_periods(db) -> "set[str]":
    return {row.period for row in db.scalars(select(BonusClose).where(BonusClose.status == "CLOSED")).all()}


def already_paid(db, doc_ids: "list[str]", *, exclude_period: "str | None" = None) -> "dict[tuple[str, str], float]":
    """{(감정서, 사람): 마감된 달들에 지급한 순수수료 합} — 사람 합계 행(doc_id NULL)은 제외.

    exclude_period: 그 달 자체의 스냅샷은 빼고 센다 — 마감된 달을 다시 계산해 볼 때(대조 스크립트) 필요하다.
    """
    ids = [doc for doc in dict.fromkeys(str(d or "").strip() for d in doc_ids) if doc]
    if not ids:
        return {}
    closed = _closed_periods(db) - {exclude_period}
    if not closed:
        return {}
    result: "dict[tuple[str, str], float]" = {}
    for start in range(0, len(ids), _CHUNK):
        rows = db.scalars(
            select(BonusResult).where(
                BonusResult.doc_id.in_(ids[start:start + _CHUNK]),
                BonusResult.period.in_(sorted(closed)),
            )
        ).all()
        for row in rows:
            key = (row.doc_id, row.person)
            result[key] = result.get(key, 0.0) + float(row.fee or 0)
    return result


def carry_in(db, period: str) -> "dict[str, float] | None":
    """전월 마감 사람 합계 행의 미납비용을 양수(차감액)로. 전월이 CLOSED 가 아니면 None."""
    previous = prev_period(period)
    if close_status(db, previous) != "CLOSED":
        return None
    rows = db.scalars(
        select(BonusResult).where(BonusResult.period == previous, BonusResult.doc_id.is_(None))
    ).all()
    result: "dict[str, float]" = {}
    for row in rows:   # 주주 합계 + 공통건 합계처럼 사람당 행이 둘이면 더한다
        if row.kind == "META":
            continue
        result[row.person] = result.get(row.person, 0.0) - float(row.unpaid_carry_out or 0)
    return result


def load_result(db, period: str) -> "list[dict[str, Any]]":
    """마감 스냅샷 행 전부 (3단계 화면·총괄표가 쓴다)."""
    rows = db.scalars(
        select(BonusResult).where(BonusResult.period == period).order_by(BonusResult.person, BonusResult.doc_id)
    ).all()
    return [
        {
            column.name: getattr(row, column.name)
            for column in BonusResult.__table__.columns
        }
        for row in rows
    ]


# ── 마감 / 재개 / 스냅샷 ─────────────────────────────────────────────────

META_PERSON = "__meta__"   # 보류 목록·경고를 담는 행 (사람이 아니다)
_TOTAL_KEYS = ("payout_base", "bonus", "pretax", "income_tax", "resident_tax", "other_deduct", "payment", "unpaid_carry_out", "card_limit")


def _person_row(period: str, kind: str, entry: "dict[str, Any]") -> BonusResult:
    totals = entry["totals"]
    return BonusResult(
        period=period, person=entry["name"], kind=kind, doc_id=None,
        **{key: totals.get(key) for key in _TOTAL_KEYS},
        retired="Y" if entry.get("retired") else "N", source="MOA",
        detail_json=json.dumps({"totals": totals, "blocks": entry.get("blocks", [])}, ensure_ascii=False, default=str),
    )


def _doc_row(period: str, person: str, row: "dict[str, Any]") -> BonusResult:
    return BonusResult(
        period=period, person=person, kind=row.get("kind") or "SHAREHOLDER", doc_id=row["doc_id"],
        block_from=row.get("block_from"), rate=row.get("rate"), share_pct=row.get("share_pct"),
        fee=row.get("fee") or 0, assessed=row.get("assessed") or 0, indemnity=row.get("indemnity") or 0,
        association_fee=row.get("association_fee") or 0, bonus=row.get("bonus"), source="MOA",
        detail_json=json.dumps(row, ensure_ascii=False, default=str),
    )


def close_period(db, period: str, report: "dict[str, Any]", usr_seq: "int | None" = None) -> "dict[str, Any]":
    """리포트를 스냅샷으로 저장하고 잠근다. 이미 CLOSED 면 거부. 전월이 열려 있으면 경고만."""
    _split(period)
    if close_status(db, period) == "CLOSED":
        raise BonusMasterError(f"{period} 은 이미 마감돼 있습니다 — 고치려면 먼저 재개하세요.")
    warnings: "list[str]" = []
    previous = prev_period(period)
    if close_status(db, previous) != "CLOSED":
        warnings.append(f"전월({previous})이 마감되지 않았습니다 — 미납비이월이 0으로 들어갔을 수 있습니다.")
    rows: "list[BonusResult]" = []
    for group, kind in (("shareholders", "SHAREHOLDER"), ("common", "COMMON"), ("associates", "ASSOCIATE")):
        for entry in report.get(group, []):
            rows.append(_person_row(period, kind, entry))
            rows.extend(_doc_row(period, entry["name"], row) for row in entry.get("rows", []))
    meta = BonusResult(
        period=period, person=META_PERSON, kind="META", doc_id=None, source="MOA",
        detail_json=json.dumps({"held": report.get("held", []), "warnings": report.get("warnings", [])}, ensure_ascii=False, default=str),
    )
    db.execute(delete(BonusResult).where(BonusResult.period == period, BonusResult.source == "MOA"))
    existing = db.get(BonusClose, period)
    if existing is None:
        db.add(BonusClose(period=period, status="CLOSED", source="MOA", closed_by_usr_seq=usr_seq, closed_at=datetime.now()))
    else:
        existing.status, existing.source, existing.closed_by_usr_seq, existing.closed_at = "CLOSED", "MOA", usr_seq, datetime.now()
    db.add_all(rows + [meta])
    db.commit()
    from app.services.bonus import deduction_items   # 순환 import 방지 (deduction_items 가 closing 을 쓴다)

    unconsumed = sorted({
        entry["name"] for group in ("shareholders", "common", "associates") for entry in report.get(group, [])
        if float((entry.get("totals") or {}).get("wreath_unapplied") or 0) > 0
    })
    reverted = deduction_items.revert_unconsumed(db, period, unconsumed, usr_seq)
    if reverted:
        warnings.append(f"상여가 0이라 못 뺀 화환류 {len(reverted)}건을 대기로 돌렸습니다 (다음 달 이월): {', '.join(unconsumed)}")
    return {"period": period, "status": "CLOSED", "rows": len(rows), "warnings": warnings, "reverted_items": reverted}


def reopen_period(db, period: str, usr_seq: "int | None" = None) -> "dict[str, Any]":
    """MOA 마감을 되돌린다 — 스냅샷을 지우고 다시 계산하게 한다. 엑셀 이력은 못 되돌린다."""
    existing = db.get(BonusClose, period)
    if existing is None or existing.status != "CLOSED":
        raise BonusMasterError(f"{period} 은 마감돼 있지 않습니다.")
    if existing.source != "MOA":
        raise BonusMasterError(f"{period} 은 엑셀 지급 이력이라 재개할 수 없습니다.")
    db.execute(delete(BonusResult).where(BonusResult.period == period, BonusResult.source == "MOA"))
    existing.status, existing.reopened_by_usr_seq, existing.reopened_at = "OPEN", usr_seq, datetime.now()
    db.commit()
    return {"period": period, "status": "OPEN"}


def _excel_doc(row: "dict[str, Any]") -> "dict[str, Any]":
    def number(key):
        return float(row[key]) if row.get(key) is not None else None

    return {
        "doc_id": row["doc_id"], "person": row["person"], "kind": row["kind"],
        "fee": float(row.get("fee") or 0), "assessed": float(row.get("assessed") or 0),
        "rate": number("rate"), "share_pct": number("share_pct"), "bonus": number("bonus"), "flags": ["EXCEL"],
    }


def _group_target(kind: str, kinds: "set[str]") -> str:
    if kind == "SHAREHOLDER" and "SHAREHOLDER" in kinds:
        return "SHAREHOLDER"
    if kind == "COMMON" and "COMMON" in kinds:
        return "COMMON"
    if "ASSOCIATE" in kinds:
        return "ASSOCIATE"
    return next(iter(sorted(kinds)), kind)


def snapshot_from_rows(period: str, rows: "list[dict[str, Any]]") -> "dict[str, Any]":
    """마감 스냅샷 행 → 리포트와 같은 모양. detail_json 이 없는 엑셀 이력은 열 값으로만 채운다."""
    from app.services.bonus.summary import summarize

    held: "list[Any]" = []
    warnings: "list[str]" = []
    entries: "dict[tuple[str, str], dict[str, Any]]" = {}
    docs_by: "dict[str, list[dict[str, Any]]]" = {}
    for row in rows:
        detail = json.loads(row["detail_json"]) if row.get("detail_json") else None
        kind = row.get("kind") or "SHAREHOLDER"
        if kind == "META":
            held, warnings = (detail or {}).get("held", []), (detail or {}).get("warnings", [])
        elif row.get("doc_id") is None:
            entries[(row["person"], kind)] = {
                "name": row["person"], "kind": kind, "retired": row.get("retired") == "Y",
                "totals": (detail or {}).get("totals") or {key: float(row.get(key) or 0) for key in _TOTAL_KEYS},
                "blocks": (detail or {}).get("blocks", []), "rows": [],
            }
        else:
            docs_by.setdefault(row["person"], []).append(detail or _excel_doc(row))
    for person, docs in docs_by.items():
        kinds = {kind for (name, kind) in entries if name == person}
        for doc in docs:
            target = _group_target(doc.get("kind") or "SHAREHOLDER", kinds)
            entries.setdefault((person, target), {
                "name": person, "kind": target, "retired": False, "totals": {}, "blocks": [], "rows": [],
            })["rows"].append(doc)
    groups: "dict[str, list[dict[str, Any]]]" = {"SHAREHOLDER": [], "COMMON": [], "ASSOCIATE": []}
    for (_, kind), entry in sorted(entries.items()):
        groups.setdefault(kind, []).append(entry)
    year, month = _split(prev_period(period))
    return {
        "period": period, "perf_month": f"{year}{month:02d}", "status": "CLOSED",
        "shareholders": groups["SHAREHOLDER"], "common": groups["COMMON"], "associates": groups["ASSOCIATE"],
        "held": held, "warnings": warnings, "expense_notes": [], "rows": rows,
        "summary": summarize(groups["SHAREHOLDER"], groups["COMMON"], groups["ASSOCIATE"]),
    }


def snapshot_report(db, period: str) -> "dict[str, Any]":
    return snapshot_from_rows(period, load_result(db, period))
