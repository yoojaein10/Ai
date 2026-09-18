"""의견서 문단 → 섹션 분리. GamJun `extractor._walk_opinion` 에서 이식.

의견서는 제목이 그냥 문단으로 오기도 하고, **번호셀+제목셀로 된 작은 표**(박스형
제목)로 오기도 한다. 후자를 놓치면 섹션이 통째로 뭉개진다.

BankOn 이 쓰는 섹션:
    대상물건 개요      → 소재지·구조·층수·사용승인일자 (parse/outline.py)
    감정평가 개요      → 비교표준지 표             (parse/standard_land.py)
    감정평가액 산출 과정 → 원가법 산출표            (parse/cost.py)
    그 밖의 사항       → 물건특성 8종             (parse/characteristics.py)
"""
from __future__ import annotations

import re
from dataclasses import dataclass

KNOWN_HEADINGS: frozenset[str] = frozenset({
    "대상물건 개요",
    "감정평가 개요",
    "기준가치 및 감정평가조건",
    "감정평가액 산출 근거",
    "감정평가액 산출 과정",
    "감정평가액 결정",
    "그 밖의 사항",
    "그밖의 사항",
})

_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL)
# 제목 박스로 인정할 최대 셀 수. 본문 데이터 표에 제목과 같은 글자가 있어도
# 셀이 많으면 제목으로 보지 않는다.
_MAX_HEADING_CELLS = 3


@dataclass(frozen=True)
class Section:
    title: str
    body: str

    @property
    def tables(self) -> tuple[str, ...]:
        return tuple(re.findall(r"<table[^>]*>.*?</table>", self.body, re.DOTALL))


def _table_heading(paragraph: str) -> str | None:
    """박스형 제목(작은 표에 담긴 대분류 제목) 감지."""
    if not paragraph.startswith("<table"):
        return None
    cells = _CELL.findall(paragraph)
    if not cells or len(cells) > _MAX_HEADING_CELLS:
        return None
    for cell in cells:
        text = cell.strip()
        if text in KNOWN_HEADINGS:
            return text
    return None


def split(paragraphs: tuple[str, ...] | list[str]) -> tuple[Section, ...]:
    """문단 목록을 섹션으로 나눈다. 제목 이전의 내용은 버린다(서식·표지)."""
    sections: list[Section] = []
    title: str | None = None
    body: list[str] = []

    for paragraph in paragraphs:
        text = paragraph.strip()
        if not text:
            continue
        heading = text if text in KNOWN_HEADINGS else _table_heading(text)
        if heading:
            if title is not None and body:
                sections.append(Section(title, "\n".join(body)))
            title, body = heading, []
            continue
        body.append(text)

    if title is not None and body:
        sections.append(Section(title, "\n".join(body)))
    return tuple(sections)


def find(sections: tuple[Section, ...], title: str) -> Section | None:
    """제목이 같은 섹션 중 **본문이 가장 긴 것**.

    같은 제목이 여러 번 나오는 문서가 있다(감정평가액 결정 등). 내용이 있는 쪽을 쓴다.
    """
    matched = [s for s in sections if s.title == title]
    if not matched:
        return None
    return max(matched, key=lambda s: len(s.body))
