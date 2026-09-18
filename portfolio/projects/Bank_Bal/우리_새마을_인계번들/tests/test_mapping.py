"""은행별 매핑 조립 — 신한/국민."""
from __future__ import annotations

from decimal import Decimal

from bankon.mapping import kookmin, shinhan
from bankon.model import DocumentContext, Fee, Parties
from bankon.parse.account import BankAccount
from bankon.parse.characteristics import Characteristics
from bankon.parse.cost import CostLayer
from bankon.parse.mullist import parse as parse_mullist
from bankon.parse.outline import Outline
from bankon.parse.standard_land import StandardLand
from bankon.sources.apw import Jibun

COMBOS = {
    "담보종류": frozenset({"집합상가", "아파트", "기계기구", "공장"}),
    "담보용도": frozenset({"상가(중/소형)", "아파트", "공장"}),
    "건물구조(신)": frozenset({"철근콘크리트구조", "일반철골구조"}),
    "지목": frozenset({"대지", "전"}),
    "용도지역구분(신)": frozenset({"제2종일반주거지역", "일반상업지역"}),
}

MULLIST_ROW = {
    "NO": "1", "SNO": "가", "DABO_JONG": "집합건물", "DABO_JONG_SUB": "집합상가",
    "MUL_GUBUN": "건물", "JI_YOUNGDO": "철근콘크리트조", "YG_AREA": "제2종일반주거지역",
    "ADDR_NEW": "대구광역시 수성구 신매동 273", "GONG_AREA": "98.6", "SA_AREA": "98.6",
    "P_PRICE": "480,000,000", "DUNG_NO": "1701-2018-002982",
    "DB_YEAR": "50", "SUR_YEAR": "28", "USE_APP_DATE": "2018.02.14",
}


def make_context(**overrides) -> DocumentContext:
    base = dict(
        doc_id="03-2509-3-1011",
        business_number="2148746436",
        parties=Parties(boss="정우종", appraisers=("김민석", "황인석"), reviewer="전영배"),
        fee=Fee(net=Decimal("2232880"), vat=Decimal("223200"),
                subtotal=Decimal("2455200"), total=Decimal("2678400"),
                expense_base=Decimal("115000"), expense_extra=Decimal("0")),
        account=BankAccount("신한은행", "100-025-471640", "(주)대화감정평가법인"),
        jibun=Jibun(reg="11650", eub="10800", san="1", bun1="1601", bun2="10"),
        outline=Outline(address="대구광역시 수성구 신매동", struct="철근콘크리트구조",
                        floors_text="지하1층 / 지상 20층", approval_date="2018-02-14"),
        price_point_date="2026-08-11",
        total_amount=Decimal("2863000000"),
        properties=parse_mullist({"mullist0": [MULLIST_ROW]}),
    )
    return DocumentContext(**{**base, **overrides})


class TestShinhan:
    def test_물건별로_한벌씩_만든다(self):
        rows = shinhan.build(make_context(), COMBOS)
        assert len(rows) == 1
        assert rows[0]["물건순번"] == "1"

    def test_mullist_값을_코드로_바꾼다(self):
        row = shinhan.build(make_context(), COMBOS)[0]
        assert row["담보종류"] == "집합상가"
        assert row["담보용도"] == "상가(중/소형)"      # 담보종류에서 유도
        assert row["담보세부종류"] == "건물"
        assert row["건물구조(신)"] == "철근콘크리트구조"  # '…조' → '…구조' 정규화
        assert row["용도지역구분(신)"] == "제2종일반주거지역"
        assert row["지목"] is None                      # 건물 물건이므로

    def test_수수료는_실측_관계대로_넣는다(self):
        # 실물 대조로 확인: 감정평가료=TOTAL, 실비=(SILBISUM+SILBI)*1.1
        row = shinhan.build(make_context(), COMBOS)[0]
        assert row["순수수료"] == "2232880"
        assert row["감정평가료"] == "2678400"
        assert row["실   비"] == "126500"

    def test_면적은_소수2자리_등기번호는_숫자만(self):
        row = shinhan.build(make_context(), COMBOS)[0]
        assert row["공부면적(수량)"] == "98.60"      # 98.6 → 98.60
        assert row["건물등기부번호"] == "17012018002982"

    def test_해당층수를_소재지에서_뽑는다(self):
        ctx = make_context(
            properties=__import__("bankon.parse.mullist", fromlist=["parse"]).parse(
                {"mullist0": [{**MULLIST_ROW, "ADDR_NEW": "서울 강서구 마곡동 798-3 제9층 제901호"}]}
            )
        )
        assert shinhan.build(ctx, COMBOS)[0]["해당층수"] == "9"

    def test_금액은_콤마없이_넣는다(self):
        row = shinhan.build(make_context(), COMBOS)[0]
        assert row["감정평가액"] == "480000000"
        assert row["총감정가액"] == "2863000000"

    def test_등기번호는_물건종류에_따라_나뉜다(self):
        # 화면에는 하이픈 없이 숫자만 들어간다(실측).
        row = shinhan.build(make_context(), COMBOS)[0]
        assert row["건물등기부번호"] == "17012018002982"
        assert row["토지등기부번호"] is None

    def test_지번은_APW에서_온다(self):
        row = shinhan.build(make_context(), COMBOS)[0]
        assert (row["번지구분"], row["본번지"], row["부번지"]) == ("일반", "1601", "10")

    def test_담당자와_계좌(self):
        row = shinhan.build(make_context(), COMBOS)[0]
        assert row["대표,지사장"] == "정우종"
        assert row["평가사명1"] == "김민석"
        assert row["평가사명2"] == "황인석"
        assert row["평가사명3"] is None
        assert row["심사자"] == "전영배"
        assert row["수수료입금계좌번호"] == "100-025-471640"

    def test_물건특성_표가_없으면_기본값(self):
        row = shinhan.build(make_context(), COMBOS)[0]
        assert row["튼상가"] == "아니오"
        assert row["임대"] == "미상"

    def test_물건특성_표가_있으면_그_값(self):
        found = Characteristics(sale="예", lease="임대있음", open_wall_shop="아니오")
        row = shinhan.build(make_context(characteristics=found), COMBOS)[0]
        assert row["매매/분양"] == "예"
        assert row["임대"] == "임대있음"

    def test_mullist가_없으면_담보종류를_비운다(self):
        # 신한 건의 32% — 사용자 결정: 비워두고 사람이 선택.
        rows = shinhan.build(make_context(properties=()), COMBOS)
        assert len(rows) == 1
        assert "담보종류" not in rows[0]        # 물건 필드 자체가 없다
        assert rows[0]["대표,지사장"] == "정우종"  # 헤더는 채운다

    def test_콤보목록에_없는_값은_비운다(self):
        narrow = {**COMBOS, "담보종류": frozenset({"아파트"})}
        row = shinhan.build(make_context(), narrow)[0]
        assert row["담보종류"] is None
        assert row["담보용도"] is None


class TestKookmin:
    def test_법정동코드는_내지_않는다(self):
        # 국민 폼의 법정동코드 칸은 라벨이 없고 **위치로도 못 짚는다**(토지탭이 겹쳐
        # 밴드 경계가 흔들린다 — 163건 중 3건이 어긋난다). 사람이 채운다.
        result = kookmin.build(make_context())
        assert "법정동코드" not in result
        assert result["번지구분"] == "일반"

    def test_등기번호는_하나다(self):
        result = kookmin.build(make_context())
        assert result["등기번호"] == "1701-2018-002982"
        assert "건물등기부번호" not in result

    def test_원가법표가_있으면_원가평가(self):
        layers = (CostLayer("가", "지상1층", "주택", Decimal("1400000"), 16, 45, Decimal("497000")),)
        result = kookmin.build(make_context(cost_layers=layers))
        assert result["평가방법"] == kookmin.METHOD_COST
        assert result["평가단가"] == "497000"
        assert result["내용년수"] == "50"     # mullist 값이 우선
        assert result["잔존년수"] == "28"

    def test_원가법표가_없으면_거래사례(self):
        assert kookmin.build(make_context())["평가방법"] == kookmin.METHOD_COMPARISON

    def test_표준지는_있을때만_채운다(self):
        assert kookmin.build(make_context())["표준지소재지"] is None
        standard = StandardLand(address="교동 BL-단-1-25", price=Decimal("672800"),
                                base_date="2023-01-01")
        result = kookmin.build(make_context(standard_land=standard))
        assert result["표준지소재지"] == "교동 BL-단-1-25"
        assert result["표준지공시지가"] == "672800"
        assert result["공시기준일"] == "2023-01-01"

    def test_총세대수는_비운다(self):
        # 4개 소스에 없음 — 사용자 결정으로 자동입력하지 않는다.
        assert kookmin.build(make_context())["총세대수"] is None

    def test_수수료는_순수수료에서_계산한다(self):
        # 실측: 국민 화면의 부가세는 gam_info TAX 가 아니라 **순수수료의 10%** 이고,
        # 총액은 순수수료+부가세다(1,838,000 → 183,800 → 2,021,800).
        result = kookmin.build(make_context())
        assert result["감정평가(순)수수료"] == "2232880"
        assert result["(순)수수료-부가가치세"] == "223200"   # 2,232,000 × 10%
        assert result["감정평가(순)수수료 총액"] == "2455200"
        assert result["실비-총액"] == "126500"                 # (SILBISUM+SILBI)*1.1
