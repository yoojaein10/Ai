"""의견서 `그 밖의 사항` 의 물건특성 표 파싱 — 신한 담보 8종.

번호 1~8 순서가 뱅크온라인 신한 폼과 그대로 같다:

    | 구분 | 전문내용        | 대상   | 선택사항 | 세부설명                    |
    | 1   | 매매/분양       | 집합건물 | 예      | 본건 210,000,000원 매매계약체결 |
    | 2   | 임대           | 집합건물 | 임대없음 | 매매로 인한 단기 공실          |
    | 3   | 튼상가          | 집합건물 | 아니오   | 해당사항 없음                |
    ...
    | 8   | 별도 등기 존재   | 집합건물 | 아니오   | ...

헤더가 두 종류(`전문내용|선택사항` / `항목|내용`)라 **이름이 아니라 위치**로 읽는다
(2번째 셀=항목, 4번째 셀=값, 5번째 셀=세부설명).

커버리지는 낮다 — 2026년 신한 의견서 331건 중 35건(10.6%). 최근 도입된 양식이라
표가 없으면 기본값(`아니오` / 임대는 `미상`)을 쓴다.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass

_TABLE = re.compile(r"<table[^>]*>.*?</table>", re.DOTALL | re.IGNORECASE)
_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
_CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.DOTALL | re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")

# 표의 항목명 → 뱅크온라인 필드 키. 원문 표기가 흔들려서(띄어쓰기·쉼표) 공백을 지우고 맞춘다.
ITEM_KEYS: dict[str, str] = {
    "매매/분양": "sale",
    "임대": "lease",
    "튼상가": "open_wall_shop",
    "오픈상가": "open_shop",
    "공부/현황불일치": "mismatch",
    "제시외건물,종물,부합물": "extra_building",
    "제시외건물,종물/부합물": "extra_building",
    "미등기부동산": "unregistered",
    "별도등기존재": "separate_registry",
}

# 물건특성 콤보는 예/아니오 두 개뿐이다. `아니요` 표기 변형을 정규화한다.
_YES_NO = {"예": "예", "아니오": "아니오", "아니요": "아니오"}

# 임대 콤보(5지선다). 의견서는 `임대있음` / `임대없음` 까지만 적으므로
# `임대없음` 은 세부설명의 단서로 갈라야 한다.
LEASE_PRESENT = "임대있음"
LEASE_VACANT = "임대없음(공실)"
LEASE_SELF_USE = "임대없음(자가사용및자가사용예정)"
LEASE_UNKNOWN = "미상"

_SELF_USE_HINT = re.compile(r"자가|본인\s*사용|소유자\s*사용")
_VACANT_HINT = re.compile(r"공실|비어|미임대")


@dataclass(frozen=True)
class Characteristics:
    """신한 폼의 물건특성 8종. 값이 없으면 None → 호출측이 기본값을 쓴다."""

    sale: str | None = None
    lease: str | None = None
    open_wall_shop: str | None = None
    open_shop: str | None = None
    mismatch: str | None = None
    extra_building: str | None = None
    unregistered: str | None = None
    separate_registry: str | None = None

    @property
    def found(self) -> bool:
        """표를 실제로 찾았는가(하나라도 값이 있는가)."""
        return any(getattr(self, f.name) for f in self.__dataclass_fields__.values())


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub(" ", fragment))).strip()


def _key(label: str) -> str | None:
    return ITEM_KEYS.get(re.sub(r"\s+", "", label))


def _lease_value(raw: str, detail: str) -> str:
    """`임대있음` / `임대없음` → 뱅크온라인 5지선다."""
    text = re.sub(r"\s+", "", raw)
    if "임대있음" in text:
        return LEASE_PRESENT
    if "임대없음" not in text:
        return LEASE_UNKNOWN
    if _SELF_USE_HINT.search(detail):
        return LEASE_SELF_USE
    if _VACANT_HINT.search(detail):
        return LEASE_VACANT
    return LEASE_UNKNOWN


def _parse_table(table_html: str) -> dict[str, str]:
    """표 하나에서 항목→값을 뽑는다. 헤더 이름이 아니라 셀 위치로 읽는다."""
    found: dict[str, str] = {}
    for row_html in _ROW.findall(table_html):
        cells = [_text(cell) for cell in _CELL.findall(row_html)]
        if len(cells) < 4:
            continue
        key = _key(cells[1])
        if key is None:
            continue
        raw = cells[3]
        detail = cells[4] if len(cells) > 4 else ""
        found[key] = _lease_value(raw, detail) if key == "lease" else _YES_NO.get(raw, raw)
    return found


def parse(opinion_html: str | None) -> Characteristics:
    """의견서 본문(표가 HTML 로 재구성된 텍스트)에서 물건특성 표를 찾는다.

    표가 없으면 전부 None 인 Characteristics — 호출측이 기본값으로 채운다.
    """
    if not opinion_html:
        return Characteristics()

    merged: dict[str, str] = {}
    for table_html in _TABLE.findall(opinion_html):
        # 이 표가 물건특성 표인지 확인 — 고유 항목이 2개 이상 보여야 인정한다.
        parsed = _parse_table(table_html)
        if len(parsed) >= 2:
            merged.update(parsed)
    return Characteristics(**merged) if merged else Characteristics()
