"""기업은행 담보(TBNKKIB24DAMB) 매핑 — 실측 문서 구조를 축약해 검증.

캐시 추출물 회귀검사는 `tools/check_ibk_offline.py`(DB 필요)가 맡고, 여기서는 DB 없이
매핑 규칙만 고정한다. 행 구조는 실제 `.gam` 명세표(문서번호를 주석에 표기)에서 따왔다.
"""
from __future__ import annotations

from decimal import Decimal

from bankon.mapping import ibk
from bankon.model import DocumentContext, Fee, Parties
from bankon.parse import detail
from bankon.parse.outline import Outline
from bankon.sources.apw import Jibun


def context(tables: dict, **kwargs) -> DocumentContext:
    fields = {
        "doc_id": "01-2608-3-0000",
        "business_number": "2148746436",
        "details": detail.parse(tables),
    }
    fields.update(kwargs)
    return DocumentContext(**fields)


# 실측 2531: 토지 2필지(공장용지, 일단지 묶음) + 공장 3개층 + 성형기 1대.
MIXED_2531 = {
    "land_list0": [
        {"NO": "1", "ADDR": "경기도", "JIBUN": "506-9", "JIMOK": "공장용지",
         "YONGDO": "계획관리지역", "AREA1": "1,428", "AREA1RB": "<", "AREA2": "2,906",
         "DANGA": "1,130,000", "PRICE": "3,283,780,000", "BIGO": "일단지"},
        {"NO": "2", "ADDR": "동 소", "JIBUN": "506-31", "JIMOK": "공장용지",
         "YONGDO": "계획관리지역", "AREA1": "1,478", "AREA1RB": ">"},
        {"NO": "가", "ADDR": "동소", "JIBUN": "506-9,", "JIMOK": "공장", "YONGDO": "철골조"},
        {"JIMOK": "공장", "YONGDO": "1층", "AREA1": "966.94", "AREA2": "966.94",
         "DANGA": "285,000", "PRICE": "275,577,900"},
        {"JIMOK": "공장", "YONGDO": "2층", "AREA1": "333.3", "AREA2": "267.8",
         "DANGA": "285,000", "PRICE": "76,323,000"},
        {"JIMOK": "공장", "YONGDO": "3층", "AREA1": "188.2", "AREA2": "188.2",
         "DANGA": "391,000", "PRICE": "73,586,200"},
    ],
    "detail_machin0": [
        {"NO": "1", "machine_detail": "자동 진공 고무성형기", "PRICE": "69,400,000"},
    ],
}


class TestAmountSplit:
    def test_토지_건물_기계를_나눈다(self):
        values = ibk.build(context(MIXED_2531))
        assert values["토지평가금액"] == "3283780000"
        assert values["건물평가금액"] == "425487100"      # 275,577,900+76,323,000+73,586,200
        assert values["기계기구평가금액"] == "69400000"
        assert values["기타평가금액"] == "0"

    def test_분리합이_총감정평가액과_맞는다(self):
        # 분리는 명세행, 총액은 gam_info.price — 서로 다른 소스라 교차검증이 된다.
        total = Decimal("3778667100")
        values = ibk.build(context(MIXED_2531, total_amount=total))
        parts = sum(int(values[k]) for k in
                    ("토지평가금액", "건물평가금액", "기계기구평가금액", "기타평가금액"))
        assert parts == int(total)

    def test_필지_소분행은_토지다(self):
        # 실측 2516: NO=1 '대' 필지 아래 접도구역 소분행 — 지목칸이 비어도 토지.
        values = ibk.build(context({"land_list0": [
            {"NO": "1", "JIBUN": "89-3", "JIMOK": "대", "YONGDO": "계획관리지역",
             "AREA1": "4,824", "AREA2": "4,554", "PRICE": "2,354,418,000"},
            {"AREA2": "270", "PRICE": "111,780,000", "BIGO": "접도구역"},
        ]}))
        assert values["토지평가금액"] == "2466198000"     # 2,354,418,000+111,780,000
        assert values["건물평가금액"] == "0"

    def test_선박은_기타로_간다(self):
        # 실측 2471: 모터보트 — 부동산 칸이 아니라 기타평가금액.
        values = ibk.build(context({"app_ship0": [
            {"NO": "1", "A1": "카이로스", "PRICE": "552,232,000"}]}))
        assert values["기타평가금액"] == "552232000"
        assert values["토지평가금액"] == values["건물평가금액"] == "0"


class TestPropertyKind:
    def test_토지_물건(self):
        values = ibk.build(context(MIXED_2531))
        assert values["부동산구분"] == "토지"
        assert values["공부지목"] == "공장용지"
        assert values["용도지역"] == "계획관리지역"

    def test_land_list_건물만_있으면_건물이다(self):
        # 실측 2452: 단독주택 한 채. 테이블은 land_list 지만 물건은 건물이다.
        values = ibk.build(context({"land_list0": [
            {"NO": "가", "JIBUN": "117-97", "JIMOK": "단독주택", "YONGDO": "철근"},
            {"AREA1": "122.6", "AREA2": "122.6", "PRICE": "253,782,000"},
        ]}, outline=Outline(zone="제1종일반주거지역")))
        assert values["부동산구분"] == "건물"
        # 건물 유닛 행의 JIMOK/YONGDO 는 건물용도·건물구조라 지목·용도지역이 아니다.
        assert values["공부지목"] is None
        assert values["용도지역"] == "제1종일반주거지역"     # 의견서 개요로 물러선다

    def test_구분건물은_집합건물(self):
        # 실측 2526: 지식산업센터 2유닛.
        values = ibk.build(context({"section_build0": [
            {"NO": "가", "gujo": "철근콘크리트구조"},
            {"gujo": "제7층 제703호", "AREA1": "116.3", "AREA2": "116.3",
             "PRICE": "2,024,000,000"}]}))
        assert values["부동산구분"] == "집합건물"
        assert values["건물평가금액"] == "2024000000"


class TestSectionDetail:
    """집합건물 상세 — 실폼 2526 대조로 확정한 칸들."""

    SECTION = {"section_build0": [
        {"NO": "가", "gujo": "철근콘크리트구조"},
        {"gujo": "제7층 제703호", "AREA1": "116.3", "AREA2": "116.3",
         "PRICE": "2,024,000,000"}]}
    OUTLINE = Outline(
        address='서울특별시 성동구 성수동1가 656-1110외 12필지 "서울숲엘타워“',
        struct="철근콘크리트구조 (철근)콘크리트지붕",
        building_use="공장(지식산업센터) 및 지원시설", approval_date="2016-02-05")

    def test_건물명은_개요_따옴표에서(self):
        values = ibk.build(context(self.SECTION, outline=self.OUTLINE))
        assert values["건 물 명"] == "서울숲엘타워"        # 실폼 화면값과 일치

    def test_건물구조와_전용면적(self):
        values = ibk.build(context(self.SECTION, outline=self.OUTLINE))
        assert values["건물구조"] == "철근콘크리트구조"
        assert values["공부면적(전용면적)"] == "116.30"
        assert values["사정면적"] == "116.30"

    def test_구분건물엔_공부면적_칸이_없다(self):
        # 폼이 물건 종류에 따라 바뀐다 — 구분건물 폼엔 `공부면적(전용면적)` 만 있다.
        values = ibk.build(context(self.SECTION, outline=self.OUTLINE))
        assert values["공부면적"] is None

    def test_준공일자(self):
        values = ibk.build(context(self.SECTION, outline=self.OUTLINE))
        assert values["준공일자"] == "2016-02-05"

    def test_토지건은_건물칸을_비운다(self):
        values = ibk.build(context({"land_list0": [
            {"NO": "1", "JIBUN": "461-17", "JIMOK": "대", "PRICE": "5,024,400,000"}]},
            outline=Outline(struct="철근콘크리트구조", approval_date="2016-02-05")))
        assert values["건물구조"] is None and values["준공일자"] is None
        assert values["공부면적(전용면적)"] is None

    def test_구조는_원문_표기를_지킨다(self):
        # 실측 2682: 화면=`철근콘크리트조`. 국민처럼 '구조'로 바꾸면 안 된다.
        values = ibk.build(context({"section_build0": [
            {"gujo": "제3층 제301호", "AREA1": "28.08", "PRICE": "295,000,000"}]},
            outline=Outline(struct="철근콘크리트조 / 슬래브지붕")))
        assert values["건물구조"] == "철근콘크리트조"

    def test_기계전용_문서엔_건물칸을_비운다(self):
        # 실측 2416: 태양광발전설비뿐인데 개요 구조가 새어 들어가면 안 된다.
        values = ibk.build(context({"detail_machin0": [
            {"NO": "1", "machine_detail": "태양광발전설비", "PRICE": "363,000,000"}]},
            outline=Outline(struct="일반철골구조 기타지붕", approval_date="2009-12-28")))
        assert values["건물구조"] is None and values["준공일자"] is None

    # 물건종류는 **부동산 물건이 있을 때만** 낸다 — 아래 표본을 붙여 준다.
    LAND_ROW = {"land_list0": [
        {"NO": "1", "JIBUN": "100", "JIMOK": "대", "AREA1": "100", "PRICE": "1,000"}]}

    def test_물건종류_공업용은_공장으로(self):
        values = ibk.build(context(self.LAND_ROW, outline=Outline(usage="공업용")))
        assert values[ibk.BOX_KIND_TEXT] == "공장"

    def test_물건종류_단일명사는_그대로(self):
        for name in ("단독주택", "전", "공장"):
            values = ibk.build(context(self.LAND_ROW, outline=Outline(usage=name)))
            assert values[ibk.BOX_KIND_TEXT] == name

    def test_물건종류_이용상황_용어는_비운다(self):
        # 실측: 같은 '공업나지'가 화면에선 2587=공장 / 2543=대(垈) — 결정 불가.
        for term in ("상업용", "공업나지", "공업기타"):
            values = ibk.build(context(self.LAND_ROW, outline=Outline(usage=term)))
            assert values[ibk.BOX_KIND_TEXT] is None, term

    def test_물건종류_복합서술은_비운다(self):
        # 화면은 그중 하나만 고른다(2682→근린생활시설, 2586→오피스텔).
        for text in ("주택 및 근린생활시설",
                     "업무시설(오피스텔), 판매시설(상점), 제1,2종근린생활시설",
                     "공장(지식산업센터) 및 지원시설"):
            values = ibk.build(context(self.LAND_ROW, outline=Outline(building_use=text)))
            assert values[ibk.BOX_KIND_TEXT] is None, text

    def test_기계선박_전용문서는_물건종류를_비운다(self):
        # 부동산 명세행이 없는 문서. 화면은 `국산기계`·`구축물` 처럼 기계 어휘를 쓴다
        # (실측 2416: 개요 이용상황 '공업용' → 우리 '공장' / 화면 '국산기계').
        values = ibk.build(context({}, outline=Outline(usage="공업용")))
        assert values[ibk.BOX_KIND_TEXT] is None
        assert values[ibk.BOX_LEGAL_CODE] is None


class TestAreaAndZone:
    def test_공부면적은_사정과_다를_수_있다(self):
        # 실측 2561: 공부 277.70 / 사정 267.75 (차액 9.95 = 감정평가외 부분).
        values = ibk.build(context({"land_list0": [
            {"NO": "1", "JIBUN": "377-18", "JIMOK": "대", "YONGDO": "제2종",
             "AREA1": "277.7", "AREA2": "267.75", "PRICE": "4,658,850,000"},
            {"AREA2": "9.95"},                       # 금액 없는 감정평가외 소분
        ]}))
        assert values["공부면적"] == "277.70"
        assert values["사정면적"] == "267.75"

    def test_묶음머리는_공부도_블록합을_쓴다(self):
        # 실측 2531 일단지: AREA1(1,428)은 head 필지 몫뿐이고 묶음 총면적이 AREA2.
        values = ibk.build(context({"land_list0": [
            {"NO": "1", "JIBUN": "506-9", "JIMOK": "공장용지", "AREA1": "1,428",
             "AREA1RB": "<", "AREA2": "2,906", "PRICE": "3,283,780,000"},
            {"NO": "2", "JIBUN": "506-31", "JIMOK": "공장용지", "AREA1": "1,478",
             "AREA1RB": ">"},
        ]}))
        assert values["공부면적"] == "2906.00" and values["사정면적"] == "2906.00"

    def test_묶음머리라도_AREA1이_총면적이면_그걸_쓴다(self):
        # 실측 2412: AREA1 3,181 이 묶음 총 공부면적이고 사정 3,144.20 은 감정평가외를 뺀 값.
        # 무조건 사정(블록합)을 쓰면 화면(3,181)과 어긋난다 → 둘 중 큰 쪽.
        values = ibk.build(context({"land_list0": [
            {"NO": "1", "JIBUN": "102-11", "JIMOK": "대", "AREA1": "3,181",
             "AREA1RB": "<", "AREA2": "3,144.2", "DANGA": "1,310,000",
             "PRICE": "4,118,902,000"},
            {"NO": "2", "JIBUN": "102-13", "JIMOK": "대", "AREA1": "394", "AREA1RB": ">"},
        ]}))
        assert values["공부면적"] == "3181.00" and values["사정면적"] == "3144.20"

    def test_소분을_합친_물건은_단가를_비운다(self):
        # 실측 2516: 필지 517,000 + 접도구역 소분 414,000 — 단가가 하나가 아니라 화면도 0.
        values = ibk.build(context({"land_list0": [
            {"NO": "1", "JIBUN": "89-3", "JIMOK": "대", "AREA1": "4,824",
             "AREA2": "4,554", "DANGA": "517,000", "PRICE": "2,354,418,000"},
            {"AREA2": "270", "DANGA": "414,000", "PRICE": "111,780,000"},
        ]}))
        assert values["평가단가"] is None
        assert values["감정평가액"] == "2466198000"

    def test_land_list에_실린_건물은_블록합산하지_않는다(self):
        """실측 2452 — 단독주택 3개 층이 `land_list` 에 온다.

        `is_land`(테이블)로 가르면 건물 유닛까지 소분 합산해 화면(유닛 하나)과 어긋난다
        (사정 496.69 / 화면 122.60). `kind`(블록 머리)로 갈라야 맞는다.
        """
        tables = {"land_list0": [
            {"NO": "가", "JIBUN": "117-97", "JIMOK": "단독주택", "YONGDO": "철근"},
            {"YONGDO": "지1층", "AREA1": "122.6", "AREA2": "122.6",
             "DANGA": "2,070,000", "PRICE": "253,782,000"},
            {"YONGDO": "지1층", "AREA1": "99.23", "AREA2": "99.23",
             "DANGA": "3,400,000", "PRICE": "337,382,000"},
        ]}
        values = ibk.build(context(tables), "1")
        assert values["사정면적"] == "122.60"
        assert values["감정평가액"] == "253782000"
        assert values["평가단가"] == "2070000"
        # 건물 물건이므로 전용면적 칸을 쓴다(건물형 폼엔 `공부면적` 칸이 없다).
        assert values["공부면적(전용면적)"] == "122.60"
        assert values["공부면적"] is None

    def test_소분이_없으면_단가를_그대로(self):
        values = ibk.build(context({"land_list0": [
            {"NO": "1", "JIBUN": "89-3", "JIMOK": "대", "AREA1": "100",
             "AREA2": "100", "DANGA": "517,000", "PRICE": "51,700,000"}]}))
        assert values["평가단가"] == "517000"

    def test_용도지역이_잘렸으면_개요로_물러선다(self):
        # 명세 조각('제2종')만 있고 이을 조각이 없는 문서 — 개요의 온전한 값을 쓴다.
        values = ibk.build(context({"land_list0": [
            {"NO": "1", "JIMOK": "대", "YONGDO": "제2종", "PRICE": "100"}]},
            outline=Outline(zone="제2종일반 주거지역")))
        assert values["용도지역"] == "제2종일반주거지역"

    def test_용도지역은_첫_하나만(self):
        values = ibk.build(context({"land_list0": [
            {"NO": "1", "JIMOK": "대", "YONGDO": "제2종일반주거지역, 자연녹지지역",
             "PRICE": "100"}]}))
        assert values["용도지역"] == "제2종일반주거지역"

    def test_콤보에_없는_용도지역은_비운다(self):
        # 기업 콤보는 국토계획법 **용도지역** 21종뿐 — `개발제한구역` 은 용도구역이라 없다.
        # 넣어 봐야 못 고르고, 텍스트로 우겨넣으면 틀린 값이 된다(실측 2683 화면=자연녹지지역).
        values = ibk.build(context({"land_list0": [
            {"NO": "1", "JIMOK": "대", "YONGDO": "개발제한구역", "PRICE": "100"}]}))
        assert values["용도지역"] is None

    def test_등급은_살린다(self):
        # 농협 화면은 대분류만 받지만 기업 콤보는 `제1종일반주거지역` 까지 있다.
        values = ibk.build(context({"land_list0": [
            {"NO": "1", "JIMOK": "대", "YONGDO": "제１종일반주거지역", "PRICE": "100"}]}))
        assert values["용도지역"] == "제1종일반주거지역"

    def test_잘린_지목은_비운다(self):
        # 명세표 칸 폭 때문에 `공장용지`→`장` 으로 잘려 오는 문서가 있다(실측 1186·1538).
        values = ibk.build(context({"land_list0": [
            {"NO": "1", "JIMOK": "장", "YONGDO": "일반공업지역", "PRICE": "100"}]}))
        assert values["공부지목"] is None

    def test_대는_대지로(self):
        values = ibk.build(context({"land_list0": [
            {"NO": "1", "JIMOK": "대", "YONGDO": "일반상업지역", "PRICE": "100"}]}))
        assert values["공부지목"] == "대지"


class TestHeaderFields:
    def test_지번은_명세행이_우선(self):
        values = ibk.build(context(MIXED_2531, jibun=Jibun(
            reg="41590", eub="25300", san="1", bun1="999", bun2="9")))
        assert (values["본번지"], values["부번지"]) == ("506", "9")
        assert values[ibk.BOX_LEGAL_CODE] == "4159025300"
        assert values["번지구분"] == "일반"

    def test_명세행에_지번이_없으면_DB로_물러선다(self):
        values = ibk.build(context({}, jibun=Jibun(
            reg="41590", eub="25300", san="1", bun1="461", bun2="17")))
        assert (values["본번지"], values["부번지"]) == ("461", "17")

    def test_실비는_구성항목합이고_부가세를_안_붙인다(self):
        # 실측 2683: GONGBU+YEBI+MULJOSABI+SILBI = 69,900. 국민(부가세 포함)과 다르다.
        fee = Fee(net=Decimal("1000000"), vat=Decimal("100000"), total=Decimal("1169900"),
                  expense_extra=Decimal("200"),
                  expense_parts=(Decimal("2000"), Decimal("57700"), Decimal("10000")))
        values = ibk.build(context({}, fee=fee))
        assert values["실   비"] == "69900"
        assert values["순수수료"] == "1000000"
        assert values["부가세"] == "100000"
        assert values["감정수수료"] == "1169900"
        assert values["특별용역비"] == "0"

    def test_담보구분은_비워둔다(self):
        # 화면 '임대차포함' 등 — 소스 미확정이라 사람이 고르게 남긴다.
        assert ibk.build(context({}))["담보구분"] is None

    def test_평가사명(self):
        values = ibk.build(context({}, parties=Parties(
            appraisers=("유승민", "전영배"), reviewer="김치암")))
        assert values["평가사명"] == "유승민"

    def test_심사자_칸은_기업폼에_없다(self):
        # 실폼 확인: 토지 32칸·구분건물 37칸 어디에도 심사자가 없다(국민과 다름).
        # 넣어 두면 검증마다 '우리채움' 잡음만 남는다.
        values = ibk.build(context({}, parties=Parties(reviewer="김치암")))
        assert "심사자" not in values
