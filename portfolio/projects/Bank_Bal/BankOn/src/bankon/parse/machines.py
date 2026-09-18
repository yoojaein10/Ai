"""의견서 '대상물건 개요' → 기계기구 표: 기호별 소재지·명칭(종류)·제작자·제작일자·수량.

    | 기 호 | 소재지          | 명 칭(종 류)   | 제작자 (공급자) | 제작일자 (계약일자) | 수 량 |
    | 1     | 남동구 고잔동 144 | 전동 체인호이스트 | 극동호이스트(주) | 미상             | 1식   |

신한 폼 기계기구 물건의 소재지(동미만 칸) = 지번 + 명칭(실물 2673 '144 전동 체인호이스트', 2026-08-27).
"""
from __future__ import annotations

from dataclasses import dataclass

from .tables import iter_tables, normalize_label as _normalize, rows_of

REQUIRED_HEADERS = ("기호", "명칭(종류)")
_COLUMNS = {
    "mark": ("기호", "기 호"),
    "location": ("소재지",),
    "name": ("명칭(종류)", "명칭"),
    "maker": ("제작자(공급자)", "제작자"),
    "made": ("제작일자(계약일자)", "제작일자"),
    "qty": ("수량", "수 량"),
}


@dataclass(frozen=True)
class MachineRow:
    mark: str | None
    location: str | None
    name: str | None
    maker: str | None
    made: str | None
    qty: str | None


def _index_of(header, names):
    wanted = {_normalize(n) for n in names}
    for i, cell in enumerate(header):
        if _normalize(cell) in wanted:
            return i
    return None


def parse(section_body: str | None) -> tuple[MachineRow, ...]:
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
                return " ".join(row[at].split()) if at is not None and len(row) > at and row[at].strip() else None
            if not cell("name"):
                continue
            out.append(MachineRow(mark=cell("mark"), location=cell("location"), name=cell("name"),
                                  maker=cell("maker"), made=cell("made"), qty=cell("qty")))
        if out:
            return tuple(out)
    return ()
