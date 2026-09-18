"""명세표 파싱 — 실제 `land_list0`(01-2607-3-2418) 구조로 검증."""
from __future__ import annotations

from decimal import Decimal

from bankon.parse import detail

# 실측: 명세행 뒤에 주소 조각 행이 이어진다.
LAND_ROWS = [
    {"ATTR": "CCCCCRRRRL", "GUBUN": "D"},                      # 빈 행
    {"ATTR": "CCCCCRRRRL", "GUBUN": "D", "NO": "1", "ADDR": "경기도", "JIBUN": "299-2",
     "JIMOK": "답", "YONGDO": "보전관리지역", "AREA1": "100", "AREA2": "100",
     "DANGA": "210,000", "PRICE": "21,000,000"},
    {"ATTR": "CCCCCRRRRL", "GUBUN": "D", "ADDR": "이천시"},       # 주소 조각
    {"ATTR": "CCCCCRRRRL", "GUBUN": "D", "ADDR": "마장면"},
    {"ATTR": "CCCCCRRRRL", "GUBUN": "D", "ADDR": "양촌리"},
    {"ATTR": "CCCCCRRRRL", "GUBUN": "D", "NO": "2", "ADDR": '"', "JIBUN": "299-8",
     "JIMOK": '"', "YONGDO": '"', "AREA1": "200", "PRICE": "42,000,000"},
]


class TestParse:
    def test_명세행만_뽑는다(self):
        rows = detail.parse({"land_list0": LAND_ROWS})
        assert len(rows) == 2                     # 빈 행·주소 조각은 제외
        assert [r.seq_no for r in rows] == ["1", "2"]

    def test_주소조각을_이어붙인다(self):
        rows = detail.parse({"land_list0": LAND_ROWS})
        assert rows[0].location == "경기도 이천시 마장면 양촌리"

    def test_동일부호는_직전행을_승계한다(self):
        rows = detail.parse({"land_list0": LAND_ROWS})
        assert rows[1].category == "답"            # JIMOK='"' → 앞 행 값
        assert rows[1].zone == "보전관리지역"

    def test_숫자를_변환한다(self):
        row = detail.parse({"land_list0": LAND_ROWS})[0]
        assert row.area_public == Decimal("100")
        assert row.unit_price == Decimal("210000")   # 콤마 제거
        assert row.amount == Decimal("21000000")

    def test_패밀리_정규식(self):
        tables = {"land_list0": LAND_ROWS, "land_list1008": LAND_ROWS,
                  "land_list_20": LAND_ROWS, "cover0": LAND_ROWS}
        names = {r.table for r in detail.parse(tables)}
        assert names == {"land_list0", "land_list1008"}   # `_2` 서식표·표지 제외

    def test_토지건물_구분(self):
        # 구분건물 명세: 유닛머리(NO='가', 구조) + 가격행(제N층 제N호, PRICE).
        land = detail.parse({"land_list0": LAND_ROWS})[0]
        build = detail.parse({"section_build0": [
            {"NO": "가", "gujo": "철근콘크리트조"},
            {"gujo": "제3층 제301호", "AREA1": "50", "AREA2": "50", "PRICE": "100000000"}]})[0]
        assert land.is_land and not land.is_building
        assert build.is_building and not build.is_land
        assert build.struct == "철근콘크리트조"

    def test_명세표가_없으면_빈결과(self):
        assert detail.parse({"cover0": [{"a": 1}]}) == ()

    def test_묶음괄호_머리행을_표시한다(self):
        # 실측 0668: 여는괄호('<') 머리행의 AREA2/PRICE 는 두 필지 묶음 합계.
        rows = detail.parse({"land_list0": [
            {"NO": "1", "JIBUN": "368-18", "AREA1": "749", "AREA1RB": "<",
             "AREA2": "895", "DANGA": "2,490,000", "PRICE": "2,228,550,000"},
            {"NO": "2", "JIBUN": "373-6", "AREA1": "146", "AREA1RB": ">"},
        ]})
        assert rows[0].group_head is True          # 여는괄호 → 머리행
        assert rows[1].group_head is False

    def test_괄호없는_행은_머리행이_아니다(self):
        rows = detail.parse({"land_list0": LAND_ROWS})
        assert all(r.group_head is False for r in rows)

    def test_구분건물_다물건을_유닛별로_나눈다(self):
        # 실측 1642: 유닛머리(가/나) + 가격행(제N층 제N호, PRICE). 토지행(NO=숫자)=경계.
        rows = detail.parse({"section_build0": [
            {"JIBUN": "202-5"},                                    # 표제부 지번
            {"NO": "1", "JIMOK": "공장용지", "AREA1": "15786.5"},   # 토지행(경계)
            {"NO": "가", "gujo": "철근콘크리트구조"},
            {"gujo": "제2층 제3-207호", "AREA1": "63.35", "AREA2": "63.35",
             "PRICE": "221,000,000"},
            {"NO": "나", "gujo": "철근콘크리트구조"},
            {"gujo": "제2층 제3-208호", "AREA1": "66.03", "AREA2": "66.03",
             "PRICE": "231,000,000"}]})
        assert [str(r.amount) for r in rows] == ["221000000", "231000000"]
        assert rows[0].seq_no == "가" and rows[0].struct == "철근콘크리트구조"
        assert rows[0].location == "제2층 제3-207호"
        assert rows[0].jibun == "202-5"                            # 표제부 공통 지번

    def test_다물건은_화면순번으로_고른다(self):
        rows = detail.parse({"section_build0": [
            {"NO": "가", "gujo": "철근콘크리트구조"},
            {"gujo": "제2층 제3-207호", "AREA1": "63.35", "PRICE": "221,000,000"},
            {"NO": "나", "gujo": "철근콘크리트구조"},
            {"gujo": "제2층 제3-208호", "AREA1": "66.03", "PRICE": "231,000,000"}]})
        assert detail.for_sequence(rows, "1").amount == Decimal("221000000")
        assert detail.for_sequence(rows, "2").amount == Decimal("231000000")
        assert detail.for_sequence(rows, None).amount == Decimal("221000000")   # 기본=첫물건

    def test_집계형은_총액행만_남고_감지된다(self):
        rows = detail.parse({"section_build0": [{"NO": "", "JIBUN": ""},
                                                {"PRICE": "25,607,000,000"}]})
        assert len(rows) == 1 and rows[0].amount == Decimal("25607000000")
        assert detail.is_rollup_only(rows) is True
        assert detail.is_rollup_only(detail.parse({"land_list0": LAND_ROWS})) is False


class TestUnitKind:
    """토지 명세표의 블록 머리 — 숫자=필지(토지), 한글 한 글자=그 지상 건물."""

    # 실측 2516 축약: NO=1 '대' 필지 + 접도구역 소분행 + NO=가 제2종근린생활시설 건물.
    # 건물 유닛 행에서는 JIMOK 이 건물용도, YONGDO 가 건물구조라 지목·용도지역이 아니다.
    MIXED = [
        {"NO": "1", "ADDR": "인천광역시", "JIBUN": "89-3", "JIMOK": "대",
         "YONGDO": "계획관리지역", "AREA1": "4,824", "AREA2": "4,554",
         "DANGA": "517,000", "PRICE": "2,354,418,000"},
        {"AREA2": "270", "DANGA": "414,000", "PRICE": "111,780,000", "BIGO": "접도구역"},
        {"NO": "가", "ADDR": "동소", "JIBUN": "89-3", "JIMOK": "제2종근린",
         "YONGDO": "일반철골구조"},
        {"AREA1": "462", "AREA2": "462", "DANGA": "1,100,000", "PRICE": "508,200,000"},
    ]

    def test_숫자머리는_토지_한글머리는_건물(self):
        rows = detail.parse({"land_list0": self.MIXED})
        assert [r.unit_kind for r in rows] == [
            detail.UNIT_LAND, detail.UNIT_LAND, detail.UNIT_BUILDING, detail.UNIT_BUILDING]

    def test_금액행은_블록_머리에서_종류를_물려받는다(self):
        # 접도구역 소분행은 지목칸이 비어 있어도 NO=1 필지 소속이라 토지다(실측 2516).
        rows = detail.parse({"land_list0": self.MIXED})
        접도구역 = next(r for r in rows if r.amount == Decimal("111780000"))
        assert 접도구역.category is None and 접도구역.kind == detail.UNIT_LAND
        건물금액 = next(r for r in rows if r.amount == Decimal("508200000"))
        assert 건물금액.kind == detail.UNIT_BUILDING

    def test_land_list_인데_토지가_없을_수_있다(self):
        # 실측 2452: 단독주택 한 채뿐인 문서 — 테이블은 land_list 지만 물건은 건물.
        rows = detail.parse({"land_list0": [
            {"NO": "가", "ADDR": "인천광역시", "JIBUN": "117-97", "JIMOK": "단독주택",
             "YONGDO": "철근"},
            {"AREA1": "122.6", "AREA2": "122.6", "PRICE": "253,782,000"}]})
        assert all(r.is_land for r in rows)              # 테이블은 토지계
        assert all(r.kind == detail.UNIT_BUILDING for r in rows)   # 물건은 건물

    def test_구분건물은_항상_건물(self):
        rows = detail.parse({"section_build0": [
            {"NO": "가", "gujo": "철근콘크리트구조"},
            {"gujo": "제7층 제703호", "AREA1": "116.3", "PRICE": "2,024,000,000"}]})
        assert rows[0].kind == detail.UNIT_BUILDING

    def test_mullist_는_유닛규칙을_쓰지_않는다(self):
        # 신한 물건행은 번호 관례가 달라 블록 머리 규칙 대상이 아니다(무회귀).
        rows = detail.parse({"mullist0": [
            {"NO": "1", "JIBUN": "299-2", "PRICE": "21,000,000"}]})
        assert rows[0].unit_kind is None

    def test_머리가_없으면_테이블로_추정한다(self):
        rows = detail.parse({"land_list0": [{"JIBUN": "299-2", "PRICE": "21,000,000"}]})
        assert rows[0].unit_kind is None and rows[0].kind == detail.UNIT_LAND


class TestPick:
    def test_순번으로_고른다(self):
        rows = detail.parse({"land_list0": LAND_ROWS})
        assert detail.for_sequence(rows, "2").jibun == "299-8"

    def test_순번이_없으면_첫행(self):
        rows = detail.parse({"land_list0": LAND_ROWS})
        assert detail.for_sequence(rows, None).seq_no == "1"
        assert detail.for_sequence(rows, "99").seq_no == "1"   # 없으면 첫 행

    def test_빈_목록(self):
        assert detail.for_sequence((), "1") is None
