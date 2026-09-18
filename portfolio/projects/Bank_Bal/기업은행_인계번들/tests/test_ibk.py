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

    def test_물건종류_공업용은_공장으로(self):
        values = ibk.build(context({}, outline=Outline(usage="공업용")))
        assert values["물건종류"] == "공장"

    def test_물건종류는_그밖엔_원본대로(self):
        values = ibk.build(context({}, outline=Outline(usage="단독주택")))
        assert values["물건종류"] == "단독주택"


class TestHeaderFields:
    def test_지번은_명세행이_우선(self):
        values = ibk.build(context(MIXED_2531, jibun=Jibun(
            reg="41590", eub="25300", san="1", bun1="999", bun2="9")))
        assert (values["본번지"], values["부번지"]) == ("506", "9")
        assert values["법정동코드"] == "4159025300"
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
        assert values["심사자"] == "김치암"
