"""mullist 파싱 — 실제 `.gam` 값(03-2509-3-1011)을 픽스처로 사용."""
from __future__ import annotations

from decimal import Decimal

from bankon.parse.mullist import find_tables, parse

REAL_ROW = {
    "ATTR": "CCCCCCLCCC", "GUBUN": "D", "NO": "1", "SNO": "가",
    "DABO_JONG": "집합건물", "DABO_JONG_SUB": "집합상가", "MUL_GUBUN": "건물",
    "JI_YOUNGDO": "철근콘크리트구조",
    "ADDR_NEW": "대구광역시 수성구 신매동 273 신매동에스앤엘메디타워 제1동 제2층 제206호",
    "YG_AREA": "제2종일반주거지역", "GONG_AREA": "98.6", "SA_AREA": "98.6",
    "P_PRICE": "480,000,000", "DUNG_NO": "1701-2018-002982",
    "DAE_NO": "2726011800-3-02730000", "DB_YEAR": "50", "SUR_YEAR": "28",
    "USE_APP_DATE": "2018.02.14",
}


def test_실제행을_구조화한다():
    rows = parse({"mullist0": [REAL_ROW]})
    assert len(rows) == 1
    row = rows[0]
    assert row.seq_no == "1"
    assert row.mark == "가"
    assert row.collateral_kind == "집합상가"
    assert row.object_kind == "건물"
    assert row.is_building and not row.is_land
    assert row.struct_or_category == "철근콘크리트구조"
    assert row.zone == "제2종일반주거지역"
    assert row.area_public == Decimal("98.6")
    assert row.amount == Decimal("480000000")   # 콤마 제거
    assert row.registry_no == "1701-2018-002982"
    assert row.useful_years == 50
    assert row.remaining_years == 28


def test_바인더번호가_붙은_테이블명을_찾는다():
    tables = {"mullist0": [], "mullist1008": [], "mullist_20": [], "land_list0": []}
    # `mullist_20` 은 서식 테이블이라 제외된다(패밀리 뒤 숫자만 허용).
    assert find_tables(tables) == ("mullist0", "mullist1008")


def test_빈행과_서식행은_건너뛴다():
    empty = {"GUBUN": "D", "ATTR": "CCC", "NO": "", "DABO_JONG_SUB": "", "ADDR_NEW": "", "P_PRICE": ""}
    rows = parse({"mullist0": [empty, REAL_ROW]})
    assert len(rows) == 1


def test_mullist가_없으면_빈결과():
    # 신한 건의 32% — 이때 담보종류·담보용도는 비워둔다.
    assert parse({"land_list0": [{"ADDR": "서울시"}]}) == ()


def test_토지행_판별():
    land = {**REAL_ROW, "MUL_GUBUN": "토지", "JI_YOUNGDO": "대"}
    row = parse({"mullist0": [land]})[0]
    assert row.is_land and not row.is_building
    assert row.struct_or_category == "대"


def test_숫자가_깨져있어도_죽지_않는다():
    broken = {**REAL_ROW, "P_PRICE": "-", "DB_YEAR": "N/A", "GONG_AREA": ""}
    row = parse({"mullist0": [broken]})[0]
    assert row.amount is None
    assert row.useful_years is None
    assert row.area_public is None
