"""의견서 물건특성 표 파싱 — 실제 의견서 두 건(헤더 양식이 서로 다름)."""
from __future__ import annotations

from bankon.parse.characteristics import (
    LEASE_PRESENT,
    LEASE_UNKNOWN,
    LEASE_VACANT,
    parse,
)

# 01-2604-3-1248 — 헤더 `구 분|전문내용|대상|선택사항|세부설명`
FORM_A = """<table><tr><td>구 분</td><td>전문내용</td><td>대상</td><td>선택사항</td><td>세부설명</td></tr>
<tr><td>1</td><td>매매/분양</td><td>집합\n건물</td><td>예</td><td>본건 210,000,000원(2026.03.06.)매매계약체결</td></tr>
<tr><td>2</td><td>임대</td><td>집합\n건물</td><td>임대없음</td><td>매매로 인한 단기 공실</td></tr>
<tr><td>3</td><td>튼상가</td><td>집합\n건물</td><td>아니오</td><td>해당사항 없음.</td></tr>
<tr><td>4</td><td>오픈상가</td><td>집합\n건물</td><td>아니오</td><td>해당사항 없음.</td></tr>
<tr><td>5</td><td>공부/현황 불일치</td><td>집합\n건물</td><td>아니오</td><td>해당사항 없음.</td></tr>
<tr><td>6</td><td>제시외건물,\n종물, 부합물</td><td>집합\n건물</td><td>아니오</td><td>해당사항 없음.</td></tr>
<tr><td>7</td><td>미등기부동산</td><td>집합\n건물</td><td>아니오</td><td>해당사항 없음.</td></tr>
<tr><td>8</td><td>별도 등기 존재</td><td>집합\n건물</td><td>아니오</td><td>2016년 별도 등기 있었으나 말소</td></tr>
</table>"""

# 01-2604-3-1270 — 헤더 `구분|항목|대상|내용|세부내용`, 값이 `아니요`
FORM_B = """<table><tr><td>구분</td><td>항목</td><td>대상</td><td>내용</td><td>세부내용</td></tr>
<tr><td>1</td><td>매매/분양</td><td>집합건물</td><td>아니요</td><td>해당사항 없음</td></tr>
<tr><td>2</td><td>임대</td><td>집합건물</td><td>임대있음</td><td>임차보증금: 11,000,000원</td></tr>
<tr><td>3</td><td>튼상가</td><td>집합건물</td><td>아니요</td><td>해당사항 없음</td></tr>
<tr><td>8</td><td>별도 등기 존재</td><td>집합건물</td><td>아니요</td><td>해당사항 없음</td></tr>
</table>"""


def test_양식A를_읽는다():
    result = parse(FORM_A)
    assert result.found
    assert result.sale == "예"
    assert result.open_wall_shop == "아니오"
    assert result.mismatch == "아니오"
    assert result.extra_building == "아니오"
    assert result.unregistered == "아니오"
    assert result.separate_registry == "아니오"


def test_양식B의_아니요를_아니오로_정규화한다():
    result = parse(FORM_B)
    assert result.sale == "아니오"
    assert result.open_wall_shop == "아니오"
    assert result.separate_registry == "아니오"


def test_임대없음은_세부설명의_공실단서로_갈린다():
    assert parse(FORM_A).lease == LEASE_VACANT


def test_임대있음():
    assert parse(FORM_B).lease == LEASE_PRESENT


def test_임대없음인데_단서가_없으면_미상():
    html = """<table><tr><td>구분</td><td>항목</td><td>대상</td><td>내용</td><td>세부</td></tr>
    <tr><td>1</td><td>매매/분양</td><td>건물</td><td>아니오</td><td>-</td></tr>
    <tr><td>2</td><td>임대</td><td>건물</td><td>임대없음</td><td>-</td></tr></table>"""
    assert parse(html).lease == LEASE_UNKNOWN


def test_표가_없으면_전부_None():
    # 신한 의견서의 약 90% — 이때 호출측이 기본값을 채운다.
    result = parse("<table><tr><td>기호</td><td>지번</td></tr></table>")
    assert not result.found
    assert result.sale is None and result.lease is None


def test_입력이_없어도_죽지_않는다():
    assert not parse(None).found
    assert not parse("").found
