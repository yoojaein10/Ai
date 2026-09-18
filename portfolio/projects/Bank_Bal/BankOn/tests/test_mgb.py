"""새마을금고 담보(TBNKMGB24DAMB) 매핑 — 인계본(우리_새마을_인계번들 2026-09-08) 실측 규칙을 고정한다(이식 2026-09-10).

새마을 특유 2가지: ① 토지+건물 통합(일단지 블록 없음) ② 일단지 분리(블록 `<|>` 있음, member 금액 = 면적 × 머리 단가).
"""
from __future__ import annotations

from decimal import Decimal

from bankon.mapping import mgb
from bankon.model import DocumentContext, Fee, Parties
from bankon.parse import detail, outline
from bankon.parse.cost import CostLayer
from bankon.parse.outline import Outline
from bankon.parse.round import RoundInfo
from bankon.parse.standard_land import StandardLand


def context(tables: dict | None = None, **kwargs) -> DocumentContext:
    fields = {
        "doc_id": "01-2609-3-0000",
        "business_number": "2148746436",
        "details": detail.parse(tables or {}),
        "rounds": (RoundInfo(appraiser="최병산", client="북부천새마을금고이사장"),),
        "fee": Fee(net=Decimal("4733000"), vat=Decimal("473300"), total=Decimal("5206300"),
                   expense_parts=(Decimal("40000"),)),
        "parties": Parties(appraisers=("정우종",)),
        "price_point_date": "2026-09-03",
        "total_amount": Decimal("2500000000"),
        "standard_land": StandardLand(address="경기도 부천시 원미구 상동 100", price=Decimal("3000000"), base_date="2026-01-01"),
    }
    fields.update(kwargs)
    return DocumentContext(**fields)


# 통합형(실측 2762 축약): 토지 578.2㎡ + 건물(land_list 유닛) 950.52 — 한 물건에 토지+건물.
COMBINED = {"land_list0": [
    {"NO": "1", "ADDR": "경기도 부천시 원미구 상동", "JIBUN": "544-3", "JIMOK": "대",
     "YONGDO": "제2종일반주거지역", "AREA1": "578.2", "AREA2": "578.2",
     "DANGA": "3,200,000", "PRICE": "1,850,240,000"},
    {"NO": "가", "ADDR": "", "JIBUN": "", "JIMOK": "근린생활시설", "YONGDO": "철근콘크리트구조",
     "AREA1": "950.52", "AREA2": "950.52", "DANGA": "", "PRICE": "649,760,000"},
]}
LAND_ONLY = {"land_list0": [COMBINED["land_list0"][0]]}


class TestHelpers:
    def test_지목은_대(self):
        assert mgb.land_mgb("대") == "대" and mgb.land_mgb("대지") is None

    def test_구조는_지붕과_괄호를_뗀다(self):
        assert mgb._struct_head("철근콘크리트구조 / 평스라브지붕") == "철근콘크리트구조"
        assert mgb._struct_head("철골조 (철근)콘크리트지붕") == "철골조"
        assert mgb._struct_head("일반철골구조(PEB)") == "일반철골구조"
        assert mgb._struct_head(None) is None

    def test_물건종류는_gam_구분이_1차(self):
        assert mgb._kind_mgb(context(gam_category="구분건물")) == "집합건물"
        assert mgb._kind_mgb(context(gam_category="토지건물")) == "토지+건물"
        assert mgb._kind_mgb(context(gam_category="토지")) == "토지"
        assert mgb._kind_mgb(context(gam_category="건물")) == "건물"

    def test_gam_구분이_없으면_명세_구성으로(self):
        assert mgb._kind_mgb(context(COMBINED)) == "토지+건물"
        assert mgb._kind_mgb(context(LAND_ONLY)) == "토지"


class TestLandFeatures:
    BODY = ("<table><tr><td>이용상황</td><td>도로교통</td><td>형상\n지세</td></tr>"
            "<tr><td>주상용</td><td>광대세각</td><td>세장형\n평  지</td></tr></table>")

    def test_토지특성표에서_도로_형상_지세(self):
        assert outline.land_features(self.BODY) == ("광대세각", "세장형", "평지")

    def test_없으면_None(self):
        assert outline.land_features("<table><tr><td>소재지</td><td>상동 544-3</td></tr></table>") == (None, None, None)
        assert outline.land_features(None) == (None, None, None)

    def test_콤보_어휘_밖은_비운다(self):
        body = "<td>중로한면</td><td>이상한형\n경사</td>"
        assert outline.land_features(body) == ("중로한면", None, None)

    def test_표기_변형도_콤보_이름으로(self):
        # 로컬 추출본 622건 실측 표기(2026-09-15). 2847 = '사다리\n평지' 형상 빈칸 제보.
        cases = {
            "사다리\n평지": ("사다리형", "평지"),
            "사다리형/\n평지": ("사다리형", "평지"),
            "사다리 평지": ("사다리형", "평지"),
            "사다리형평  지": ("사다리형", "평지"),
            "세로장방형\n완경사지": ("세장형", "완경사"),
            "가로장방형 급경사": ("가장형", "급경사"),
            "역삼각형\n고지": ("역삼각", "고지"),
            "삼각형\n저지": ("삼각형", "저지"),
            "-\n평지": (None, "평지"),
        }
        for cell, (shape, slope) in cases.items():
            body = f"<td>세로(가)</td><td>{cell}</td>"
            assert outline.land_features(body) == ("세로(가)", shape, slope), cell

    def test_parse_가_outline_에_싣는다(self):
        parsed = outline.parse(self.BODY)
        assert (parsed.road, parsed.shape, parsed.slope) == ("광대세각", "세장형", "평지")


class TestBuild:
    def test_토지_건물_통합형은_총액과_면적합(self):
        values = mgb.build(context(COMBINED, gam_category="토지건물",
                                   outline=Outline(struct="철근콘크리트구조 / 평스라브지붕", approval_date="2005-03-01",
                                                   usage="주상용", road="광대세각", shape="세장형", slope="평지")))
        assert values["물건종류"] == "토지+건물"
        assert values["감정가액"] == "2500000000"                 # 총액
        assert values["공부면적"] == "1528.72"                    # 578.2 + 950.52
        assert values["사정면적"] == "1528.72"
        assert values["토지단가"] == "3200000"                    # 토지 단가
        assert values["건물구조"] == "철근콘크리트구조"
        assert values["사용승인일"] == "2005-03-01" and values["준공일자"] == "2005-03-01"
        assert (values["도로상태"], values["형상"], values["지세"]) == ("광대세각", "세장형", "평지")
        assert values["용도지역"] == "제2종일반주거지역"          # 정식명 그대로
        assert values["공부상지목"] == "대"
        assert values["특별용역비"] == "0"                        # 칸이 있으면 0(전 은행 공통, 사용자 지시 2026-09-14)

    def test_내용_잔존연수는_원가표_대표층(self):
        # 2847 실측: 가동 1~4층(결정단가 최대 995,000) 45/32, 나동 40/39 → 대표층 45/32.
        layers = (
            CostLayer(mark="가", floor="지1층", use="주차장", replacement_cost=Decimal("900000"),
                      remaining_years=32, useful_years=45, unit_price=Decimal("640000")),
            CostLayer(mark="가", floor="1층~4층", use="사무소", replacement_cost=Decimal("1400000"),
                      remaining_years=32, useful_years=45, unit_price=Decimal("995000")),
            CostLayer(mark="나", floor="1층, 2층", use="사무소", replacement_cost=Decimal("1000000"),
                      remaining_years=39, useful_years=40, unit_price=Decimal("975000")),
        )
        values = mgb.build(context(COMBINED, gam_category="토지건물", cost_layers=layers))
        assert (values["내용연수"], values["잔존연수"]) == ("45", "32")

    def test_원가표_없거나_토지만이면_연수_비움(self):
        values = mgb.build(context(COMBINED, gam_category="토지건물"))
        assert values["내용연수"] is None and values["잔존연수"] is None
        layers = (CostLayer(mark="가", floor="1층", use="주택", replacement_cost=Decimal("1"),
                            remaining_years=10, useful_years=40, unit_price=Decimal("1")),)
        land = mgb.build(context(LAND_ONLY, gam_category="토지", cost_layers=layers))
        assert land["내용연수"] is None and land["잔존연수"] is None

    def test_토지형(self):
        values = mgb.build(context(LAND_ONLY, gam_category="토지"))
        assert values["물건종류"] == "토지"
        assert values["감정가액"] == "1850240000"
        assert values["공부면적"] == "578.20"
        assert values["건물구조"] is None and values["사용승인일"] is None

    def test_머리_수수료_표준지(self):
        values = mgb.build(context(LAND_ONLY))
        assert values["평가사성명"] == "최병산"
        assert values["가격평가일자"] == "2026-09-03"
        assert values["감정수수료"] == "5206300" and values["순수수료"] == "4733000"
        assert values["부가세"] == "473300" and values["실비"] == "40000"
        assert values["총감정평가액"] == "2500000000"
        assert values["표준지공시기준일"] == "2026-01-01"
        assert values["표준지공시지가"] == "3000000"
        assert values["표준지소재지"] == "경기도 부천시 원미구 상동 100"

    def test_축약_용도지역은_콤보에_없어_비운다(self):
        tables = {"land_list0": [dict(LAND_ONLY["land_list0"][0], YONGDO="2종일주")]}
        assert mgb.build(context(tables, gam_category="토지"))["용도지역"] is None
