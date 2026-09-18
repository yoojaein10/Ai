"""의견서 '대상물건 개요' → '2. 건물' 표: 기호별 소재지·용도·구조·연면적·층수·**사용승인일자**.

    | 기호 | 소재지        | 용 도              | 구조/지붕            | 연면적(㎡) | 층 수   | 사용승인일자 |
    | 가   | 양촌리 299-3  | 동·식물관련시설(축사) | 일반철골구조/일반철골구조 | 281.75    | 지상 1층 | 2018.06.26 |

동마다 준공일이 달라 outline(대표값 하나)로는 안 된다(2418: 라·마 2019.05.10, 바·사 2013.01.18 — 화면 실물과 일치,
사용자 지적 2026-08-26). 기호 = 명세표 건물 머리행 NO('가','나'…)와 같다.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .outline import to_decimal, to_iso_date
from .tables import iter_tables, normalize_label as _normalize, rows_of

REQUIRED_HEADERS = ("기호", "사용승인일자")
_COLUMNS = {
    "mark": ("기호", "기 호"),
    "location": ("소재지",),
    "use": ("용도", "용 도", "공부상 용도", "공부상용도", "주용도"),   # 2513 실물 헤더 '공부상 용도(현황 용도)'
    "struct": ("구조/지붕", "구조"),
    "area_total": ("연면적(㎡)", "연면적"),
    "floors": ("층수", "층 수"),
    "approval_date": ("사용승인일자", "사용승인일"),
}


@dataclass(frozen=True)
class BuildingRow:
    mark: str | None
    location: str | None
    use: str | None
    struct: str | None
    area_total: Decimal | None
    floors: str | None
    approval_date: str | None      # ISO


def _index_of(header, names, *, taken=()):
    """헤더에서 컬럼 위치. 정확 일치 우선, 없으면 **부분 일치**로 한 번 더.

    표 머리글이 문서마다 다르다 — `용 도` / `공부상 용도(현황 용도)`(2513 실물 2026-09-17) /
    `구조/지붕` / `구조`. 정확 일치만 보면 못 찾아 그 칸이 통째로 비었다(2513 물건종류 미판정).
    부분 일치는 이미 다른 키가 가져간 칸(taken)은 건너뛴다.
    """
    wanted = {_normalize(n) for n in names}
    for i, cell in enumerate(header):
        if _normalize(cell) in wanted:
            return i
    for i, cell in enumerate(header):
        if i in taken:
            continue
        text = _normalize(cell)
        if text and any(w in text for w in wanted):
            return i
    return None


def parse(section_body: str | None) -> tuple[BuildingRow, ...]:
    if not section_body:
        return ()
    wanted = {_normalize(h) for h in REQUIRED_HEADERS}
    for table_html in iter_tables(section_body):
        rows = rows_of(table_html)
        header_at = next((i for i, r in enumerate(rows[:3]) if wanted <= {_normalize(c) for c in r}), None)
        if header_at is None:
            continue
        header = rows[header_at]
        cols: dict[str, int | None] = {}
        for key, names in _COLUMNS.items():       # 정확 일치가 먼저 자리를 잡고, 부분 일치는 남은 칸에서만
            cols[key] = _index_of(header, names, taken={i for i in cols.values() if i is not None})
        out = []
        for row in rows[header_at + 1:]:
            def cell(key):
                at = cols[key]
                return row[at].strip() if at is not None and len(row) > at else None
            mark = cell("mark")
            if not mark or len(mark) > 2:
                continue
            out.append(BuildingRow(
                mark=mark, location=cell("location"), use=cell("use"),
                struct=(cell("struct") or "").split("/")[0].strip().replace("\n", "") or None,
                area_total=to_decimal(cell("area_total")), floors=cell("floors"),
                approval_date=to_iso_date(cell("approval_date")),
            ))
        if out:
            return tuple(out)
    return ()


def by_mark(rows: tuple[BuildingRow, ...], mark: str | None) -> BuildingRow | None:
    if not mark:
        return None
    return next((r for r in rows if r.mark == mark), None)
