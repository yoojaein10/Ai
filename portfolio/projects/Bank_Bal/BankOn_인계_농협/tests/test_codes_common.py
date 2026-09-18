"""은행 공통 코드 변환 — 지목 별칭·건물구조 정규화."""
from __future__ import annotations

from bankon.codes import common


class TestLandCategory:
    def test_대는_대지로(self):
        assert common.land_category("대") == "대지"

    def test_그대로인_지목(self):
        assert common.land_category("공장용지") == "공장용지"

    def test_목록에_없으면_비운다(self):
        assert common.land_category("대", allowed=frozenset({"전"})) is None

    def test_빈값(self):
        assert common.land_category(None) is None and common.land_category("  ") is None


class TestStructOnly:
    def test_슬래시_지붕을_뗀다(self):
        assert common.struct_only("철근콘크리트조 / 슬라브지붕") == "철근콘크리트구조"

    def test_괄호_부기를_뗀다(self):
        assert common.struct_only("철근콘크리트구조 (철근)콘크리트지붕") == "철근콘크리트구조"

    def test_구분자_없는_지붕도_뗀다(self):
        # 실측 2656 개요: 슬래시도 괄호도 없이 `구조 지붕` 으로 붙어 온다.
        assert common.struct_only("철근콘크리트구조 철근콘크리트지붕") == "철근콘크리트구조"
        assert common.struct_only("일반철골구조 난연판넬지붕") == "일반철골구조"

    def test_지붕만_있으면_비우지_않는다(self):
        # 앞에 구조가 없으면 뗄 게 아니라 그 값이 전부다(빈 값으로 만들지 않는다).
        assert common.struct_only("슬래브지붕") == "슬래브지붕"

    def test_조를_구조로_맞춘다(self):
        assert common.struct_only("철근콘크리트조") == "철근콘크리트구조"

    def test_이미_구조면_그대로(self):
        assert common.struct_only("일반철골구조") == "일반철골구조"

    def test_구조_변형이_없는_표기는_예외(self):
        assert common.struct_only("연와조") == "연와조"
        assert common.struct_only("석조") == "석조"

    def test_빈값(self):
        assert common.struct_only(None) is None and common.struct_only("") is None


class TestZoneName:
    def test_첫_용도지역만_쓴다(self):
        # 화면은 한 칸이라 첫 것만 받는다(실측 2546).
        assert common.zone_name("제2종일반주거지역, 자연녹지지역") == "제2종일반주거지역"

    def test_내부_공백을_없앤다(self):
        # 개요는 줄바꿈 자리에 공백이 남는다(실측 2561).
        assert common.zone_name("제2종일반 주거지역") == "제2종일반주거지역"

    def test_빈값(self):
        assert common.zone_name(None) is None and common.zone_name("  ") is None


class TestBestStruct:
    def test_완전한_값을_고른다(self):
        # 명세표 gujo 가 워드랩으로 조각나면(`철근`) 개요의 완전값으로 물러선다.
        assert common.best_struct("철근", "철근콘크리트구조 (철근)콘크리트지붕") \
            == "철근콘크리트구조"

    def test_순서보다_완전성이_우선(self):
        assert common.best_struct(None, "철골철근", "철골철근콘크리트구조") \
            == "철골철근콘크리트구조"

    def test_전부_조각이면_첫_유효값(self):
        assert common.best_struct(None, "철근", "철골") == "철근"

    def test_후보가_없으면_None(self):
        assert common.best_struct(None, None) is None

    def test_기업은_원문_표기를_지킨다(self):
        # 국민 화면은 '…구조'로 통일돼 있지만 기업 화면은 원문 그대로다(실측 2682).
        assert common.struct_only("철근콘크리트조 / 슬래브지붕", to_gujo=False) == "철근콘크리트조"
        assert common.best_struct("철근", "철근콘크리트조 / 슬래브지붕", to_gujo=False) \
            == "철근콘크리트조"
        # 국민은 그대로 '구조'로 맞춘다(무회귀).
        assert common.best_struct("철근", "철근콘크리트조 / 슬래브지붕") == "철근콘크리트구조"
