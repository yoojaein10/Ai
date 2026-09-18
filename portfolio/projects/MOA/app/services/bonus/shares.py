"""감정서 지분 — 거래처명 괄호 표기 파서와 인별 지분 결정.

재무팀 시트는 공동 건의 지분을 거래처명 뒤 괄호에 적는다: '(김5 강2.5 조2.5)',
'(안9:이1)', '(이덕권5:이준희5)', 공동유치 '50%', 법인카드 몫 '(안6:황4/법카 안100)'.
숫자는 십분율(5 → 50%), 1 이하면 비율(0.33 → 33%), 10 초과면 이미 퍼센트(100).
파서는 시딩·제안용이고, 정식 값은 a10_bonus_share 다.

지분 우선순위(계획 확정): GaPrice 승인 배분(In_Price, 이미 지분이 적용된 금액이라
다시 곱하지 않는다) → 수기 → 시드 → APW_Booking → APW_Charge_IDX → 괄호 → 균등.
"""

import re
from dataclasses import dataclass
from typing import Any

from app.services.bonus.schedule import BonusMasterError


@dataclass(frozen=True)
class ParsedNote:
    shares: "dict[str, float]"          # 이름(또는 약칭, '*'=블록 주인) → %
    bc: "dict[str, float] | None" = None  # 법인카드 몫이 따로 적힌 경우


@dataclass(frozen=True)
class ShareHit:
    pct: float
    source: str  # IN_PRICE | MANUAL | SEED | BOOKING | CHARGE_IDX | NOTE | EQUAL


_BRACKET = re.compile(r"\(([^()]*)\)")
# 이름 바로 뒤에 숫자: '김5', '이덕권5', '안100'. 뒤에는 구분자·끝·다음 토큰만 온다 —
# '제3주구'(숫자 뒤 한글) 같은 건 지분이 아니다.
_TOKEN = re.compile(r"([가-힣]{1,4})(\d+(?:\.\d+)?)(?=\s*(?:[\s:,/)]|$|[가-힣]{1,4}\d))")
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def _pct(raw: str) -> float:
    value = float(raw)
    if value > 10:
        return value
    if value >= 1:
        return value * 10
    return value * 100


def _tokens(text: str) -> "dict[str, float]":
    return {name: _pct(number) for name, number in _TOKEN.findall(text)}


def parse_share_note(customer_name: "str | None") -> "ParsedNote | None":
    """거래처명에서 지분 표기를 읽는다. 지분 표기가 아니면 None."""
    text = str(customer_name or "")
    shares: "dict[str, float]" = {}
    bc: "dict[str, float]" = {}
    for inner in _BRACKET.findall(text):
        for part in inner.split("/"):
            found = _tokens(part)
            if not found:
                continue
            if "법카" in part:
                bc.update(found)
            else:
                shares.update(found)
    if shares:
        return ParsedNote(shares=shares, bc=bc or None)
    percent = _PERCENT.search(text)
    if percent:
        return ParsedNote(shares={"*": float(percent.group(1))})
    return None


def match_note_names(note: "dict[str, float]", candidates: "list[str]") -> "dict[str, float]":
    """약칭(성 한 글자)을 후보 이름으로 푼다. 같은 성이 둘이면 풀지 않는다(모호)."""
    result: "dict[str, float]" = {}
    for key, pct in note.items():
        if key == "*" or key in candidates:
            result[key] = pct
            continue
        hits = [name for name in candidates if name.startswith(key)]
        if len(hits) == 1:
            result[hits[0]] = pct
    return result


def resolve_share(
    person: str,
    *,
    in_price: float = 0.0,
    fee_total: float = 0.0,
    manual: "float | None" = None,
    seed: "float | None" = None,
    booking: "float | None" = None,
    charge_idx: "float | None" = None,
    note: "dict[str, float] | None" = None,
    names: "list[str] | tuple[str, ...]" = (),
) -> ShareHit:
    """한 사람의 지분(%)과 그 근거. note 는 match_note_names 를 거친 실명 dict."""
    if in_price and in_price > 0 and fee_total and fee_total > 0:
        return ShareHit(in_price / fee_total * 100, "IN_PRICE")
    for pct, source in ((manual, "MANUAL"), (seed, "SEED"), (booking, "BOOKING"), (charge_idx, "CHARGE_IDX")):
        if pct is not None:
            return ShareHit(float(pct), source)
    if note:
        if person in note:
            return ShareHit(float(note[person]), "NOTE")
        if "*" in note:
            return ShareHit(float(note["*"]), "NOTE")
    if names and person in names:
        return ShareHit(100 / len(names), "EQUAL")
    return ShareHit(100.0, "EQUAL")


def share_summary(shares: "dict[str, Any]") -> "dict[str, Any]":
    """감정서 한 건의 지분 합 — 100이 아니어도 저장은 되지만 화면에 경고를 띄운다."""
    total = sum(float(value) for value in shares.values())
    return {"total": total, "warning": abs(total - 100) > 0.01}


# ── DB 읽기·쓰기 (a10_bonus_share) ──────────────────────────────────────────

_CHUNK = 500  # MSSQL 2016 파라미터 2100 제한


def load_shares(db, doc_ids: "list[str]") -> "dict[str, dict[str, dict[str, Any]]]":
    """감정서별 살아 있는 지분: {doc_id: {person: {share_pct, bc_pct, source, note}}}."""
    from sqlalchemy import select

    from app.models.bonus_share import BonusShare

    ids = [doc for doc in dict.fromkeys(str(d or "").strip() for d in doc_ids) if doc]
    result: "dict[str, dict[str, dict[str, Any]]]" = {}
    for start in range(0, len(ids), _CHUNK):
        rows = db.scalars(
            select(BonusShare).where(
                BonusShare.active == "Y", BonusShare.doc_id.in_(ids[start:start + _CHUNK])
            )
        ).all()
        for row in rows:
            result.setdefault(row.doc_id, {})[row.person] = {
                "share_pct": float(row.share_pct),
                "bc_pct": float(row.bc_pct) if row.bc_pct is not None else None,
                "source": row.source,
                "note": row.note,
            }
    return result


def _clean_share_rows(doc: str, rows: "list[dict[str, Any]]") -> "dict[str, dict[str, Any]]":
    incoming: "dict[str, dict[str, Any]]" = {}
    for raw in rows:
        person = str(raw.get("person") or "").strip()
        if not person:
            raise BonusMasterError(f"{doc}: 이름이 비어 있습니다.")
        pct = float(raw.get("share_pct") or 0)
        if not (0 < pct <= 100):
            raise BonusMasterError(f"{doc} {person}: 지분은 0 초과 100 이하여야 합니다: {raw.get('share_pct')!r}")
        bc = raw.get("bc_pct")
        bc_pct = float(bc) if bc not in (None, "") else None
        if bc_pct is not None and not (0 < bc_pct <= 100):
            raise BonusMasterError(f"{doc} {person}: 법인카드 몫은 0 초과 100 이하여야 합니다: {bc!r}")
        if person in incoming:
            continue
        incoming[person] = {"share_pct": pct, "bc_pct": bc_pct, "note": (str(raw.get("note") or "").strip() or None)}
    return incoming


def save_shares(
    db, doc_id: str, rows: "list[dict[str, Any]]", usr_seq: "int | None" = None,
    source: str = "MANUAL",
) -> "dict[str, Any]":
    """한 감정서의 지분을 목록 그대로 맞춘다. 합이 100 이 아니어도 저장하고 경고만 돌려준다."""
    from decimal import Decimal

    from sqlalchemy import select

    from app.models.bonus_share import BonusShare

    doc = str(doc_id or "").strip()
    if not doc:
        raise BonusMasterError("감정서번호가 비어 있습니다.")
    incoming = _clean_share_rows(doc, rows)

    current = {row.person: row for row in db.scalars(select(BonusShare).where(BonusShare.doc_id == doc)).all()}
    for person, values in incoming.items():
        row = current.get(person)
        if row is None:
            db.add(BonusShare(
                doc_id=doc, person=person, share_pct=Decimal(str(values["share_pct"])),
                bc_pct=Decimal(str(values["bc_pct"])) if values["bc_pct"] is not None else None,
                note=values["note"], source=source, active="Y", updated_by_usr_seq=usr_seq,
            ))
            continue
        row.share_pct = Decimal(str(values["share_pct"]))
        row.bc_pct = Decimal(str(values["bc_pct"])) if values["bc_pct"] is not None else None
        row.note, row.source, row.active = values["note"], source, "Y"
        row.updated_by_usr_seq = usr_seq
    for person, row in current.items():
        if person not in incoming and row.active == "Y":
            row.active = "N"
            row.updated_by_usr_seq = usr_seq
    db.commit()

    items = [
        {"person": person, **values, "source": source}
        for person, values in incoming.items()
    ]
    summary = share_summary({item["person"]: item["share_pct"] for item in items})
    return {"doc_id": doc, "items": items, "total": summary["total"], "warning": summary["warning"]}


def list_shares(db, doc_id: "str | None" = None) -> "list[dict[str, Any]]":
    """설정 화면용 — 살아 있는 지분 행 전부(또는 한 감정서), 감정서·사람 순."""
    from sqlalchemy import select

    from app.models.bonus_share import BonusShare

    query = select(BonusShare).where(BonusShare.active == "Y")
    if doc_id:
        query = query.where(BonusShare.doc_id == doc_id.strip())
    rows = db.scalars(query.order_by(BonusShare.doc_id, BonusShare.person)).all()
    return [
        {
            "doc_id": row.doc_id, "person": row.person, "share_pct": float(row.share_pct),
            "bc_pct": float(row.bc_pct) if row.bc_pct is not None else None,
            "source": row.source, "note": row.note,
        }
        for row in rows
    ]
