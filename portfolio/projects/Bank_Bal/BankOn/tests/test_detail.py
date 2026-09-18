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


# 실측 2636(01-2608-3-2636 land_list0): 주소가 단어별로 줄바꿈되고, 조각행에 괄호표시('|')·감정평가외 부속행이 섞여 있다.
WRAPPED_ROWS = [
    {"ATTR": "CCCCCRRRRL", "GUBUN": "D", "NO": "1", "ADDR": "경기도", "JIBUN": "708-3", "JIMOK": "공장용지", "YONGDO": "계획관리지역",
     "AREA1": "4,011.2", "AREA2": "3,861.2", "AREA2LB": "<", "DANGA": "946,000", "PRICE": "3,652,695,200"},
    {"ATTR": "CCCCCRRRRL", "GUBUN": "D", "ADDR": "화성시", "AREA2LB": "|"},
    {"ATTR": "CCCCCRRCRL", "GUBUN": "D", "ADDR": "만세구", "AREA2": "150", "AREA2LB": ">", "DANGA": "-", "PRICE": "감정평가외", "BIGO": "법면 부분"},
    {"ATTR": "CCCCCRRRRL", "GUBUN": "D", "ADDR": "남양읍"},
    {"ATTR": "CCCCCRRRRL", "GUBUN": "D", "ADDR": "북양리"},
    {"ATTR": "CCCCCRRRRL", "GUBUN": "D"},
    {"ATTR": "CCCCCRRRRL", "GUBUN": "D", "NO": "가", "ADDR": "동 소", "JIBUN": "708-3", "JIMOK": "공장", "YONGDO": "일반철골구조", "BIGO": "일반건축물"},
    {"ATTR": "CCCCCRRRRL", "GUBUN": "D", "ADDR": "[도로명주소]", "YONGDO": "지상 2층"},
    {"ATTR": "CCCCCRRRRL", "GUBUN": "D", "ADDR": "경기도"},
    {"ATTR": "CCCCCRRRRL", "GUBUN": "D", "ADDR": "화성시", "YONGDO": "1층", "AREA1": "703.3", "AREA1RB": "<", "AREA2": "908.85",
     "DANGA": "1,300,000", "PRICE": "1,181,505,000", "BIGO": "1,300,000"},
    {"ATTR": "CCCCCRRRRL", "GUBUN": "D", "NO": "2", "ADDR": "동 소", "JIBUN": "708-4", "JIMOK": "도로", "YONGDO": "계획관리지역",
     "AREA2": "280.00", "DANGA": "-", "PRICE": "감정평가외"},
]


class TestWrappedAddress2636:
    def test_괄호표시_감정평가외_부속행도_주소조각(self):
        rows = detail.parse({"land_list0": WRAPPED_ROWS})
        assert rows[0].seq_no == "1" and rows[0].location == "경기도 화성시 만세구 남양읍 북양리"
        assert rows[0].amount == Decimal("3652695200")

    def test_감정평가외_부속행은_물건행이_아니다(self):
        rows = detail.parse({"land_list0": WRAPPED_ROWS})
        assert [r.seq_no for r in rows if r.seq_no] == ["1", "가", "2"]   # '만세구' 부속행이 새 행으로 끼지 않는다
        assert not any(r.location == "만세구 남양읍 북양리" for r in rows)

    def test_NO_있는_감정평가외_행은_그대로_명세행(self):
        rows = detail.parse({"land_list0": WRAPPED_ROWS})
        road = [r for r in rows if r.seq_no == "2"][0]
        assert road.category == "도로" and road.amount is None


class TestRowFlags:
    def test_감정평가외_지번행은_excluded(self):
        rows = detail.parse({"land_list0": WRAPPED_ROWS})
        road = [r for r in rows if r.seq_no == "2"][0]
        assert road.excluded and road.amount is None and road.area_assessed == Decimal("280.00")
        assert not rows[0].excluded

    def test_묶음괄호_후속행은_group_member(self):
        rows = detail.parse({"land_list0": [
            {"NO": "1", "ADDR": "경기도", "JIBUN": "1124", "JIMOK": "전", "AREA1": "240", "AREA1RB": "<", "AREA2": "2,532",
             "DANGA": "314,000", "PRICE": "795,048,000", "BIGO": "일단지"},
            {"NO": "2", "ADDR": "동  소", "JIBUN": "1124-1", "JIMOK": "전", "AREA1": "2,292", "AREA1RB": ">"},
        ]})
        assert rows[0].group_head and not rows[0].group_member
        assert rows[1].group_member and rows[1].amount is None and rows[1].area_public == Decimal("2292")

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


class TestWrappedText:
    """세로로 줄바꿈된 용도지역·구조 조각 잇기 — 온전해지면 멈춘다."""

    def test_용도지역_조각을_잇는다(self):
        # 실측 2546: '제2종' + '일반주거지역,' + '자연녹지지역'. 첫 용도지역에서 멈춘다.
        rows = detail.parse({"land_list0": [
            {"NO": "1", "JIBUN": "1408-1", "JIMOK": "전", "YONGDO": "제2종",
             "AREA1": "587", "PRICE": "1,256,180,000"},
            {"ADDR": "시흥시", "YONGDO": "일반주거지역,", "BIGO": "제2종"},
            {"ADDR": "거모동", "YONGDO": "자연녹지지역", "BIGO": "일반주거지역"},
        ]})
        assert rows[0].zone == "제2종일반주거지역,"      # '자연녹지지역'은 안 붙는다

    def test_건물유닛에서는_구조로_친다(self):
        # 같은 YONGDO 열이지만 건물 블록에서는 구조다 — '조'로 끝나면 멈춘다.
        rows = detail.parse({"land_list0": [
            {"NO": "가", "JIBUN": "1408-1", "JIMOK": "근린생활", "YONGDO": "철근"},
            {"JIMOK": "시설", "YONGDO": "콘크리트조"},
            {"YONGDO": "슬래브지붕"},
            {"YONGDO": "3층"},
        ]})
        assert rows[0].zone == "철근콘크리트조"          # 지붕·층수는 안 붙는다

    def test_이미_온전하면_안_잇는다(self):
        rows = detail.parse({"land_list0": [
            {"NO": "1", "JIMOK": "대", "YONGDO": "계획관리지역", "PRICE": "100"},
            {"YONGDO": "자연녹지지역"},
        ]})
        assert rows[0].zone == "계획관리지역"

    def test_구분건물_구조_조각을_잇는다(self):
        # 실측 2665 표제부: '철근' + '콘크리트구조' + '(철근)' + '콘크리트지붕' + '24층'
        rows = detail.parse({"section_build0": [
            {"gujo": "철근"},
            {"gujo": "콘크리트구조"},
            {"gujo": "(철근)"},
            {"gujo": "콘크리트지붕"},
            {"gujo": "24층"},
            {"NO": "가", "gujo": "(내)"},
            {"gujo": "제7층 제703호", "AREA1": "35.05", "PRICE": "150,000,000"},
        ]})
        assert rows[0].struct == "철근콘크리트구조"

    def test_구조칸의_용도지역은_구조가_아니다(self):
        # 실측 국민 0541: 같은 gujo 칸에 용도지역이 먼저 온다.
        rows = detail.parse({"section_build0": [
            {"gujo": "일반주거지역"},
            {"gujo": "철근콘크리트구조"},
            {"NO": "가"},
            {"gujo": "제3층 제301호", "AREA1": "50", "PRICE": "100,000,000"},
        ]})
        assert rows[0].struct == "철근콘크리트구조"

    def test_잘린_용도지역_머리도_구조가_아니다(self):
        # 실측 국민 1132: ', 제3종' 조각이 구조 앞에 붙으면 안 된다.
        rows = detail.parse({"section_build0": [
            {"gujo": ", 제3종"},
            {"gujo": "철근콘크리트구조"},
            {"NO": "가"},
            {"gujo": "제3층 제301호", "AREA1": "50", "PRICE": "100,000,000"},
        ]})
        assert rows[0].struct == "철근콘크리트구조"


class TestFloorAreaGroup:
    """구분건물 공부면적이 **층마다 한 행**으로 나뉘어 괄호(`<`|`>`)로 묶인 표 — 합쳐야 한다.

    실측 01-2609-3-2874(새마을 중앙하이츠빌라 203호): 1층 77.75 · 2층 77.75 · 지하층 77.75 ·
    지하층 차고 17.78 = 251.03(= 사정면적). 종전엔 금액행의 77.75 만 들어갔다.
    괄호 밖에 오는 대지권 면적(196.88)은 더하면 안 된다.
    """

    ROWS = [
        {"GUBUN": "D", "NO": "1", "ADDR": "동소", "JIBUN": "947-4", "JIMOK": "대",
         "gujo": "제2종", "AREA1": "2,953.8"},
        {"GUBUN": "D", "gujo": "일반주거지역"},
        {"GUBUN": "D", "gujo": "(내)"},
        {"GUBUN": "D", "NO": "가", "gujo": "세멘벽돌조"},
        {"GUBUN": "D", "gujo": "1층", "AREA1": "77.75", "AREA1RB": "<",
         "AREA2": "251.03", "AREA2RB": "<", "PRICE": "3,140,000,000", "BIGO": "비준가액"},
        {"GUBUN": "D", "gujo": "2층", "AREA1": "77.75", "AREA1RB": "|", "AREA2RB": "|"},
        {"GUBUN": "D", "gujo": "지하층", "AREA1": "77.75", "AREA1RB": "|", "AREA2RB": "|"},
        {"GUBUN": "D", "gujo": "지하층 차고", "AREA1": "17.78", "AREA1RB": ">", "AREA2RB": "|"},
        {"GUBUN": "D", "AREA1": "196.88", "AREA2RB": "|"},                       # 대지권(괄호 밖)
        {"GUBUN": "D", "gujo": "1 소유권대지권", "AREA1": "-----", "AREA2": "196.88", "AREA2RB": ">"},
    ]

    def test_층별_공부면적을_합친다(self):
        rows = detail.parse({"section_build0": self.ROWS})
        assert len(rows) == 1
        assert rows[0].area_public == Decimal("251.03")      # 77.75×3 + 17.78
        assert rows[0].area_assessed == Decimal("251.03")

    def test_층이_하나면_종전과_같다(self):
        single = [dict(r) for r in self.ROWS[:5]]
        single[4] = {k: v for k, v in single[4].items() if k not in ("AREA1RB", "AREA2RB")}
        rows = detail.parse({"section_build0": single})
        assert rows[0].area_public == Decimal("77.75")

    def test_괄호가_닫히지_않으면_금액행_값을_쓴다(self):
        broken = [dict(r) for r in self.ROWS[:6]]
        broken[5] = {k: v for k, v in broken[5].items() if k != "AREA1RB"}   # '>' 없이 끊김
        rows = detail.parse({"section_build0": broken})
        assert rows[0].area_public == Decimal("77.75")

    def test_묶음_안에_금액행이_또_있으면_합치지_않는다(self):
        # 층 묶음이 아니라 물건 묶음(land_list 일단지 꼴) — 다른 물건 면적을 끌어오면 안 된다.
        two = [dict(r) for r in self.ROWS]
        two[5] = {**two[5], "PRICE": "1,000,000,000"}
        rows = detail.parse({"section_build0": two})
        assert rows[0].area_public == Decimal("77.75")


class TestFloorAreaGroupLandList:
    """토지 명세표(land_list)의 건물 유닛도 같은 층 묶음이 온다 — 단, 변형이 많아 **합이
    사정면적과 같을 때만** 쓴다(전례 624건 스캔).

    실측 01-2609-3-2871(하나 잠실동 숙박시설) 단가 756,000 행: 2~9층
    98.82×5 + 84.24 + 69.66 + 32.34 = 680.34 = 사정면적. 종전엔 2층 98.82 만 들어갔다.
    """

    HEAD = {"GUBUN": "D", "NO": "1", "ADDR": "서울특별시", "JIBUN": "184-20", "JIMOK": "대",
            "YONGDO": "일반상업지역", "AREA1": "165.3", "AREA2": "165.3",
            "DANGA": "47,000,000", "PRICE": "7,769,100,000"}
    UNIT = {"GUBUN": "D", "NO": "가", "JIBUN": "위지상", "JIMOK": "숙박시설", "YONGDO": "철근"}
    FLOORS = [
        {"GUBUN": "D", "YONGDO": "2층", "AREA1": "98.82", "AREA1RB": "<", "AREA2": "680.34",
         "DANGA": "756,000", "PRICE": "514,337,040"},
        {"GUBUN": "D", "YONGDO": "3층", "AREA1": "98.82", "AREA1RB": "|"},
        {"GUBUN": "D", "YONGDO": "4층", "AREA1": "98.82", "AREA1RB": "|"},
        {"GUBUN": "D", "YONGDO": "5층", "AREA1": "98.82", "AREA1RB": "|"},
        {"GUBUN": "D", "YONGDO": "6층", "AREA1": "98.82", "AREA1RB": "|"},
        {"GUBUN": "D", "YONGDO": "7층", "AREA1": "84.24", "AREA1RB": "|"},
        {"GUBUN": "D", "YONGDO": "8층", "AREA1": "69.66", "AREA1RB": "|"},
        {"GUBUN": "D", "YONGDO": "9층", "AREA1": "32.34", "AREA1RB": ">"},
    ]

    def _rows(self, floors):
        return detail.parse({"land_list0": [self.HEAD, self.UNIT] + floors})

    def test_층별_공부면적을_합친다(self):
        rows = self._rows(self.FLOORS)
        assert [r.area_public for r in rows] == [Decimal("165.3"), None, Decimal("680.34")]
        assert rows[2].area_assessed == Decimal("680.34")

    def test_합이_사정면적과_다르면_그대로_둔다(self):
        # '2층~5층 각 298.32'(0680) 처럼 층마다라는 뜻이면 단순 합이 사정과 안 맞는다 → 손대지 않는다.
        each = [{"GUBUN": "D", "YONGDO": "1층", "AREA1": "271.72", "AREA1RB": "<",
                 "AREA2": "1,465", "DANGA": "1,240,000", "PRICE": "1,816,600,000"},
                {"GUBUN": "D", "YONGDO": "2층~5층 각", "AREA1": "298.32", "AREA1RB": ">"}]
        rows = self._rows(each)
        assert rows[2].area_public == Decimal("271.72")

    def test_일단지_묶음은_합치지_않는다(self):
        # 묶음 안 필지가 제 몫의 명세행(NO·지번·금액)이면 물건 묶음이다 — 머리 AREA2 는 합계.
        block = [
            {"GUBUN": "D", "NO": "2", "JIBUN": "299-2", "JIMOK": "답", "AREA1": "614",
             "AREA1RB": "<", "AREA2": "1240", "DANGA": "100,000", "PRICE": "124,000,000"},
            {"GUBUN": "D", "NO": "3", "JIBUN": "299-3", "JIMOK": "답", "AREA1": "626",
             "AREA1RB": ">", "PRICE": "126,000,000"},
        ]
        rows = detail.parse({"land_list0": [self.HEAD] + block})
        assert [r.area_public for r in rows[1:]] == [Decimal("614"), Decimal("626")]


class TestExcludedParts:
    """번호 없는 '감정평가외' 면적행 — 건물 평가제외 부분(옥탑)만 물건 후보로 낸다.

    하나 화면은 이걸 한 행으로 넣는다(2871: 옥탑 12.25 → 단가 1·금액 0). 반면 토지 부기
    ('도로후퇴부분'·'법면')는 공부면적이 없고 주소 조각이 붙어 있어 종전대로 물건이 아니다.
    """

    def test_옥탑은_물건_후보(self):
        parts = detail.excluded_parts({"land_list0": [
            {"YONGDO": "옥탑", "AREA1": "12.25", "AREA2": "12.25", "DANGA": "-", "PRICE": "감정평가 외"},
        ]})
        assert len(parts) == 1
        assert parts[0].area_public == Decimal("12.25") and parts[0].excluded
        assert parts[0].kind == detail.UNIT_BUILDING

    def test_토지_부기는_물건이_아니다(self):
        # 공부면적이 없다(사정면적만) + 주소 조각 — 직전 물건의 부기다.
        assert detail.excluded_parts({"land_list0": [
            {"ADDR": "장안구", "AREA2": "76", "PRICE": "감정평가외", "BIGO": "도로후퇴부분"},
        ]}) == ()

    def test_details_에는_안_섞인다(self):
        rows = detail.parse({"land_list0": [
            {"NO": "1", "JIBUN": "184-20", "AREA1": "165.3", "AREA2": "165.3", "PRICE": "7,769,100,000"},
            {"YONGDO": "옥탑", "AREA1": "12.25", "AREA2": "12.25", "PRICE": "감정평가 외"},
        ]})
        assert len(rows) == 1                      # 다른 은행 매핑은 종전 그대로
