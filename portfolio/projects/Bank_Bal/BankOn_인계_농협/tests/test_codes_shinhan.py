"""신한 코드 변환 — 실제 수집한 콤보 목록을 allowed 로 넣어 검증."""
from __future__ import annotations

from bankon.codes.shinhan import (
    building_struct,
    collateral_kind,
    collateral_use,
    land_category,
)

# 화면에서 수집한 실제 목록의 일부(전체는 combo_shinhan.md).
KINDS = frozenset({
    "아파트", "단독주택", "다가구주택", "연립/빌라", "다세대주택", "기타공동주택",
    "상가주택", "일반상가", "집합상가", "대형상업시설", "일반업무시설", "집합업무시설",
    "오피스텔", "주거용오피스텔", "창고시설(일반)", "기계기구", "공장", "아파트형공장",
    "기타부동산", "대지", "도로",
})
USES = frozenset({
    "아파트", "단독주택", "연립주택", "다세대주택", "기타공동주택", "상가주택",
    "상가(중/소형)", "대형상업시설", "업무시설", "오피스텔", "숙박시설",
    "기타부동산(단독시설)", "대지", "도로", "공장", "아파트형공장",
})
STRUCTS = frozenset({
    "철근콘크리트구조", "일반철골구조", "콘크리트구조", "경량철골구조", "벽돌구조",
    "시멘트벽돌구조", "조적구조", "블럭구조", "목구조", "철골구조", "강파이프구조",
    "조립식판넬조", "시멘트블럭조",
})
CATEGORIES = frozenset({"대지", "전", "답", "임야", "공장용지", "도로", "잡종지"})


class TestCollateralKind:
    def test_그대로_일치하는_값(self):
        # DABO_JONG_SUB 의 92% 가 이 경우다.
        assert collateral_kind("집합상가", KINDS) == "집합상가"
        assert collateral_kind("아파트", KINDS) == "아파트"

    def test_미매칭_5종은_별칭으로_잇는다(self):
        assert collateral_kind("일반창고시설", KINDS) == "창고시설(일반)"
        assert collateral_kind("동산담보", KINDS) == "기계기구"
        assert collateral_kind("공장저당", KINDS) == "공장"
        assert collateral_kind("의료시설", KINDS) == "기타부동산"
        assert collateral_kind("위험물 저장 및 처리시설", KINDS) == "기타부동산"

    def test_목록에_없는_값은_비운다(self):
        assert collateral_kind("듣도보도못한것", KINDS) is None

    def test_빈값(self):
        assert collateral_kind(None, KINDS) is None
        assert collateral_kind("  ", KINDS) is None


class TestCollateralUse:
    def test_상위분류로_올린다(self):
        assert collateral_use("일반상가", USES) == "상가(중/소형)"
        assert collateral_use("집합상가", USES) == "상가(중/소형)"
        assert collateral_use("연립/빌라", USES) == "연립주택"
        assert collateral_use("다가구주택", USES) == "단독주택"
        assert collateral_use("주거용오피스텔", USES) == "오피스텔"
        assert collateral_use("일반업무시설", USES) == "업무시설"
        assert collateral_use("창고시설(일반)", USES) == "기타부동산(단독시설)"

    def test_이름이_같으면_그대로(self):
        assert collateral_use("아파트", USES) == "아파트"
        assert collateral_use("대지", USES) == "대지"
        assert collateral_use("아파트형공장", USES) == "아파트형공장"

    def test_담보용도에_없는_계열은_비운다(self):
        # 기계기구·차량·선박은 담보용도 목록 자체에 없다.
        assert collateral_use("기계기구", USES) is None


class TestBuildingStruct:
    def test_그대로_일치(self):
        assert building_struct("철근콘크리트구조", STRUCTS) == "철근콘크리트구조"
        assert building_struct("일반철골구조", STRUCTS) == "일반철골구조"

    def test_조를_구조로_정규화한다(self):
        # `.gam` 에 3만건 넘게 있는 표기 변형.
        assert building_struct("철근콘크리트조", STRUCTS) == "철근콘크리트구조"
        assert building_struct("경량철골조", STRUCTS) == "경량철골구조"
        assert building_struct("철골조", STRUCTS) == "철골구조"
        assert building_struct("벽돌조", STRUCTS) == "벽돌구조"
        assert building_struct("콘크리트조", STRUCTS) == "콘크리트구조"

    def test_오타와_표기변형을_별칭으로_잡는다(self):
        assert building_struct("철근콩크리트조", STRUCTS) == "철근콘크리트구조"
        assert building_struct("세멘벽돌조", STRUCTS) == "시멘트벽돌구조"
        assert building_struct("판넬조", STRUCTS) == "조립식판넬조"
        assert building_struct("조적조", STRUCTS) == "조적구조"

    def test_잘린_값은_비운다(self):
        # gam_detail 에 1만7천건 있는 품질 문제값 — 화면에 넣으면 안 된다.
        assert building_struct("구조", STRUCTS) is None
        assert building_struct("구조 (철근)", STRUCTS) is None


class TestLandCategory:
    def test_대를_대지로(self):
        assert land_category("대", CATEGORIES) == "대지"

    def test_나머지는_그대로(self):
        assert land_category("전", CATEGORIES) == "전"
        assert land_category("임야", CATEGORIES) == "임야"

    def test_목록에_없으면_비운다(self):
        assert land_category("없는지목", CATEGORIES) is None
