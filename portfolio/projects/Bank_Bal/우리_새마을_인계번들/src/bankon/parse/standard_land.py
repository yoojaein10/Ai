"""의견서 `감정평가 개요` 의 비교표준지 표 → 표준지 소재지·공시지가·공시기준일.

뱅크온라인 국민은행 폼의 `표준지소재지` `표준지공시지가` `공시기준일` 이 여기서 온다.
**첫 섹션(대상물건 개요)에는 없다** — 담보 495건 기준 개요 1%, 의견서 전체 50%.

표는 후보를 여러 줄 보여주고 **비고에 `선정`** 이 찍힌 행이 실제 채택된 표준지다.
표시가 없으면 채우지 않는다(엉뚱한 후보가 들어가는 것보다 비는 편이 낫다).

    <caption>&lt;경기도 여주시&gt;   (공시기준일: 2023. 01. 01.)</caption>
    | 기호 | 소재지        | 면적 | 지목 | 이용상황 | 용도지역 | ... | 공시지가 | 비고 |
    | A   | 교동 BL-단-1-25 | 240.6 | 대  | 주거나지 | 1종일주 | ... | 672,800 | 선정 |
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from .outline import to_decimal, to_iso_date
from .tables import normalize_label as _normalize, iter_tables, rows_of, text_of

_CAPTION = re.compile(r"<caption[^>]*>(.*?)</caption>", re.DOTALL | re.IGNORECASE)
_BASE_DATE = re.compile(r"공시기준일\s*[:：]?\s*([^)）]+)")
# 공시기준일이 <caption> 이 아니라 표 바깥 <td>(중첩표 flatten 시 삭제됨)에 있는
# 경우가 있다. 원문(raw section_body)에서 직접 뽑는 인라인 백업.
# 연-월 구분자가 점/하이픈/'년' 이 아니라 **공백만** 인 경우도 있다(실측 2541:
# `2026 01. 01` — 연 뒤 구분자 없이 공백). 구분자를 선택적으로(있으면 그것, 없으면 공백).
_BASE_DATE_INLINE = re.compile(
    r"공시기준일[^0-9]{0,4}(\d{4}\s*[.\-년]?\s*\d{1,2}\s*[.\-월]?\s*\d{1,2})")

# 머리행 판별. `공시지가` 와 `소재지` 가 함께 있어야 비교표준지 표로 본다.
_HEADER_PRICE = ("공시지가",)
_HEADER_ADDRESS = ("소재지", "소 재 지")
_SELECTED = re.compile(r"선\s*정")


@dataclass(frozen=True)
class StandardLand:
    address: str | None = None
    price: Decimal | None = None       # 공시지가 (원/㎡)
    base_date: str | None = None       # 공시기준일 (ISO)
    zone: str | None = None
    usage: str | None = None

    @property
    def found(self) -> bool:
        return bool(self.address or self.price)


def _header_index(header: tuple[str, ...], names: tuple[str, ...]) -> int | None:
    wanted = {_normalize(n) for n in names}
    for index, cell in enumerate(header):
        if _normalize(cell) in wanted:
            return index
    return None


def _iso_date(text: str | None) -> str | None:
    """공시기준일 문자열 → ISO. 연-월-일 사이 구분자가 **공백만** 인 표기(`2026 01. 01`,
    실측 2541)도 처리 — 숫자 사이 공백을 점으로 채워 `to_iso_date` 가 읽게 한다."""
    if not text:
        return None
    normalized = re.sub(r"(\d)\s+(\d)", r"\1.\2", text)
    return to_iso_date(normalized)


def _caption_base_date(table_html: str) -> str | None:
    for caption in _CAPTION.findall(table_html):
        match = _BASE_DATE.search(text_of(caption))
        if match:
            return _iso_date(match.group(1))
    return None


def parse(section_body: str | None) -> StandardLand:
    """비교표준지 표에서 채택된 표준지를 뽑는다.

    비고에 `선정` 표시가 있으면 그 행을, 없으면 **첫 후보(기호 A)** 를 쓴다. 감정사는
    비교표준지를 관련도 순으로 나열해 기호 A(첫 행)를 주 표준지로 삼고 산정단가에도
    A를 쓴다(실측 0625·1674: 후보 2행·비고 `-` 인데 화면이 A를 채택). 단일 표준지 표도
    비고가 `-` 라 이 규칙으로 잡힌다(0668). `소재지`+`공시지가` 머리행이 없으면(비교표준지
    표가 아니면) 건너뛴다.
    """
    if not section_body:
        return StandardLand()

    inline = _BASE_DATE_INLINE.search(section_body)
    inline_date = _iso_date(inline.group(1)) if inline else None

    for table_html in iter_tables(section_body):
        rows = rows_of(table_html)
        if len(rows) < 2:
            continue
        header = rows[0]
        price_at = _header_index(header, _HEADER_PRICE)
        address_at = _header_index(header, _HEADER_ADDRESS)
        if price_at is None or address_at is None:
            continue

        zone_at = _header_index(header, ("용도지역",))
        usage_at = _header_index(header, ("이용상황",))
        base_date = _caption_base_date(table_html) or inline_date

        # 공시지가가 실제로 있는 데이터 행만 후보로.
        data = [r for r in rows[1:]
                if len(r) > price_at and to_decimal(r[price_at]) is not None]
        selected = [r for r in data
                    if any(_SELECTED.fullmatch(_normalize(cell)) for cell in r[price_at + 1:])]
        # 선정 표시가 있으면 그 행, 없으면 첫 후보(기호 A). 감정사가 관련도순으로
        # 나열해 A를 주 표준지로 쓴다(실측 0625·1674 화면=A).
        chosen = selected[0] if selected else (data[0] if data else None)
        if chosen is None:
            continue
        return StandardLand(
            address=chosen[address_at] or None,
            price=to_decimal(chosen[price_at]),
            base_date=base_date,
            zone=chosen[zone_at] if zone_at is not None and len(chosen) > zone_at else None,
            usage=chosen[usage_at] if usage_at is not None and len(chosen) > usage_at else None,
        )
    return StandardLand()
