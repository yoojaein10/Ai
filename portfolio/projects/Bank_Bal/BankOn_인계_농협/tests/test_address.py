"""소재지·건물명 파싱 — 실측 의견서 문장에서 따온 표본으로 검증."""
from __future__ import annotations

from bankon.parse import address


class TestBuildingName:
    def test_따옴표_짝이_어긋나도_읽는다(self):
        # 실측 2526: 여는 게 `"` 인데 닫는 게 `“` 다.
        assert address.building_name(
            '서울특별시 성동구 성수동1가 656-1110외 12필지 "서울숲엘타워“ '
            '[도로명주소] 서울특별시 성동구 아차산로 17') == "서울숲엘타워"

    def test_이름_안의_공백을_지킨다(self):
        # 실측 2586. 명세표 워드랩('부띠크'+'모나코')으론 띄어쓰기를 복원 못 한다.
        assert address.building_name(
            '서울특별시 서초구 서초동 1316-5 “부띠크 모나코”') == "부띠크 모나코"

    def test_번지_표기가_섞여도_읽는다(self):
        assert address.building_name(
            '서울특별시 구로구 구로동 222-31번지 "지플러스타워"') == "지플러스타워"

    def test_토지건은_건물명이_없다(self):
        assert address.building_name("수서동 461-17") is None
        assert address.building_name(None) is None


class TestFullAddress:
    # 실측 2683: 개요 소재지는 `수서동 461-17` 뿐이고 시군구는 본문에만 있다.
    BODY_2683 = "본건은 서울특별시 강남구 수서동 소재 지하철 3호선 인근에 위치하며 …"

    def test_본문에서_시군구까지_찾는다(self):
        assert address.full_address(self.BODY_2683, "수서동 461-17") == "서울특별시 강남구 수서동"

    def test_아는_동으로_오검출을_거른다(self):
        # 실측 2516: '계획관리지역'의 앞부분이 '…리'로 끝나 완전주소처럼 걸린다.
        body = ("인천광역시 강화군 길상면 선두리 소재 … "
                "표준지는 인천광역시 강화군 계획관리지역에 속하며 …")
        assert address.full_address(body, "선두리 89-3") == "인천광역시 강화군 길상면 선두리"

    def test_명세표_계층주소도_후보가_된다(self):
        # 실측 2543: 본문 완전주소는 사례지(금토동)뿐이고 명세표가 정답을 갖고 있다.
        body = "비교표준지는 경기도 성남시 수정구 금토동 소재 …"
        assert address.full_address(body, "시흥동 350", "경기도 성남시 수정구 시흥동") \
            == "경기도 성남시 수정구 시흥동"

    def test_대상주소가_본문에_없으면_시군구만_빌린다(self):
        # 실측 2561: 대상은 마포구 서교동인데 본문 완전주소는 사례지 합정동뿐.
        body = "거래사례는 서울특별시 마포구 합정동 소재 …"
        assert address.full_address(body, "서교동 377-18", "서울특별시") \
            == "서울특별시 마포구 서교동"

    def test_힌트가_없으면_가장_상세한_후보(self):
        # 실측 2452: 개요에 소재지 항목 자체가 없는 건.
        body = "인천광역시 연수구 송도동 소재 단독주택 …"
        assert address.full_address(body, None) == "인천광역시 연수구 송도동"

    def test_주소가_없으면_None(self):
        assert address.full_address("표는 비어 있다", "수서동 461-17") is None
        assert address.full_address(None) is None

    def test_읍면까지_포함한다(self):
        body = "경기도 김포시 통진읍 서암리 517 소재 …"
        assert address.full_address(body, "서암리 517") == "경기도 김포시 통진읍 서암리"


class TestDongNames:
    def test_지번_앞의_동리를_뽑는다(self):
        assert address.dong_names("수서동 461-17") == ("수서동",)
        assert address.dong_names("성수동1가 656-1110외 12필지") == ("성수동1가",)

    def test_여러_힌트를_순서대로(self):
        assert address.dong_names("서교동 377-18", "서울특별시 마포구 합정동") \
            == ("서교동", "합정동")
