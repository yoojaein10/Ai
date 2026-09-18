"""유치실적(매출 입력) 인쇄 양식의 열 구성.

재무팀이 지정한 순서(2026-08-07):
  감정서번호 · 거래처명 · 유치자 · 순수수료 · 비율 · 배분액 · 실적인정금액 · 실입금액 · 입금일

감정서 단위 값(rowspan)과 담당자 단위 값이 번갈아 나오는 표라, 순서를 바꾸면
rowspan 위치도 같이 옮겨야 한다. 한 칸만 어긋나도 인쇄물 전체가 밀린다.
"""

import re
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "desktop" / "ui" / "allocation.js"
EXPECTED = [
    "감정서번호", "거래처명", "유치자", "순수수료",
    "비율(%)", "배분액", "실적인정금액", "실입금액", "입금일",
]


@pytest.fixture(scope="module")
def print_block():
    source = SCRIPT.read_text(encoding="utf-8")
    start = source.index("allocation-print-table")
    return source[start : source.index("</tfoot>", start)]


def test_헤더가_재무팀이_정한_순서다(print_block):
    heads = re.findall(r"<th[^>]*>([^<]+)</th>", print_block)
    assert heads == EXPECTED, heads


def test_colgroup_열수와_너비합이_맞는다(print_block):
    widths = [int(w) for w in re.findall(r'<col style="width:(\d+)%">', print_block)]
    assert len(widths) == len(EXPECTED), widths
    assert sum(widths) == 100, f"너비 합 {sum(widths)}% — 100%가 아니면 표가 어긋난다"


def test_첫_행은_아홉_칸_둘째_행부터는_네_칸이다():
    """rowspan 칸은 첫 행에만 있다. 둘째 행부터는 담당자 단위 값 네 개
    (유치자·비율·배분액·실적인정금액)만 나오고 나머지는 rowspan 이 덮는다."""
    source = SCRIPT.read_text(encoding="utf-8")
    start = source.index("const rows=items.map(doc=>doc.rows.map(")
    template = source[start : source.index("`).join('')).join('');", start)]

    # index===0 조건부 블록 안의 칸(rowspan) + 그 블록을 걷어낸 나머지 칸
    blocks = re.findall(r"\$\{index===0\?`(.*?)`:''\}", template, re.S)
    spanned = sum(len(re.findall(r"<td[ >]", chunk)) for chunk in blocks)
    always = len(re.findall(r"<td[ >]", re.sub(r"\$\{index===0\?`.*?`:''\}", "", template, flags=re.S)))
    assert spanned == 5, f"rowspan 칸 {spanned}개 (감정서번호·거래처명·순수수료·실입금액·입금일 5개여야 한다)"
    assert always == 4, f"담당자 단위 칸 {always}개 (유치자·비율·배분액·실적인정금액 4개여야 한다)"
    assert spanned + always == len(EXPECTED)


def test_합계줄_폭이_헤더와_같다(print_block):
    """colspan 을 안 고치면 합계 숫자가 엉뚱한 열 아래 찍힌다."""
    foot = print_block[print_block.index("<tfoot>") :]
    width = sum(
        int(m.group(1)) if m.group(1) else 1
        for m in re.finditer(r'<td(?:\s+colspan="(\d+)")?[^>]*>', foot)
    )
    assert width == len(EXPECTED), f"합계 폭 {width} / 헤더 {len(EXPECTED)}"


def test_승인_인쇄물_제목():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "'개인별 매출 실적 내역'" in source
