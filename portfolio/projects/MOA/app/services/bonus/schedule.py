"""주주 상여율 스케줄 — (사람, 감정서 접수일 구간) → 요율.

엑셀에서는 사람마다 합계행이 접수기간 라벨별로 갈려 있고('2019년분/2021년 3월~' 40%,
'2020년~2021년 2월' 45%, '2025년 7월 7일 접수분~' 40% …) 그 라벨이 곧 요율표다.
여기서는 라벨을 날짜 구간으로 읽어 두고(시딩), 감정서 접수일로 요율을 고른다.
구간은 양끝 포함 — 이영준 '~2026년 7월7일' 블록에 접수 07-07 건이 들어 있었다.
"""

import calendar
import re
from dataclasses import dataclass
from datetime import date
from typing import Any


class BonusMasterError(ValueError):
    """마스터(사람·요율·지분) 입력이 규칙에 어긋난다."""


@dataclass(frozen=True)
class RateBlock:
    person: str
    from_date: "date | None"  # None = 처음부터
    to_date: "date | None"    # None = 계속
    rate: float
    label: str = ""


# 날짜 토큰: '2021년 3월', '2024년 7월 1일', '2023.6.12일', '2025.10월', '2022/12', '24년 6월'
# 또는 연도만('2020년' — '년분'은 제외).
_DATE = re.compile(
    r"(\d{2,4})\s*[년./]\s*(\d{1,2})\s*(?:[월./]\s*(\d{1,2})\s*일?)?"
    r"|(\d{4})\s*년(?!분)"
)
_YEAR_ONLY = re.compile(r"(\d{4})년분")


def _to_date(m: "re.Match[str]", end: bool) -> date:
    if m.group(4):
        year = int(m.group(4))
        return date(year, 12, 31) if end else date(year, 1, 1)
    year, month, day = int(m.group(1)), int(m.group(2)), m.group(3)
    if year < 100:
        year += 2000
    if day:
        return date(year, month, int(day))
    return date(year, month, calendar.monthrange(year, month)[1]) if end else date(year, month, 1)


def parse_rate_label(label: "str | None") -> "list[tuple[date | None, date | None]]":
    """합계행 라벨 → 접수일 구간 목록. 'YYYY년분'은 그 해 전체, '~' 오른쪽은 끝(말일)."""
    text = str(label or "").strip()
    if not text:
        return []
    if "~" in text:
        left, right = text.split("~", 1)
    elif "부터" in text:
        left, right = text.split("부터", 1)[0], ""
    else:
        left, right = text, ""
    intervals: "list[tuple[date | None, date | None]]" = [
        (date(int(m.group(1)), 1, 1), date(int(m.group(1)), 12, 31))
        for m in _YEAR_ONLY.finditer(left)
    ]
    left_dates = list(_DATE.finditer(_YEAR_ONLY.sub("", left)))
    right_dates = list(_DATE.finditer(right))
    start = _to_date(left_dates[-1], end=False) if left_dates else None
    end = _to_date(right_dates[-1], end=True) if right_dates else None
    if start or end:
        intervals.append((start, end))
    return intervals


def normalize_blocks(blocks: "list[RateBlock]") -> "list[RateBlock]":
    """시작일 순으로 정렬하고, 뒤집힌 구간·겹치는 구간은 거부한다 (저장 전 검증)."""
    for block in blocks:
        if block.from_date and block.to_date and block.to_date < block.from_date:
            raise BonusMasterError(
                f"{block.person} 요율 구간의 끝이 시작보다 빠릅니다: {block.from_date}~{block.to_date}"
            )
    ordered = sorted(blocks, key=lambda b: (b.from_date or date.min, b.to_date or date.max))
    for earlier, later in zip(ordered, ordered[1:]):
        if earlier.to_date is None or later.from_date is None or later.from_date <= earlier.to_date:
            raise BonusMasterError(
                f"{earlier.person} 요율 구간이 겹칩니다: "
                f"{earlier.from_date}~{earlier.to_date or '계속'} / {later.from_date}~{later.to_date or '계속'}"
            )
    return ordered


def rate_for(
    blocks: "list[RateBlock]", receipt_date: "date | None"
) -> "tuple[float | None, date | None, str]":
    """접수일이 든 구간의 요율. (요율, 블록 시작일, 근거) — 근거는
    SCHEDULE(구간 안) / FALLBACK_LATEST(구간 밖·접수일 없음 → 가장 최근 블록) / NONE(블록 없음).
    조용히 40% 같은 기본값을 쓰지 않는다 — 폴백은 화면 경고로 드러낸다."""
    if not blocks:
        return (None, None, "NONE")
    if receipt_date is not None:
        for block in blocks:
            after_start = block.from_date is None or block.from_date <= receipt_date
            before_end = block.to_date is None or receipt_date <= block.to_date
            if after_start and before_end:
                return (block.rate, block.from_date, "SCHEDULE")
    latest = max(blocks, key=lambda b: b.from_date or date.min)
    return (latest.rate, latest.from_date, "FALLBACK_LATEST")


# ── DB 읽기·쓰기 (a10_bonus_rate) ──────────────────────────────────────────

def load_schedule(db) -> "dict[str, list[RateBlock]]":
    """살아 있는 요율 구간을 사람별로 정렬해 돌려준다."""
    from collections import defaultdict

    from sqlalchemy import select

    from app.models.bonus_rate import BonusRate

    rows = db.scalars(
        select(BonusRate).where(BonusRate.active == "Y").order_by(BonusRate.person, BonusRate.from_date)
    ).all()
    grouped: "dict[str, list[RateBlock]]" = defaultdict(list)
    for row in rows:
        grouped[row.person].append(
            RateBlock(row.person, row.from_date, row.to_date, float(row.rate), row.label or "")
        )
    return {person: normalize_blocks(blocks) for person, blocks in grouped.items()}


def _rate_row(row) -> "dict[str, Any]":
    return {
        "from_date": row.from_date, "to_date": row.to_date, "rate": float(row.rate),
        "label": row.label, "source": row.source,
    }


def save_rates(
    db, person: str, rows: "list[dict[str, Any]]", usr_seq: "int | None" = None,
    source: str = "MANUAL",
) -> "list[dict[str, Any]]":
    """한 사람의 요율 구간을 목록 그대로 맞춘다 (겹치면 아무것도 저장하지 않는다)."""
    from decimal import Decimal

    from sqlalchemy import select

    from app.models.bonus_rate import BonusRate

    name = str(person or "").strip()
    if not name:
        raise BonusMasterError("이름이 비어 있습니다.")
    blocks = []
    for raw in rows:
        rate = float(raw.get("rate") or 0)
        if not (0 < rate <= 100):
            raise BonusMasterError(f"{name}: 요율은 0 초과 100 이하여야 합니다: {raw.get('rate')!r}")
        blocks.append(RateBlock(name, raw.get("from_date"), raw.get("to_date"), rate, str(raw.get("label") or "")))
    ordered = normalize_blocks(blocks)

    current = db.scalars(select(BonusRate).where(BonusRate.person == name)).all()
    by_key = {(row.from_date, row.to_date): row for row in current}
    kept = set()
    for block in ordered:
        key = (block.from_date, block.to_date)
        kept.add(key)
        row = by_key.get(key)
        if row is None:
            db.add(BonusRate(
                person=name, from_date=block.from_date, to_date=block.to_date,
                rate=Decimal(str(block.rate)), label=block.label or None, source=source,
                active="Y", updated_by_usr_seq=usr_seq,
            ))
            continue
        row.rate, row.label, row.source, row.active = (
            Decimal(str(block.rate)), block.label or None, source, "Y"
        )
        row.updated_by_usr_seq = usr_seq
    for key, row in by_key.items():
        if key not in kept and row.active == "Y":
            row.active = "N"
            row.updated_by_usr_seq = usr_seq
    db.commit()
    saved = db.scalars(
        select(BonusRate).where(BonusRate.person == name, BonusRate.active == "Y")
    ).all()
    saved.sort(key=lambda r: (r.from_date or date.min, r.to_date or date.max))
    return [_rate_row(row) for row in saved]


def list_rates(db) -> "list[dict[str, Any]]":
    """설정 화면용 — 살아 있는 요율 구간 전부 (사람·시작일 순)."""
    from sqlalchemy import select

    from app.models.bonus_rate import BonusRate

    rows = db.scalars(
        select(BonusRate).where(BonusRate.active == "Y").order_by(BonusRate.person, BonusRate.from_date)
    ).all()
    return [{"person": row.person, **_rate_row(row)} for row in rows]
