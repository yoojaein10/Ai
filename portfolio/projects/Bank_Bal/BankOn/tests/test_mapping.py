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
        assert rows[0]["물건순번"] is None   # 화면이 매기는 번호 — 쓰지 않음(2026-08-25)

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
        assert row["건물등기부번호"] == "17012018002982"   # 하이픈 없이 숫자만(업무팀 실물 2676, 2026-08-26)

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
        assert row["건물등기부번호"] == "17012018002982"   # 건물 물건 → 건물 칸(2026-08-26)
        assert row["토지등기부번호"] is None                # 건물 물건엔 토지 칸 비움

    def test_지번은_APW에서_온다(self):
        row = shinhan.build(make_context(), COMBOS)[0]
        # 물건 주소(ADDR_NEW '신매동 273')의 지번이 우선(2026-08-25). APW 대표지번(1601-10)은 폴백.
        assert (row["번지구분"], row["본번지"], row["부번지"]) == ("일반", "273", "0")

    def test_담당자와_계좌(self):
        row = shinhan.build(make_context(), COMBOS)[0]
        assert row["대표,지사장"] is None        # 발송 기준: 대표·심사자 비움(2026-08-25)
        assert row["평가사명1@2"] == "김민석"    # @2 = 라벨 오른쪽 둘째 콤보(이름)
        assert row["평가사명2@2"] == "황인석"
        assert row["평가사명3@2"] is None
        assert row["심사자"] is None
        assert "수수료입금계좌번호" not in row   # 신한 폼에 없는 칸(2026-08-25 제거)

    def test_물건특성_표가_없으면_기본값(self):
        row = shinhan.build(make_context(), COMBOS)[0]
        assert row["튼상가"] == "아니오"
        assert row["임대"] == "임대없음(자가사용및자가사용예정)"   # 콤보에 '해당없음' 없음(2026-09-07)

    def test_물건특성_표가_없어도_요약표_임대료_단서면_임대있음(self):
        # 2831: 의견서 물건특성 표 없음 + .gam 요약표 비고 '월 임대료 : 3,800,000원' → 자가사용으로 나갔다(2026-09-11).
        row = shinhan.build(make_context(lease_hint="임대있음"), COMBOS)[0]
        assert row["임대"] == "임대있음"
        # 물건특성 표의 답이 있으면 그것이 우선이다.
        found = Characteristics(lease="임대없음(공실)")
        row = shinhan.build(make_context(characteristics=found, lease_hint="임대있음"), COMBOS)[0]
        assert row["임대"] == "임대없음(공실)"

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
        assert rows[0]["평가사명1@2"] == "김민석"  # 헤더는 채운다

    def test_콤보목록에_없는_값은_비운다(self):
        narrow = {**COMBOS, "담보종류": frozenset({"아파트"})}
        row = shinhan.build(make_context(), narrow)[0]
        assert row["담보종류"] is None
        assert row["담보용도"] is None


class TestKookmin:
    def test_법정동코드는_10자리_한칸(self):
        result = kookmin.build(make_context())
        assert result["법정동코드"] == "1165010800"
        assert result["번지구분"] == "일반"

    def test_등기번호는_하나다(self):
        result = kookmin.build(make_context())
        assert result["등기번호"] == "1701-2018-002982"
        assert "건물등기부번호" not in result

    def test_토지건물이면_원가평가(self):
        # 평가방법은 물건구분으로(사용자 확정 2026-09-14): 토지건물·토지·건물 = 원가평가, 구분건물 = 거래사례
        layers = (CostLayer("가", "지상1층", "주택", Decimal("1400000"), 16, 45, Decimal("497000")),)
        result = kookmin.build(make_context(cost_layers=layers, gam_category="토지건물"))
        assert result["평가방법"] == kookmin.METHOD_COST
        assert kookmin.build(make_context(gam_category="토지"))["평가방법"] == kookmin.METHOD_COST
        assert kookmin.build(make_context(gam_category="토지건물구분건물"))["평가방법"] == kookmin.METHOD_COST
        assert result["평가단가"] == "497000"
        assert result["내용년수"] == "50"     # mullist 값이 우선
        assert result["잔존년수"] == "28"

    def test_구분건물이면_거래사례(self):
        assert kookmin.build(make_context(gam_category="구분건물"))["평가방법"] == kookmin.METHOD_COMPARISON
        assert kookmin.METHOD_COMPARISON == "구분소유물건(거례사례)"    # 은행 화면 캡션 그대로('거례' = 은행 쪽 오타, 실측 2026-09-14) — 고치면 못 찾는다

    def test_물건구분이_없으면_명세_구성으로(self):
        # 토지 필지 없이 호 명세만 = 거래사례, 그 외 = 원가평가
        assert kookmin.build(make_context())["평가방법"] == kookmin.METHOD_COST

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


class TestRowJibun:
    def test_물건_주소_꼬리_지번(self):
        from bankon.mapping.shinhan import _row_jibun
        assert _row_jibun("경기도 안성시 양성면 도곡리 356-26 ") == ("일반", "356", "26")
        assert _row_jibun("경기도 안성시 양성면 도곡리 356-2 외 1필지") == ("일반", "356", "2")
        assert _row_jibun("경기도 안성시 양성면 도곡리 산 12-3") == ("산", "12", "3")
        assert _row_jibun("서울특별시 영등포구 당산동1가 1040번지") == ("일반", "1040", "0")
        assert _row_jibun("서울 강서구 마곡동 798-3 제9층 제901호") == ("일반", "798", "3")
        assert _row_jibun("") is None
        assert _row_jibun("경기도 안성시 양성면 도곡리") is None


class TestShinhan토지건물:
    """사용자 정정(2026-08-27, 01-2608-3-2673 발송본 대조): 토지건물은 등기번호·소재지 안 넣고,
    토지 담보종류=지목, 기계기구=기계기구/기타부동산(단독시설), 건물 평가단가=감정가÷사정면적."""

    COMBOS = {
        "담보종류": frozenset({"공장", "공장용지", "도로", "기계기구"}),
        "담보용도": frozenset({"공장", "공장용지", "도로", "기타부동산(단독시설)"}),
        "지목": frozenset({"공장용지", "도로"}),
        "용도지역구분(신)": frozenset({"일반공업지역"}),
        "건물구조(신)": frozenset({"일반철골구조"}),
    }

    def _ctx(self):
        base = {"DABO_JONG": "토지건물", "DABO_JONG_SUB": "공장", "YG_AREA": "일반공업지역",
                "ADDR_NEW": "인천광역시 남동구 고잔동 144", "USE_APP_DATE": "20151117"}
        rows = [
            {**base, "NO": "1", "MUL_GUBUN": "토지", "JI_YOUNGDO": "공장용지", "GONG_AREA": "445", "SA_AREA": "445",
             "P_PRICE": "1,775,550,000", "DUNG_NO": "1247-2010-004648"},
            {**base, "NO": "1", "MUL_GUBUN": "건물", "JI_YOUNGDO": "일반철골구조", "GONG_AREA": "724.71",
             "SA_AREA": "724.71", "P_PRICE": "602,234,010", "DUNG_NO": "1247-2015-011869"},
            {**base, "NO": "3", "DABO_JONG": "기계기구", "DABO_JONG_SUB": "공장저당", "MUL_GUBUN": "기계기구",
             "JI_YOUNGDO": "", "GONG_AREA": "1", "SA_AREA": "1", "P_PRICE": "0", "DUNG_NO": ""},
        ]
        return make_context(properties=parse_mullist({"mullist0": rows}))

    def test_토지는_담보종류도_지목(self):
        land, build, machine = shinhan.build(self._ctx(), self.COMBOS)
        assert (land["담보종류"], land["담보용도"], land["지목"]) == ("공장용지", "공장용지", "공장용지")
        assert (build["담보종류"], build["담보용도"]) == ("공장", "공장")
        assert (machine["담보종류"], machine["담보용도"]) == ("기계기구", "기타부동산(단독시설)")

    def test_토지건물은_등기번호를_안_넣는다(self):
        for row in shinhan.build(self._ctx(), self.COMBOS):
            assert row["토지등기부번호"] is None and row["건물등기부번호"] is None

    def test_구분건물은_건물등기번호와_소재지를_넣는다(self):
        row = shinhan.build(make_context(), COMBOS)[0]     # 기본 fixture = 집합건물(2676)
        assert row["건물등기부번호"] == "17012018002982"
        assert row["소재지"] == "273"

    def test_건물_평가단가는_감정가_나누기_사정면적(self):
        land, build, machine = shinhan.build(self._ctx(), self.COMBOS)
        assert land["평가단가"] == "3990000"
        assert build["평가단가"] == "831000"
        assert machine["평가단가"] is None

    def test_건물_전용칸은_건물에만(self):
        land, build, machine = shinhan.build(self._ctx(), self.COMBOS)
        assert build["사용승인일"] == "2015-11-17" and land["사용승인일"] is None and machine["사용승인일"] is None
        assert land["용도지역구분(신)"] == "일반공업지역" and build["용도지역구분(신)"] is None


class TestShinhan구분건물:
    """사용자 정정(2026-08-27, 01-2608-3-2695 발송본): 구분건물 평가단가=0, 대지권면적은 호별(개요 호별 표)."""

    from bankon.parse import units as _units

    OVERVIEW = (
        "<table><tr><td>기 호</td><td>구 분</td><td>전유면적\n(㎡)</td><td>공용면적\n(㎡)</td><td>공급면적\n(㎡)</td>"
        "<td>대지권면적\n(㎡)</td><td>전용률(%)</td><td>용도</td></tr>"
        "<tr><td>가</td><td>제3층\n제4-304호</td><td>61.1366</td><td>46.0984</td><td>107.235</td><td>11.788</td><td>57.01</td><td>판매시설</td></tr>"
        "<tr><td>나</td><td>제3층\n제4-305호</td><td>48.116</td><td>36.2805</td><td>84.3965</td><td>9.2774</td><td>57.01</td><td>판매시설</td></tr>"
        "</table>"
    )

    def test_호별_표를_읽는다(self):
        rows = self._units.parse(self.OVERVIEW)
        assert [(r.mark, str(r.area_land_right), r.unit) for r in rows] == [
            ("가", "11.788", "제3층 제4-304호"), ("나", "9.2774", "제3층 제4-305호")]

    def test_대지권면적은_호별_평가단가는_0(self):
        rows = [{**MULLIST_ROW, "SNO": "가"}, {**MULLIST_ROW, "SNO": "나", "GONG_AREA": "48.11", "SA_AREA": "48.11"}]
        ctx = make_context(properties=parse_mullist({"mullist0": rows}), units=self._units.parse(self.OVERVIEW),
                           outline=Outline(address="대구광역시 수성구 신매동", area_land_right=Decimal("99")))
        a, b = shinhan.build(ctx, COMBOS)
        assert (a["대지권면적"], b["대지권면적"]) == ("11.78", "9.27")   # 2자리 버림
        assert a["평가단가"] == "0" and b["평가단가"] == "0"

    def test_호별_표가_없으면_대표값(self):
        ctx = make_context(outline=Outline(address="x", area_land_right=Decimal("12.5")))
        assert shinhan.build(ctx, COMBOS)[0]["대지권면적"] == "12.50"


class TestShinhan소재지:
    """'동미만' 칸 관례(발송 실물 2673·2695, 2026-08-27)."""
    from bankon.parse import machines as _machines
    from bankon.sources.scan import GongbuRow as _G

    MACHINE_TABLE = ("<table><tr><td>기 호</td><td>소재지</td><td>명 칭(종 류)</td><td>제작자 (공급자)</td>"
                     "<td>제작일자 (계약일자)</td><td>수 량</td></tr>"
                     "<tr><td>1</td><td>남동구 고잔동 144</td><td>전동 체인호이스트</td><td>극동호이스트(주)</td>"
                     "<td>미상</td><td>1식</td></tr></table>")

    def _ctx(self):
        base = {"DABO_JONG": "토지건물", "DABO_JONG_SUB": "공장", "YG_AREA": "일반공업지역", "USE_APP_DATE": "20151117"}
        rows = [
            {**base, "NO": "1", "MUL_GUBUN": "토지", "JI_YOUNGDO": "공장용지", "ADDR_NEW": "인천광역시 남동구 고잔동 144 ",
             "GONG_AREA": "445", "SA_AREA": "445", "P_PRICE": "1,775,550,000", "DUNG_NO": "1247-2010-004648"},
            {**base, "NO": "1", "MUL_GUBUN": "건물", "JI_YOUNGDO": "일반철골구조", "ADDR_NEW": "인천광역시 남동구 고잔동 144 ",
             "GONG_AREA": "724.71", "SA_AREA": "724.71", "P_PRICE": "602,234,010", "DUNG_NO": "1247-2015-011869"},
            {**base, "NO": "2", "DABO_JONG": "토지", "DABO_JONG_SUB": "도로", "MUL_GUBUN": "토지", "JI_YOUNGDO": "도로",
             "ADDR_NEW": "인천광역시 남동구 고잔동 144-12 ", "GONG_AREA": "43", "SA_AREA": "43", "P_PRICE": "0",
             "DUNG_NO": "1247-2015-011110"},
            {**base, "NO": "3", "DABO_JONG": "기계기구", "DABO_JONG_SUB": "공장저당", "MUL_GUBUN": "기계기구",
             "JI_YOUNGDO": "", "ADDR_NEW": "인천광역시 남동구 고잔동 144 ", "GONG_AREA": "1", "SA_AREA": "1",
             "P_PRICE": "0", "DUNG_NO": ""},
        ]
        gongbu = (self._G("1", "건물", "1247-2015-011869", "인천광역시 남동구 고잔동 144 주건축물제1동", Decimal("263.32"), "x"),
                  self._G("1", "토지", "1247-2010-004648", "인천광역시 남동구 고잔동 144", Decimal("445"), "공장용지"))
        return make_context(properties=parse_mullist({"mullist0": rows}), gongbu=gongbu,
                            machines=self._machines.parse(self.MACHINE_TABLE))

    def test_기계기구_표를_읽는다(self):
        rows = self._machines.parse(self.MACHINE_TABLE)
        assert [(r.mark, r.name, r.qty) for r in rows] == [("1", "전동 체인호이스트", "1식")]

    def test_토지건물_소재지(self):
        land, build, road, machine = shinhan.build(self._ctx(), TestShinhan토지건물.COMBOS)
        assert land["소재지"] == "144"
        assert build["소재지"] == "144 주건축물제1동"       # 공부스캔 건물 주소
        assert road["소재지"] == "144-12"
        assert machine["소재지"] == "144 전동 체인호이스트"   # 지번 + 기계 명칭

    def test_구분건물_소재지는_원문_그대로(self):
        row = {**MULLIST_ROW, "ADDR_NEW": "서울특별시 강동구 천호동 580 강동중흥에스클래스 제이스턴스퀘어동 제3층 제4-305호"}
        ctx = make_context(properties=parse_mullist({"mullist0": [row]}))
        assert shinhan.build(ctx, COMBOS)[0]["소재지"] == "580 강동중흥에스클래스 제이스턴스퀘어동 제3층 제4-305호"
