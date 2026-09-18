"""의견서 원가법 산출표 → 내용연수·잔존연수·결정단가.

    | 기 호 | 층      | 용 도          | 재조달원가 | 잔존연수 | 내용연수 | 산정단가 | 결정단가 |
    | 가    | 지하1층  | 대피소,보일러실 | 700,000   |   16    |   45    | 248,888 | 248,000 |
    | 가    | 지상1층  | 근린생활시설    | 1,100,000 |   16    |   45    | 391,111 | 391,000 |

담보 496건 중 168건(33%) 보유 — 원가법 건에만 있는 게 정상이다(아파트처럼
거래사례비교법으로 하는 건에는 없다).

⚠️ `내용연수` 는 **참고표에도 나온다**:
  - 재조달원가 자료집 표(`55(50~60)` 형태)
  - 거래사례 배분표(`내용년수|경과년수|잔존년수` 머리행, 실측 220건)
둘 다 대상물건 값이 아니다. **`결정단가` 컬럼이 있는 표만** 대상물건 산출표다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from .outline import to_decimal, to_int
from .tables import normalize_label as _normalize, iter_tables, rows_of

# 대상물건 산출표를 참고표와 가르는 필수 컬럼.
REQUIRED_HEADERS = ("결정단가", "잔존연수", "내용연수")

_LAYER_COLUMNS = {
    "mark": ("기호", "기 호"),
    "floor": ("층", "층수"),
    "use": ("용도", "용 도", "층별용도"),
    "replacement_cost": ("재조달원가",),
    "remaining_years": ("잔존연수",),
    "useful_years": ("내용연수",),
    "unit_price": ("결정단가",),
}


@dataclass(frozen=True)
class CostLayer:
    """건물 한 층(또는 층 묶음)의 원가법 산출 결과."""

    mark: str | None
    floor: str | None
    use: str | None
    replacement_cost: Decimal | None
    remaining_years: int | None
    useful_years: int | None
    unit_price: Decimal | None


def _index_of(header: tuple[str, ...], names: tuple[str, ...]) -> int | None:
    wanted = {_normalize(n) for n in names}
    for index, cell in enumerate(header):
        if _normalize(cell) in wanted:
            return index
    return None


def _header_row(rows: tuple[tuple[str, ...], ...]) -> int | None:
    """머리행 위치. 표 맨 위에 `(단위 : 원/㎡)` 같은 안내행이 끼기도 한다."""
    wanted = {_normalize(h) for h in REQUIRED_HEADERS}
    for index, row in enumerate(rows[:4]):
        if wanted <= {_normalize(cell) for cell in row}:
            return index
    return None


def parse(section_body: str | None) -> tuple[CostLayer, ...]:
    """원가법 산출표에서 층별 행을 뽑는다. 표가 없으면 빈 튜플."""
    if not section_body:
        return ()

    for table_html in iter_tables(section_body):
        rows = rows_of(table_html)
        header_at = _header_row(rows)
        if header_at is None:
            continue
        header = rows[header_at]
        columns = {key: _index_of(header, names) for key, names in _LAYER_COLUMNS.items()}

        layers: list[CostLayer] = []
        for row in rows[header_at + 1:]:
            row = _aligned(row, len(header))
            price_at = columns["unit_price"]
            if price_at is None or len(row) <= price_at:
                continue
            unit_price = to_decimal(row[price_at])
            if unit_price is None:
                continue  # 산식·설명 행

            def cell(key: str) -> str | None:
                at = columns[key]
                return row[at] if at is not None and len(row) > at else None

            mark = cell("mark")
            if not (mark or "").strip() and layers:
                mark = layers[-1].mark          # 같은 기호의 두 번째 층/부속(2706 '다' 아래 '시멘트블럭조 450,000 11 40 …')
            layers.append(CostLayer(
                mark=mark,
                floor=cell("floor"),
                use=cell("use"),
                replacement_cost=to_decimal(cell("replacement_cost")),
                remaining_years=to_int(cell("remaining_years")),
                useful_years=to_int(cell("useful_years")),
                unit_price=unit_price,
            ))
        if layers:
            return tuple(layers)
    return ()


def _aligned(row: tuple[str, ...], width: int) -> tuple[str, ...]:
    """셀이 머리행보다 적은 행(기호·층·용도 셀이 위 행과 병합된 이어짐 행)은 숫자 열이 오른쪽에 붙어 있으므로 오른쪽 정렬해 열을 맞춘다.
    2706 실물: ['시멘트블럭조','450,000','11','40','123,750','123,000'](6셀) ← 머리행 8열. 종전엔 단가 열이 없다고 버려져 93㎡ 부속건물
    내용/잔존(40/11)을 놓쳤다(2026-09-01 발송본 대조)."""
    if len(row) >= width:
        return row
    return tuple([""] * (width - len(row))) + tuple(row)


def representative(layers: tuple[CostLayer, ...]) -> CostLayer | None:
    """폼의 내용연수/잔존연수 칸은 하나뿐이라 대표값을 고른다.

    층마다 내용·잔존연수는 같고 단가만 다른 게 보통이다(실측). 단가가 가장 큰
    층을 대표로 삼아 주된 용도가 반영되게 한다.
    """
    if not layers:
        return None
    return max(layers, key=lambda layer: layer.unit_price or Decimal(0))
