"""하나은행 담보(TBNKHNB24DAMB) 매핑 — 인계본(수협_하나_인계번들 2026-09-07) 실측 규칙을 고정한다(이식 2026-09-10)."""
from __future__ import annotations

from decimal import Decimal

from bankon.mapping import hnb
from bankon.model import DocumentContext, Fee, Parties
from bankon.parse import detail
from bankon.parse.account import BankAccount
from bankon.parse.outline import Outline
from bankon.parse.round import RoundInfo
from bankon.sources.apw import Jibun


def context(tables: dict | None = None, **kwargs) -> DocumentContext:
    fields = {
        "doc_id": "01-2609-3-0000",
        "business_number": "2148746436",
        "details": detail.parse(tables or {}),
        "rounds": (RoundInfo(appraiser="김민석", client="하나은행 옥수동지점장"),),
        "fee": Fee(net=Decimal("588800"), vat=Decimal("65000"), total=Decimal("715000")),
        "parties": Parties(appraisers=("황인석",)),
        "price_point_date": "2026-09-03",
        "total_amount": Decimal("435000000"),
        "site_address": "서울특별시 성동구 옥수동",
    }
    fields.update(kwargs)
    return DocumentContext(**fields)


LAND = {"land_list0": [
    {"NO": "1", "ADDR": "서울특별시 성동구 옥수동", "JIBUN": "424-67", "JIMOK": "대",
     "YONGDO": "제2종일반주거지역", "AREA1": "146.1", "AREA2": "146.1",
     "DANGA": "2,900,000", "PRICE": "423,690,000"},
]}
SECTION = {"section_build0": [
    {"JIBUN": "424-67,"},
    {"NO": "가", "gujo": "철근콘크리트구조"},
    {"gujo": "제지3층 제비101호", "AREA1": "90.48", "AREA2": "90.48", "PRICE": "435,000,000"},
]}


class TestAddrParts:
    def test_시도_구군_읍면동(self):
        assert hnb._addr_parts("서울특별시 성동구 옥수동") == ("서울특별시", "성동구", "옥수동", None)

    def test_시_아래_구는_구군에_합친다(self):
        assert hnb._addr_parts("경기도 부천시 원미구 상동") == ("경기도", "부천시 원미구", "상동", None)

    def test_읍면_리(self):
        assert hnb._addr_parts("충청북도 청원군 북이면 옥수리") == ("충청북도", "청원군", "북이면", "옥수리")

    def test_세종은_구군_공란(self):
        assert hnb._addr_parts("세종특별자치시 조치원읍 신흥리") == ("세종특별자치시", None, "조치원읍", "신흥리")
        assert hnb._addr_parts("세종특별자치시 나성동") == ("세종특별자치시", None, "나성동", None)

    def test_빈값(self):
        assert hnb._addr_parts(None) == (None, None, None, None)


class TestBuildingUse:
    def test_근린생활시설은_점포및상가(self):
        assert hnb._building_use("근린생활시설, 판매시설") == "점포및상가"       # 실측 2751

    def test_구분건물_공장은_아파트형공장(self):
        assert hnb._building_use("공장(아파트형공장) 및 근린생활시설") == "아파트형공장"   # 실측 2722
        assert hnb._building_use("공장, 근린생활시설", is_section=True) == "아파트형공장"  # 실측 2473
        assert hnb._building_use("공장") == "일반공장"

    def test_모르면_비운다(self):
        assert hnb._building_use("위험물저장및처리시설") is None
        assert hnb._building_use(None) is None


class TestLand:
    def test_하나_지목은_대(self):
        assert hnb._land_hnb("대") == "대"
        assert hnb._land_hnb("대지") is None
        assert hnb._land_hnb("공장용지") == "공장용지"


class TestCleanName:
    def test_제동_이하를_뗀다(self):
        assert hnb._clean_name("옥수어울림 제근린생활시설동 제지3층") == "옥수어울림"   # 실측 2751
        assert hnb._clean_name("미사센트럴프라자") == "미사센트럴프라자"
        assert hnb._clean_name(None) is None


class TestBuild:
    def test_토지형(self):
        values = hnb.build(context(LAND, jibun=Jibun(reg="11290", eub="12500", san="1", bun1="424", bun2="67")))
        assert values["물건종류"] == "토지"
        assert (values["시도"], values["구군"], values["읍면동"], values["리"]) == ("서울특별시", "성동구", "옥수동", None)
        assert values["번지"] == "424-67"
        assert values["공부상지목"] == "대" and values["실제지목"] == "대"
        assert values["평가단가"] == "2900000"
        assert values["감정평가액"] == "423690000"
        assert values["사정면적"] == "146.10"
        assert values["건물명"] is None and values["건물용도"] is None

    def test_머리_수수료_계좌(self):
        acct = BankAccount(bank="하나은행", number="103-910016-91404", holder="㈜대일감정평가법인")
        values = hnb.build(context(LAND, account=acct))
        assert values["평가사명"] == "김민석"
        assert values["기준시점"] == "2026-09-03" and values["감정일자"] == "2026-09-03"
        assert values["계좌번호"] == "10391001691404"          # 하이픈 제거(실측 2722)
        assert values["총감정평가액"] == "435000000"
        assert values["순수수료"] == "588800"

    def test_구분건물은_건물이고_단가_0(self):
        values = hnb.build(context(SECTION, outline=Outline(building_use="근린생활시설", approval_date="2019-05-02")))
        assert values["물건종류"] == "건물"                      # 콤보에 집합건물 없음
        assert values["평가단가"] == "0"
        assert values["건물용도"] == "점포및상가"
        assert values["준공/제작일자"] == "2019-05-02"
        assert values["감정평가액"] == "435000000"


# 실측 01-2609-3-2871(잠실동 숙박시설) 축약 — 하나 관례가 다 들어 있다:
# 토지 1행 + 건물 **단가별 3행**(1층/2~9층/지층) + **평가외(옥탑) 1행**.
MULTI = {"land_list0": [
    {"NO": "1", "ADDR": "서울특별시", "JIBUN": "184-20", "JIMOK": "대", "YONGDO": "일반상업지역",
     "AREA1": "165.3", "AREA2": "165.3", "DANGA": "47,000,000", "PRICE": "7,769,100,000"},
    {"ADDR": "송파구"},
    {"ADDR": "잠실동"},
    {"NO": "가", "ADDR": '"', "JIBUN": "위지상", "JIMOK": "숙박시설", "YONGDO": "철근"},
    {"ADDR": "[도로명주소]", "YONGDO": "콘크리트구조"},
    {"YONGDO": "1층", "AREA1": "31.02", "AREA2": "31.02", "DANGA": "540,000", "PRICE": "16,750,800"},
    {"YONGDO": "2층", "AREA1": "98.82", "AREA1RB": "<", "AREA2": "680.34",
     "DANGA": "756,000", "PRICE": "514,337,040"},
    {"YONGDO": "3층", "AREA1": "98.82", "AREA1RB": "|"},
    {"YONGDO": "4층", "AREA1": "98.82", "AREA1RB": "|"},
    {"YONGDO": "5층", "AREA1": "98.82", "AREA1RB": "|"},
    {"YONGDO": "6층", "AREA1": "98.82", "AREA1RB": "|"},
    {"YONGDO": "7층", "AREA1": "84.24", "AREA1RB": "|"},
    {"YONGDO": "8층", "AREA1": "69.66", "AREA1RB": "|"},
    {"YONGDO": "9층", "AREA1": "32.34", "AREA1RB": ">"},
    {"YONGDO": "지층", "AREA1": "98.82", "AREA2": "98.82", "DANGA": "486,000", "PRICE": "48,026,520"},
    {"YONGDO": "옥탑", "AREA1": "12.25", "AREA2": "12.25", "DANGA": "-", "PRICE": "감정평가 외"},
    {"YONGDO": "(연면적제외)"},
]}


class TestMultiSlots:
    """하나는 **단가마다 한 행** + **평가외 한 행**(사용자 확인·2871 담당자 완성본 2026-09-16)."""

    def ctx(self):
        return context(MULTI, excluded_parts=detail.excluded_parts(MULTI))

    def test_물건_행은_다섯개(self):
        assert len(hnb.slots(self.ctx())) == 5

    def test_단가별로_행이_나뉜다(self):
        ctx = self.ctx()
        assert [hnb.build(ctx, str(n))["평가단가"] for n in (1, 2, 3, 4)] == \
            ["47000000", "540000", "756000", "486000"]

    def test_층별_공부면적은_합쳐서_들어간다(self):
        # 2~9층: 98.82×5 + 84.24 + 69.66 + 32.34 = 680.34 (= 사정면적)
        third = hnb.build(self.ctx(), "3")
        assert third["공부면적"] == "680.34" and third["사정면적"] == "680.34"

    def test_평가외_행은_단가1_금액0(self):
        fifth = hnb.build(self.ctx(), "5")
        assert fifth["물건종류"] == "건물"
        assert fifth["감정평가액"] == "0" and fifth["평가단가"] == "1"
        assert fifth["사정면적"] == "12.25" and fifth["공부면적"] == "12.25"

    def test_건물용도는_명세_유닛_용도로_폴백한다(self):
        # 2871 은 의견서 개요가 깨져 building_use 가 '연면적(㎡) (옥탑층 제외)' 로 들어온다.
        ctx = context(MULTI, excluded_parts=detail.excluded_parts(MULTI),
                      outline=Outline(building_use="연면적(㎡) (옥탑층 제외)"))
        assert hnb.build(ctx, "2")["건물용도"] == "여관"      # 명세 JIMOK '숙박시설'

    def test_평가외가_없으면_행_수는_종전대로(self):
        assert len(hnb.slots(context(LAND))) == 1
