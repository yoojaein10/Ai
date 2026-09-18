"""국민 구분건물 총세대수 ← 의견서 개요 '건물의 규모' (2788 개포동 '102호', 2026-09-09).

값 표기는 DW gam_opinion 9,451건 분포(reports/scale_values_20260909.json)에서 뽑은 실물 표본.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from bankon.mapping import kookmin
from bankon.model import DocumentContext
from bankon.parse import outline
from bankon.parse.detail import DetailRow
from bankon.parse.outline import Outline, total_units_from_scale

# 2788 대상물건 개요 — 층수 행과 건물의 규모 행이 따로 있다.
OUTLINE_2788 = """<table><tr><td>소재지</td><td>서울특별시 강남구 개포동 1234</td></tr>
<tr><td>건물용도</td><td>독립형상가</td></tr>
<tr><td>층수</td><td>지하 3층 / 지상 4층</td></tr>
<tr><td>건물의 규모</td><td>102호</td></tr></table>"""

# 층수 행 없이 규모에 층수만 있는 건 — floors 폴백은 그대로, 총세대수는 없음.
OUTLINE_SCALE_FLOORS = """<table><tr><td>건물용도</td><td>아파트</td></tr>
<tr><td>건물의 규모</td><td>지하2층 / 지상28층</td></tr></table>"""


class TestScaleParse:
    def test_2788_규모행을_층수와_따로_읽는다(self):
        result = outline.parse(OUTLINE_2788)
        assert result.floors_text == "지하 3층 / 지상 4층"
        assert result.ground_floors == 4
        assert result.scale_text == "102호"
        assert result.total_units == 102

    def test_규모에_층수만_있으면_층수_폴백은_유지하고_세대수는_없다(self):
        result = outline.parse(OUTLINE_SCALE_FLOORS)
        assert result.ground_floors == 28
        assert result.total_units is None

    def test_세대수_라벨은_규모가_없을_때_폴백(self):
        assert Outline(unit_count=10).total_units == 10
        assert Outline(unit_count=10, scale_text="24호").total_units == 24


@pytest.mark.parametrize("text, expected", [
    ("102호", 102), ("8세대", 8), ("12가구", 12), ("25개호", 25), ("총 938호수", 938), ("35객실", 35),
    ("3개단지, 총66개 호실", 66), ("204호 / 1,834세대", 1834),
    # 호·세대 병기 → 세대 우선
    ("1호 / 8세대", 8), ("8호/16세대", 16), ("11호 19세대", 19), ("근린생활시설 44호 / 아파트 212세대", 212),
    # 괄호 부기(단지 전체)는 뗀다
    ("79세대 (총 35개동, 3,391세대)", 79), ("50세대(7개동/355세대)", 50),
    # 숫자만
    ("148", 148), ("3,458", 3458),
    # 못 읽는 것 → None(수기)
    ("0", None), ("-", None), ("보통", None), ("보통.", None), ("", None), (None, None),
    ("지하2층 / 지상28층", None), ("지하 2층, 지상 28층", None), ("2025.01.21", None), ("9개동 / 761대", None),
    ("2개동", None), ("전체", None),
])
def test_total_units_from_scale(text, expected):
    assert total_units_from_scale(text) == expected


def _unit(seq, amount, area):
    return DetailRow(table="section_build0", seq_no=seq, location=f"제{seq}층 제{seq}0{seq}호",
                     area_public=Decimal(area), amount=Decimal(amount))


def test_kb_구분건물_호마다_총세대수를_넣는다():
    ctx = DocumentContext(doc_id="01-2609-3-2788", business_number="2148746436",
                          outline=Outline(address="서울특별시 강남구 개포동 1234", building_use="독립형상가",
                                          floors_text="지하 3층 / 지상 4층", scale_text="1호 / 102세대"),
                          details=(_unit("1", "100000000", "50.1"), _unit("2", "120000000", "60.2")))
    _, objects = kookmin.build_kb(ctx)
    assert [o["물건:일련번호"] for o in objects] == ["1", "2"]
    assert [o["물건:총세대수"] for o in objects] == ["102", "102"]
    assert objects[0]["물건:총층수/층수"] == "4"


def test_kb_규모가_없으면_총세대수는_비운다():
    ctx = DocumentContext(doc_id="x", business_number="2148746436", outline=Outline(building_use="아파트"),
                          details=(_unit("1", "100000000", "50.1"),))
    _, objects = kookmin.build_kb(ctx)
    assert objects[0]["물건:총세대수"] is None


def test_kb_평가방법은_물건마다_붙는다():
    # 호(구분소유물건) = 거래사례 — 라디오가 물건 패널에 있어 물건마다 눌러야 한다(2822 제보 2026-09-14)
    ctx = DocumentContext(doc_id="01-2609-3-2822", business_number="2148746436", gam_category="구분건물",
                          outline=Outline(building_use="근린생활시설"),
                          details=(_unit("1", "387000000", "50.1"), _unit("2", "357000000", "50.1")))
    _, objects = kookmin.build_kb(ctx)
    assert [o["_method"] for o in objects] == [kookmin.METHOD_COMPARISON] * 2


def test_kb_토지_필지_물건은_원가평가():
    land = DetailRow(table="land_list0", seq_no="1", jibun="299-2", category="대", area_assessed=Decimal("100"),
                     amount=Decimal("21000000"))
    ctx = DocumentContext(doc_id="x", business_number="2148746436", gam_category="토지건물", details=(land,))
    _, objects = kookmin.build_kb(ctx)
    assert objects[0]["_method"] == kookmin.METHOD_COST
