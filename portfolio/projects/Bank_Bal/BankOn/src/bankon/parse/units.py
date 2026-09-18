"""의견서 '대상물건 개요' → 구분건물 호별 표: 기호별 전유·공용·공급·**대지권면적**·용도.

    | 기 호 | 구 분            | 전유면적(㎡) | 공용면적(㎡) | 공급면적(㎡) | 대지권면적(㎡) | 전용률(%) | 용도    |
    | 가    | 제3층 제4-304호  | 61.1366     | 46.0984     | 107.235     | 11.788        | 57.01     | 판매시설 |

호마다 대지권면적이 달라 outline(대표값 하나)로는 안 된다(2695: 11.788/9.2774/10.534 — 사용자 정정 2026-08-27).
기호 = mullist SNO('가','나'…)와 같다.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .outline import to_decimal
from .tables import iter_tables, normalize_label as _normalize, rows_of

REQUIRED_HEADERS = ("기호", "대지권면적(㎡)")
_COLUMNS = {
    "mark": ("기호", "기 호"),
    "unit": ("구분", "구 분"),
    "area_exclusive": ("전유면적(㎡)", "전유면적"),
    "area_common": ("공용면적(㎡)", "공용면적"),
    "area_supply": ("공급면적(㎡)", "공급면적"),
    "area_land_right": ("대지권면적(㎡)", "대지권면적", "대지지분"),
    "use": ("용도", "용 도"),
}


@dataclass(frozen=True)
class UnitRow:
    mark: str | None
    unit: str | None
    area_exclusive: Decimal | None
    area_common: Decimal | None
    area_supply: Decimal | None
    area_land_right: Decimal | None
    use: str | None


def _index_of(header, names):
    wanted = {_normalize(n) for n in names}
    for i, cell in enumerate(header):
        if _normalize(cell) in wanted:
            return i
    return None


def parse(section_body: str | None) -> tuple[UnitRow, ...]:
    if not section_body:
        return ()
    wanted = {_normalize(h) for h in REQUIRED_HEADERS}
    for table_html in iter_tables(section_body):
        rows = rows_of(table_html)
        header_at = next((i for i, r in enumerate(rows[:3]) if wanted <= {_normalize(c) for c in r}), None)
        if header_at is None:
            continue
        header = rows[header_at]
        cols = {k: _index_of(header, names) for k, names in _COLUMNS.items()}
        out = []
        for row in rows[header_at + 1:]:
            def cell(key):
                at = cols[key]
                return row[at].strip() if at is not None and len(row) > at else None
            mark = cell("mark")
            if not mark or len(mark) > 2:
                continue
            out.append(UnitRow(
                mark=mark, unit=(cell("unit") or "").replace("\n", " ").strip() or None,
                area_exclusive=to_decimal(cell("area_exclusive")), area_common=to_decimal(cell("area_common")),
                area_supply=to_decimal(cell("area_supply")), area_land_right=to_decimal(cell("area_land_right")),
                use=cell("use"),
            ))
        if out:
            return tuple(out)
    return ()


def by_mark(rows: tuple[UnitRow, ...], mark: str | None) -> UnitRow | None:
    if not mark:
        return None
    return next((r for r in rows if r.mark == mark), None)
