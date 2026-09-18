"""농협 담보(TBNKNHB24DAMB) 매핑 — 실폼 14건 대조로 확정한 규칙을 고정한다.

문서 전체 회귀는 `tools/check_nh_offline.py`(화면값 정답지와 자동 대조)가 맡고,
여기서는 DB 없이 규칙만 못 박는다. 값은 전부 실측 문서에서 따왔다(주석에 문서번호).
"""
from __future__ import annotations

from decimal import Decimal

from bankon.mapping import nh
from bankon.model import DocumentContext, Fee, Parties
from bankon.parse import detail
from bankon.parse.outline import Outline
from bankon.parse.round import RoundInfo
from bankon.parse.standard_land import StandardLand
from bankon.sources.apw import Jibun
from bankon.sources.scan import GongbuRow


def context(tables: dict | None = None, **kwargs) -> DocumentContext:
    fields = {
        "doc_id": "01-2608-3-0000",
        "business_number": "2148746436",
        "details": detail.parse(tables or {}),
        "rounds": (RoundInfo(client="농협은행 보문동지점장"),),
    }
    fields.update(kwargs)
    return DocumentContext(**fields)


# 실측 2616(토지형): 천안 구룡동 766, 주차장, 제2종일반주거지역, 597㎡.
LAND_2616 = {"land_list0": [
    {"NO": "1", "ADDR": "충청남도", "JIBUN": "766", "JIMOK": "주차장",
     "YONGDO": "제2종일반주거지역", "AREA1": "597", "AREA2": "597",
     "DANGA": "852,000", "PRICE": "508,644,000"},
]}

# 실측 2625(건물형): 하남 망월동 968-1 미사센트럴프라자 제4층 제408호·409호(2물건).
BUILD_2625 = {"section_build0": [
    {"JIBUN": "968-1,"},
    {"NO": "가", "gujo": "철근콘크리트구조"},
    {"gujo": "제4층 제408호", "AREA1": "90.48", "AREA2": "90.48", "PRICE": "533,000,000"},
    {"NO": "나", "gujo": "철근콘크리트구조"},
    {"gujo": "제4층 제409호", "AREA1": "96.72", "AREA2": "96.72", "PRICE": "570,000,000"},
]}


class TestVariant:
    def test_토지형은_지목_용도지역_공부면적을_낸다(self):
        values = nh.build(context(LAND_2616))
        assert values["공부지목"] == "주차장"
        assert values["공부면적"] == "597.00"
        assert "건물명" not in values and "공부면적(전용면적)" not in values

    def test_층과_호가_붙어_있어도_호만_읽는다(self):
        # 실측 2345: `제4층제402호` 를 앞의 `제` 부터 먹으면 `4층제402` 가 된다.
        tables = {"section_build0": [
            {"JIBUN": "16-18"},
            {"NO": "가", "gujo": "철근콘크리트구조"},
            {"gujo": "제4층제402호", "AREA1": "59.9", "AREA2": "59.9", "PRICE": "300,000,000"},
        ]}
        values = nh.build(context(tables))
        assert values["호"] == "402" and values["해당층수"] == "4"

    def test_건물형은_건물칸을_낸다(self):
        values = nh.build(context(BUILD_2625))
        assert values["공부면적(전용면적)"] == "90.48"
        assert values["호"] == "408" and values["해당층수"] == "4"
        assert "공부지목" not in values and "용도지역" not in values

    def test_지역농협만_할인블록을_낸다(self):
        fee = Fee(net=Decimal("473474"), vat=Decimal("58600"), subtotal=Decimal("586000"),
                  total=Decimal("644600"), expense_extra=Decimal("300"),
                  expense_parts=(Decimal("3000"), Decimal("99400"), Decimal("10000")))
        bank = nh.build(context(LAND_2616, fee=fee))
        assert "감정료합계(절사 전)" not in bank
        coop = nh.build(context(LAND_2616, fee=fee,
                                rounds=(RoundInfo(client="군자농협 시화지점장"),)))
        assert coop["감정료합계(절사 전)"] == "586174"       # 473,474 + 112,700
        assert coop["감정료합계(절사 후)"] == "586000"       # SUSUSUM
        assert coop["실비합계(절사 전)"] == "112700"
        assert coop["대출 실행시 청구수수료"] == "644600"

    def test_지역농협_판정(self):
        assert nh.is_local_coop(context(rounds=(RoundInfo(client="군자농협 시화지점장"),)))
        assert not nh.is_local_coop(context(rounds=(RoundInfo(client="농협은행 안산시지부장"),)))
        assert not nh.is_local_coop(context(rounds=()))    # 모르면 농협은행으로 본다


class TestFee:
    # 실측 2645: SUSU 772,720 + 실비 220,200 → 절사 992,000 → 부가세 99,200 → 총 1,091,200
    FEE = Fee(net=Decimal("772720"), vat=Decimal("99200"), subtotal=Decimal("992000"),
              total=Decimal("1091200"), expense_base=Decimal("220000"),
              expense_parts=(Decimal("9000"), Decimal("191200"), Decimal("20000")))

    def test_농협은행_실비는_구성항목합_부가세없음(self):
        # 합계필드(SILBISUM 220,000)가 아니라 구성항목 합(220,200)이 화면값이다.
        values = nh.build(context(LAND_2616, fee=self.FEE))
        assert values["실  비"] == "220200"
        assert values["감정평가(순)수수료"] == "772720"
        assert values["부가가치세"] == "99200"
        assert values["감정수수료"] == "1091200"
        assert values["특별용역비"] == "0"

    def test_지역농협_실비는_절사후_부가세포함(self):
        # 실측 2445: 112,700 → 절사 112,000 → ×1.1 = 123,200 이 화면값.
        fee = Fee(net=Decimal("473474"), expense_extra=Decimal("300"),
                  expense_parts=(Decimal("3000"), Decimal("99400"), Decimal("10000")))
        values = nh.build(context(LAND_2616, fee=fee,
                                  rounds=(RoundInfo(client="군자농협 시화지점장"),)))
        assert values["실  비"] == "123200"
        assert values["실비합계(절사 전)"] == "112700"      # 같은 값의 절사 전


class TestLandRules:
    def test_지목을_원문대로_쓴다(self):
        # 신한·국민은 `대`를 `대지`로 바꾸지만 농협 화면은 `대` 그대로다(실측 2497·2461·2445).
        values = nh.build(context({"land_list0": [
            {"NO": "1", "JIMOK": "대", "YONGDO": "제1종전용주거지역",
             "AREA1": "330.6", "AREA2": "330.6", "PRICE": "3,669,660,000"}]}))
        assert values["공부지목"] == "대"

    def test_용도지역은_대분류만(self):
        # 실측 2616 제2종일반주거지역→일반주거지역, 2497 제1종전용주거지역→전용주거지역.
        assert nh.zone_grade("제2종일반주거지역") == "일반주거지역"
        assert nh.zone_grade("제1종전용주거지역") == "전용주거지역"
        assert nh.zone_grade("계획관리지역") == "계획관리지역"
        assert nh.zone_grade("자연녹지지역") == "자연녹지지역"
        assert nh.zone_grade(None) is None

    def test_용도지역이_잘렸으면_개요로(self):
        values = nh.build(context({"land_list0": [
            {"NO": "1", "JIMOK": "대", "YONGDO": "제2종", "PRICE": "100"}]},
            outline=Outline(zone="제2종일반 주거지역")))
        assert values["용도지역"] == "일반주거지역"

    def test_일단지_묶음머리는_그_필지_몫을_쓴다(self):
        # 실측 2399: 머리행 AREA2(8,139)·PRICE 는 묶음 합계다. 화면은 2,612㎡ 와
        # 2,612 × 235,000 = 613,820,000 을 쓴다.
        values = nh.build(context({"land_list0": [
            {"NO": "1", "JIBUN": "815-1", "JIMOK": "답", "YONGDO": "자연녹지지역",
             "AREA1": "2612", "AREA1RB": "<", "AREA2": "8139", "DANGA": "235,000",
             "PRICE": "1,912,665,000"},
            {"NO": "2", "JIBUN": "815-3", "JIMOK": "답", "YONGDO": "자연녹지지역",
             "AREA1": "2466"},
            {"NO": "3", "JIBUN": "815-5", "JIMOK": "답", "YONGDO": "자연녹지지역",
             "AREA1": "3061", "AREA1RB": ">"},
        ]}, total_amount=Decimal("1912665000")))
        assert values["공부면적"] == "2612.00" and values["사정면적"] == "2612.00"
        assert values["감정평가액"] == "613820000"
        assert values["평가금액"] == "1912665000"          # 문서 총액은 따로

    def test_평가금액과_감정평가액은_다른_칸(self):
        # 실측 2625: 문서 총액 1,103,000,000 / 물건① 533,000,000.
        values = nh.build(context(BUILD_2625, total_amount=Decimal("1103000000")))
        assert values["평가금액"] == "1103000000"
        assert values["감정평가액"] == "533000000"

    def test_평가금액은_감정평가표_총액이다(self):
        # 실측 2645: 표가 2장이지만 둘 다 338,000,000 → 화면도 338,000,000(문서 총액 676M 아님).
        values = nh.build(context(BUILD_2625, total_amount=Decimal("676000000"), rounds=(
            RoundInfo(index=0, amount=Decimal("338000000")),
            RoundInfo(index=1, amount=Decimal("338000000")))))
        assert values["평가금액"] == "338000000"

    def test_표별_총액이_갈리면_평가금액을_비운다(self):
        # 화면이 어느 표를 보는지 못 가른다 → 틀린 값을 넣느니 비운다.
        values = nh.build(context(BUILD_2625, total_amount=Decimal("676000000"), rounds=(
            RoundInfo(index=0, amount=Decimal("338000000")),
            RoundInfo(index=1, amount=Decimal("400000000")))))
        assert values["평가금액"] is None


class TestGuards:
    """검증에서 드러난 잠재 결함들 — 화면에 안 보이던 물건에서 틀린 값을 타이핑하던 자리."""

    # 실측 2461 물건②: land_list 의 **건물** 유닛인데 묶음괄호가 붙어 있다(층별 면적 묶음).
    # 이때 PRICE 는 그 건물의 평가액이므로 토지 규칙(AREA1×단가)을 쓰면 안 된다.
    BUILDING_GROUP = {"land_list0": [
        {"NO": "1", "JIBUN": "815", "JIMOK": "대", "YONGDO": "계획관리지역",
         "AREA1": "396", "AREA2": "396", "DANGA": "258,000", "PRICE": "102,168,000"},
        {"NO": "가", "JIBUN": "815", "JIMOK": "제2종", "YONGDO": "경량철골구조"},
        {"YONGDO": "1층2층", "AREA1": "64.71", "AREA1RB": "<", "AREA2": "82.05",
         "DANGA": "900,000", "PRICE": "73,845,000"},
    ]}

    def test_건물_묶음머리에는_토지_규칙을_안_쓴다(self):
        values = nh.build(context(self.BUILDING_GROUP), "2")
        assert values["감정평가액"] == "73845000"        # 64.71 × 900,000 = 58,239,000 아님

    def test_평가단가는_토지에서만(self):
        # land_list 건물행에도 DANGA 가 있어 그대로 쓰면 건물형 화면(실측 전건 0/공란)에 샌다.
        land = nh.build(context(self.BUILDING_GROUP))
        assert land["평가단가"] == "258000"
        building = nh.build(context(self.BUILDING_GROUP), "2")
        assert building["평가단가"] is None

    def test_용도지역이_용도지역_꼴이_아니면_비운다(self):
        # NO 열이 없는 순수 건물 문서는 kind 가 테이블 폴백으로 '토지'가 된다 — 그때
        # YONGDO 에 든 층 조각('지2층')을 용도지역 칸에 넣으면 안 된다.
        values = nh.build(context({"land_list0": [
            {"JIBUN": "1", "YONGDO": "지2층", "AREA1": "206.75", "PRICE": "434,175,000"}]}))
        assert values["용도지역"] is None

    def test_잘린_지목은_비운다(self):
        # 명세표 JIMOK 이 칸 폭 때문에 잘려 온다('공장용지'→'장'). 콤보에 없는 값이라 위험하다.
        assert nh.land_category("장") is None
        assert nh.land_category("주유소") is None
        assert nh.land_category("공장용지") == "공장용지"
        assert nh.land_category("대") == "대"          # 대지로 바꾸지 않는다

    def test_지역농협은_작성자_콤보를_비운다(self):
        # 실측 2445·2388·2374: 소스에 값이 있어도 화면 콤보 6칸이 전부 공란이다.
        parties = Parties(boss="정우종", appraisers=("서현수",), reviewer="김형수")
        coop = nh.build(context(LAND_2616, parties=parties,
                                rounds=(RoundInfo(client="군자농협 시화지점장"),)))
        assert coop["대표,지사장"] is None and coop["심사자"] is None
        assert coop["평가사명1"] is None
        assert coop["평가사명"] == "서현수"            # 텍스트 칸은 채워져 있다
        bank = nh.build(context(LAND_2616, parties=parties))
        assert bank["대표,지사장"] == "정우종" and bank["평가사명1"] == "서현수"

    def test_일단지_범위는_다음_묶음에서_멈춘다(self):
        """범위 계산 자체는 살려 둔다 — 화면 표기 규칙이 정해지면 바로 켤 수 있게.

        한 표에 묶음이 둘 이상일 수 있다(실측 2458) — 번호가 안 이어지면 끊는다.
        """
        ctx = context({"land_list0": [
            {"NO": "1", "JIMOK": "대", "YONGDO": "자연녹지지역", "AREA1": "100",
             "AREA1RB": "<", "AREA2": "300", "DANGA": "1,000", "PRICE": "300,000"},
            {"NO": "2", "JIMOK": "대", "YONGDO": "자연녹지지역", "AREA1": "100"},
            {"NO": "11", "JIMOK": "대", "YONGDO": "자연녹지지역", "AREA1": "50",
             "AREA1RB": "<", "AREA2": "50"},
        ]})
        assert nh._group_span(ctx, ctx.details[0]) == "기호 1~2"
        assert nh.build(ctx)["일단지등 기호"] is None      # 화면 표기 제각각이라 안 채운다

    def test_건물명_조각은_비운다(self):
        # 실측 2025 순회: `s0`·`10` 이 건물명 칸에 들어갔다 — 한글 이름이 아니면 조각이다.
        for text in ("서울시 강남구 역삼동 648-26 s0 제4층 제402호",
                     "서울시 강남구 역삼동 648-26 10 제4층 제402호"):
            ctx = context(BUILD_2625, site_full=text, outline=Outline(address=text))
            assert nh.build(ctx)["건물명"] is None, text

    def test_콤보에_없는_용도지역은_비운다(self):
        # 실측: `개발제한구역` 은 농협 콤보 20종에 없다(화면은 `자연녹지지역` 을 쓴다).
        values = nh.build(context({"land_list0": [
            {"NO": "1", "JIMOK": "대", "YONGDO": "개발제한구역", "PRICE": "100"}]}))
        assert values["용도지역"] is None
        assert nh.zone_grade("개발제한구역") is None
        assert nh.zone_grade("제2종일반주거지역") == "일반주거지역"   # 목록에 있는 값은 그대로

    def test_입력자성명은_발송담당(self):
        # apw_masterex.Sendman → 직원표 EMP (실측 14/14).
        values = nh.build(context(LAND_2616, parties=Parties(sender="이예진")))
        assert values["입력자성명"] == "이예진"
        assert values["입력자연락처"] is None          # 이 DB 에 전화번호가 없다


class TestBuildingRules:
    def test_구조는_원문_표기를_지킨다(self):
        """농협 화면은 소스 원문을 따른다 — 국민(`…구조` 통일)과 규칙이 다르다.

        73건 순회로 두 방식을 재 봤다: 원문 유지 4건 불일치 / `…구조` 통일 7건 불일치.
        """
        values = nh.build(context({"section_build0": [
            {"NO": "가", "gujo": "철근콘크리트조"},
            {"gujo": "제2층 제201호", "AREA1": "301.47", "PRICE": "2,490,000,000"}]}))
        assert values["건물구조"] == "철근콘크리트조"
        # 지붕·괄호 부기는 여전히 뗀다.
        roofed = nh.build(context({"section_build0": [
            {"NO": "가", "gujo": "벽돌조"},
            {"gujo": "제1층 제101호", "AREA1": "50", "PRICE": "100,000,000"}]},
            outline=Outline(struct="벽돌조 / 기와지붕")))
        assert roofed["건물구조"] == "벽돌조"

    def test_건물명이_아닌_것은_비운다(self):
        # 지번 뒤에서 이름을 떼다 층·동·호 표기를 집어 오면 그건 건물명이 아니다.
        for text in ("서울시 강남구 역삼동 648-26 제4층 제402호",
                     "서울시 강남구 역삼동 648-26 101동 제1층 제145호"):
            ctx = context(BUILD_2625, site_full=text, outline=Outline(address=text))
            assert nh.build(ctx)["건물명"] != "제4층"
            assert nh.build(ctx)["건물명"] != "101동"

    def test_이름_뒤_동번호를_뗀다(self):
        # 실측 `퍼스트포레2동` → 화면 `퍼스트포레`.
        ctx = context(BUILD_2625,
                      site_full="경기도 하남시 망월동 968-1 퍼스트포레2동 제4층 제408호")
        assert nh.build(ctx)["건물명"] == "퍼스트포레"

    def test_일단지등_기호는_비운다(self):
        # 화면 표기가 `기호1)~6)`·`기호12)`·`1` 로 제각각이라 형식을 못 맞춘다.
        values = nh.build(context({"land_list0": [
            {"NO": "1", "JIMOK": "답", "YONGDO": "자연녹지지역", "AREA1": "2612",
             "AREA1RB": "<", "AREA2": "8139", "DANGA": "235,000", "PRICE": "1,912,665,000"},
            {"NO": "2", "JIMOK": "답", "YONGDO": "자연녹지지역", "AREA1": "2466"},
        ]}))
        assert values["일단지등 기호"] is None

    def test_동은_제N동_표기일_때만(self):
        # 소재지의 행정동('망월동')을 건물 동으로 오인하면 안 된다.
        values = nh.build(context(BUILD_2625, site_full="경기도 하남시 망월동 968-1 미사센트럴프라자"))
        assert values["동"] is None
        with_dong = nh.build(context(BUILD_2625,
                                     site_full="서울특별시 성동구 도선동 69 성동삼성쉐르빌 제101동 제145호"))
        assert with_dong["동"] == "101"

    def test_건물명은_공부스캔_주소가_1순위(self):
        # 다물건 문서에서는 문서 대표 주소가 다른 물건을 가리킨다(실측 2645).
        ctx = context(BUILD_2625,
                      site_full="경기도 의왕시 오전동 174외대현테크노월드 802호",
                      gongbu=(GongbuRow(
                          seq_no="2", kind="건물", unique_no="1341-2021-002035",
                          address="경기도 안양시 동안구 호계동 900 에이스하이테크시티범계 제4층 제408호",
                          area=Decimal("90.48"), note=None),))
        assert nh.build(ctx)["건물명"] == "에이스하이테크시티범계"

    def test_건물명은_개요_따옴표로_물러선다(self):
        ctx = context(BUILD_2625,
                      outline=Outline(address='서울특별시 서대문구 영천동 69-20외 160필지 "경희궁 유보라"'))
        assert nh.build(ctx)["건물명"] == "경희궁 유보라"

    def test_내용_잔존년수는_비운다(self):
        # 실측 화면은 전부 0 이지만 소스가 없다 — 사람이 넣는다.
        values = nh.build(context(BUILD_2625))
        assert values["내용년수"] is None and values["잔존년수"] is None


class TestHeaderFields:
    def test_담보번호와_소유자명(self):
        values = nh.build(context(
            LAND_2616, client_doc_no="5001917641",
            rounds=(RoundInfo(client="농협은행 성동금융센터장", owner="주식회사 안현"),)))
        assert values["담보번호"] == "5001917641"
        assert values["소유자명"] == "주식회사 안현"

    def test_평가사와_심사자(self):
        values = nh.build(context(LAND_2616, parties=Parties(
            boss="정우종", appraisers=("김기석", "이준희"), reviewer="최병산")))
        assert values["평가사명"] == values["평가사명1"] == "김기석"
        assert values["평가사명2"] == "이준희" and values["평가사명3"] is None
        assert values["대표,지사장"] == "정우종" and values["심사자"] == "최병산"

    def test_심사자는_감정평가표로_물러선다(self):
        values = nh.build(context(LAND_2616,
                                  rounds=(RoundInfo(client="농협은행", reviewer="장재원"),)))
        assert values["심사자"] == "장재원"

    def test_지번은_명세행이_우선(self):
        values = nh.build(context(LAND_2616, jibun=Jibun(
            reg="44131", eub="12000", san="1", bun1="999", bun2="9")))
        assert (values["본번지"], values["부번지"]) == ("766", None)
        assert values["번지구분"] == "일반"

    def test_물건종류는_비운다(self):
        # 화면 콤보가 은행 분류(집합상가·아파트형공장·기타토지)라 소스에서 못 낸다.
        assert nh.build(context(LAND_2616, outline=Outline(usage="상업용")))["물건종류"] is None

    def test_표준지(self):
        values = nh.build(context(LAND_2616, standard_land=StandardLand(
            address="대부북동1472-5", price=Decimal("280400"), base_date="2026-01-01")))
        assert values["표준지소재지"] == "대부북동1472-5"
        assert values["표준지공시지가"] == "280400"
        assert values["공시기준일"] == "2026-01-01"

    def test_일련번호는_내지_않는다(self):
        # 화면이 관리하는 앵커라 쓰지 않는다(form.ANCHOR_LABELS).
        assert "일련번호" not in nh.build(context(LAND_2616))


class TestPositionalBoxes:
    """라벨이 없어 **위치**로 짚는 세 칸 — 부동산구분·법정동코드·소재지."""

    def test_부동산구분은_명세행_종류(self):
        assert nh.build(context(LAND_2616))[nh.BOX_KIND] == "토지"
        assert nh.build(context(BUILD_2625))[nh.BOX_KIND] == "건물"

    def test_소재지는_대표주소로_물러선다(self):
        # 공부 스캔이 없는 건(지역농협)은 `apw_masterex.ADDR` 을 그대로 쓴다.
        values = nh.build(context(LAND_2616, site_address="충청남도 천안시 동남구 구룡동"))
        assert values[nh.BOX_SITE] == "충청남도 천안시 동남구 구룡동"

    def test_소재지는_공부스캔이_우선(self):
        # 실측 2645: 대표 주소는 다른 물건(의왕시)을 가리키고 화면은 안양시를 보여 준다.
        scan = (GongbuRow(seq_no="2", kind="토지", unique_no="1341-2021-002035", note=None,
                          area=Decimal("597"),
                          address="경기도 안양시 동안구 호계동 900 에이스하이테크시티 제2층 제201호"),)
        values = nh.build(context(LAND_2616, gongbu=scan,
                                  site_address="경기도 의왕시 오전동"))
        assert values[nh.BOX_SITE] == "경기도 안양시 동안구 호계동"

    def test_법정동코드는_대표소재지와_같을_때만(self):
        jibun = Jibun(reg="44131", eub="12000", san="1", bun1="766", bun2=None)
        same = nh.build(context(LAND_2616, jibun=jibun,
                                site_address="충청남도 천안시 동남구 구룡동"))
        assert same[nh.BOX_LEGAL_CODE] == "4413112000"

    def test_다른_동에_있는_물건이면_법정동코드를_비운다(self):
        # 코드는 문서 단위 값 하나뿐이라, 다물건 건에서 그대로 쓰면 틀린 코드가 된다.
        scan = (GongbuRow(seq_no="2", kind="토지", unique_no="1341-2021-002035", note=None,
                          area=Decimal("597"),
                          address="경기도 안양시 동안구 호계동 900"),)
        values = nh.build(context(LAND_2616, gongbu=scan,
                                  site_address="경기도 의왕시 오전동",
                                  jibun=Jibun(reg="41430", eub="10500", san="1",
                                              bun1="174", bun2=None)))
        assert values[nh.BOX_SITE] == "경기도 안양시 동안구 호계동"
        assert values[nh.BOX_LEGAL_CODE] is None


class TestDongPart:
    def test_지번_앞까지_자른다(self):
        assert nh._dong_part("경기도 안양시 동안구 호계동 900 에이스하이테크시티 제2층") \
            == "경기도 안양시 동안구 호계동"
        assert nh._dong_part("경상남도 창녕군 창녕읍 교리 815-1") == "경상남도 창녕군 창녕읍 교리"

    def test_산번지도_지번이다(self):
        assert nh._dong_part("강원특별자치도 홍천군 서면 반곡리 산 12-3") \
            == "강원특별자치도 홍천군 서면 반곡리"

    def test_지번이_없으면_그대로(self):
        assert nh._dong_part("경기도 하남시 망월동") == "경기도 하남시 망월동"

    def test_빈값(self):
        assert nh._dong_part(None) is None and nh._dong_part("  ") is None


class TestDongFromAddress:
    """건물 `동` 은 **지번 뒤**에서만 찾는다 — 앞쪽엔 `제기동` 같은 법정동이 있다."""

    def test_제기동을_건물동으로_오인하지_않는다(self):
        values = nh.build(context(BUILD_2625,
                                  site_full="서울특별시 동대문구 제기동 892-51 제3층 제301호"))
        assert values["동"] is None

    def test_진짜_동표기는_잡는다(self):
        values = nh.build(context(BUILD_2625,
                                  site_full="경기도 수원시 권선구 곡반정동 123 제101동 제4층 제408호"))
        assert values["동"] == "101"

    def test_지번뒤_자르기(self):
        assert nh._after_jibun("서울특별시 동대문구 제기동 892-51 제3층") == "892-51 제3층"
        assert nh._after_jibun("제4층 제408호") == "제4층 제408호"   # 지번이 없으면 통째로
        assert nh._after_jibun(None) is None
