"""우리은행 담보(TBNKWRB24DAMB) 매핑 — 인계본(우리_새마을_인계번들 2026-09-08) 실측 규칙을 고정한다(이식 2026-09-10)."""
from __future__ import annotations

from decimal import Decimal

from bankon.mapping import wrb
from bankon.model import DocumentContext, Fee, Parties
from bankon.parse import detail
from bankon.parse.account import BankAccount
from bankon.parse.outline import Outline
from bankon.parse.round import RoundInfo
from bankon.parse.standard_land import StandardLand
from bankon.sources.apw import Jibun


def context(tables: dict | None = None, **kwargs) -> DocumentContext:
    fields = {
        "doc_id": "01-2608-3-0000",
        "business_number": "2148746436",
        "details": detail.parse(tables or {}),
        "rounds": (RoundInfo(appraiser="성지연", client="우리은행 여신업무센터장"),),
        "fee": Fee(net=Decimal("1271098"), vat=Decimal("133700"), total=Decimal("1470700"),
                   expense_parts=(Decimal("60000"), Decimal("6000"))),
        "parties": Parties(appraisers=("최병산",)),
        "price_point_date": "2026-08-20",
        "standard_land": StandardLand(address="서울특별시 용산구 한남동 1-1", price=Decimal("8000000"), base_date="2026-01-01"),
    }
    fields.update(kwargs)
    return DocumentContext(**fields)


LAND = {"land_list0": [
    {"NO": "1", "ADDR": "서울특별시 용산구 한남동", "JIBUN": "424-5", "JIMOK": "대",
     "YONGDO": "제2종일반주거지역", "AREA1": "73.1", "AREA2": "73.1",
     "DANGA": "19,200,000", "PRICE": "1,403,520,000"},
]}


class TestZone:
    def test_정식명은_축약으로(self):
        assert wrb.zone_wrb("제2종일반주거지역") == "2종일주"        # 실측 2668
        assert wrb.zone_wrb("개발제한구역") == "개발제한"
        assert wrb.zone_wrb("자연환경보전지역") == "자연환경"

    def test_이미_축약형이면_그대로(self):
        assert wrb.zone_wrb("2종일주") == "2종일주"

    def test_모르면_비운다(self):
        assert wrb.zone_wrb("지구단위계획구역") is None
        assert wrb.zone_wrb("") is None


class TestLand:
    def test_우리는_대지(self):
        assert wrb.land_wrb("대") == "대지"
        assert wrb.land_wrb("대지") == "대지"
        assert wrb.land_wrb("철도용지") is None            # 우리 콤보는 '철도'
        assert wrb.land_wrb("철도") == "철도"


class TestKind:
    def test_구체_용어가_먼저(self):
        assert wrb.kind_wrb("아파트형공장", None) == "공장(공장재단포함)"
        assert wrb.kind_wrb(None, "아파트형상가") == "상가(아파트형)"
        assert wrb.kind_wrb("단독주택", None) == "단독주택"

    def test_이용상황이_콤보에_없으면_건물용도로(self):
        assert wrb.kind_wrb("주상용", "근린생활시설") == "근린상가"   # 실측 2668

    def test_상업용_미확정은_비운다(self):
        assert wrb.kind_wrb("업무용", "판매시설") is None


class TestBuild:
    def test_토지형(self):
        values = wrb.build(context(LAND, jibun=Jibun(reg="11290", eub="12500", san="1", bun1="424", bun2="5")))
        assert values["세부물건종류"] == "대지"
        assert values["토지지목"] == "대지"
        assert values["용도지역"] == "2종일주" and values["용도"] == "2종일주"
        assert values["평가단가"] == "19200000"
        assert values["감정평가액"] == "1403520000"
        assert (values["본번지"], values["부번지"]) == ("424", "5")
        assert values["건물명"] is None

    def test_머리_수수료_계좌_표준지(self):
        values = wrb.build(context(LAND, account=BankAccount(bank="하나은행", number="100-025-471640", holder="㈜대일감정평가법인")))
        assert values["평가사명"] == "성지연"
        assert values["기준시점"] == "2026-08-20"
        assert values["감정수수료"] == "1470700" and values["순수수료"] == "1271098"
        assert values["실   비"] == "66000" and values["부가세"] == "133700"
        assert values["계좌번호"] == "100025471640"
        assert values["공시기준일"] == "2026-01-01"
        assert values["표준지공시지가"] == "8000000"
        assert values["표준지소재지"] == "서울특별시 용산구 한남동 1-1"

    def test_법정동코드_소재지는_내지_않는다(self):
        values = wrb.build(context(LAND))
        assert not any("법정동" in k or k.startswith("소재지") for k in values)   # 주소검색 자동생성 칸(인계본 감사)

    def test_개요_구조는_지붕_앞만(self):
        values = wrb.build(context(LAND, outline=Outline(struct="철근콘크리트구조 / 슬라브지붕", usage="주상용")))
        assert values["구   조"] == "철근콘크리트구조"
        assert values["이용상황"] == "주상용"
