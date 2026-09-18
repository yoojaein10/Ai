"""HTML 표 읽기 공용 유틸.

의견서 표는 평가목적·물건종류마다 구조가 완전히 다르다(토지형/구분건물형/공장형…).
그래서 **고정 위치가 아니라 라벨 셀을 찾아 그 오른쪽 값을 읽는** 방식만 쓴다.

`hwp_parser` 가 중첩표를 그대로 중첩 `<table>` 로 재구성하므로, 바깥 표만 훑으면
안쪽 표를 놓친다. `iter_tables` 는 중첩된 것까지 전부 돌려준다.
"""
from __future__ import annotations

import html
import re

_TABLE_OPEN = re.compile(r"<table[^>]*>", re.IGNORECASE)
_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
_CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.DOTALL | re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_NESTED = re.compile(r"<table[^>]*>.*?</table>", re.DOTALL | re.IGNORECASE)


def text_of(fragment: str) -> str:
    """셀 조각 → 사람이 읽는 한 줄. 중첩표는 제거하고 공백을 접는다."""
    without_nested = _NESTED.sub(" ", fragment)
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub(" ", without_nested))).strip()


def iter_tables(fragment: str) -> tuple[str, ...]:
    """중첩표를 포함해 모든 `<table>…</table>` 을 바깥→안쪽 순으로 돌려준다."""
    found: list[str] = []
    for match in _TABLE_OPEN.finditer(fragment):
        depth = 0
        position = match.start()
        cursor = position
        while cursor < len(fragment):
            opening = fragment.find("<table", cursor)
            closing = fragment.find("</table>", cursor)
            if closing == -1:
                break
            if opening != -1 and opening < closing:
                depth += 1
                cursor = opening + 6
                continue
            depth -= 1
            cursor = closing + 8
            if depth == 0:
                found.append(fragment[position:cursor])
                break
    return tuple(found)


def _own_level(table_html: str) -> str:
    """바깥 `<table>` 껍질을 벗기고 **중첩표를 통째로 제거**한다.

    이걸 안 하면 `<tr>` 정규식이 안쪽 표의 행까지 자기 행으로 읽어서, 격자형
    중첩표에서 라벨과 값이 어긋난다. 중첩표는 `iter_tables` 가 따로 돌려주므로
    여기서는 자기 층만 본다.
    """
    opening = table_html.find(">")
    closing = table_html.rfind("</table>")
    inner = table_html[opening + 1:closing] if opening != -1 and closing != -1 else table_html
    return _NESTED.sub(" ", inner)


def rows_of(table_html: str) -> tuple[tuple[str, ...], ...]:
    """표의 행 목록. 각 행은 셀 텍스트 튜플(중첩표 내용은 제외)."""
    return tuple(
        tuple(text_of(cell) for cell in _CELL.findall(row))
        for row in _ROW.findall(_own_level(table_html))
    )


# 라벨 끝에 붙는 단위 괄호: `연면적(㎡)`, `결정단가(원/㎡)`, `면 적 (㎡)`.
# 괄호를 통째로 지우면 `연면적㎡` 가 되어 `연면적` 과 안 맞으므로 **떼어낸다**.
_UNIT_SUFFIX = re.compile(r"[（(][^）)]*[）)]\s*$")


def normalize_label(label: str | None) -> str:
    """표 라벨 비교용 정규화 — 공백 제거 후 끝의 단위 괄호를 뗀다."""
    text = re.sub(r"\s+", "", label or "")
    return _UNIT_SUFFIX.sub("", text)


_normalize = normalize_label


def lookup(
    table_html: str,
    labels: tuple[str, ...],
    avoid: frozenset[str] = frozenset(),
) -> str | None:
    """표에서 라벨 셀을 찾아 그 값을 돌려준다.

    의견서 표는 두 배치가 섞여 있다:
      1) 라벨-값 나란히  `용도지역 | 제3종일반주거지역 | 토지면적 | 234.4`
      2) 머리행-데이터행  `기호 | 지 목 | 용도지역` / `1 | 대 | 준주거`

    그래서 **오른쪽 → 아래** 순으로 본다. `avoid`(다른 항목의 라벨들)에 걸리는
    값은 값이 아니라 옆 칸 머리글이므로 건너뛴다 — 이게 없으면 격자형 표에서
    `지 목` 의 값으로 옆 머리글 `용도지역` 을 집는다.
    """
    wanted = {_normalize(label) for label in labels}
    blocked = wanted | avoid
    rows = rows_of(table_html)

    for row_index, row in enumerate(rows):
        for index, cell in enumerate(row):
            if _normalize(cell) not in wanted:
                continue
            # 1) 오른쪽 (라벨 옆에 단위 셀이 끼는 경우가 있어 두 칸까지 본다)
            for value in row[index + 1:index + 3]:
                if value and _normalize(value) not in blocked:
                    return value
            # 2) 아래 (머리행-데이터행 배치)
            for below in rows[row_index + 1:row_index + 2]:
                if len(below) > index:
                    value = below[index]
                    if value and _normalize(value) not in blocked:
                        return value
    return None


def lookup_all(
    fragment: str,
    labels: tuple[str, ...],
    avoid: frozenset[str] = frozenset(),
) -> str | None:
    """조각 안의 모든 표(중첩 포함)에서 첫 번째로 찾은 값."""
    for table_html in iter_tables(fragment):
        value = lookup(table_html, labels, avoid)
        if value:
            return value
    return None


def find_table_with(fragment: str, required: tuple[str, ...]) -> str | None:
    """머리행에 지정한 라벨을 **모두** 가진 표를 찾는다(가장 안쪽 것 우선).

    참고표와 대상물건 표가 같은 컬럼명을 쓰는 경우가 있어, 구분용 컬럼을
    함께 요구해서 고른다(예: 원가법 산출표는 `결정단가` 가 있어야 한다).
    """
    wanted = {_normalize(label) for label in required}
    best: str | None = None
    for table_html in iter_tables(fragment):
        cells = {_normalize(cell) for row in rows_of(table_html) for cell in row}
        if wanted <= cells and (best is None or len(table_html) < len(best)):
            best = table_html
    return best
