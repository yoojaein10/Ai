"""수협 담보(TBNKSSB24DAMB) 매핑 — 인계본(수협_하나_인계번들 2026-09-07) 실측 규칙을 고정한다(이식 2026-09-10).

문서 전체 회귀는 `tools/check_ssb_offline.py`(EXPECT 6건, .gam 필요)가 맡고 여기서는 DB 없이 규칙만 못 박는다.
값은 인계문서·EXPECT 에서 따왔다(주석에 문서번호).
"""
from __future__ import annotations

from decimal import Decimal

from bankon.mapping import ssb
from bankon.model import DocumentContext, Fee, Parties
from bankon.parse import detail
from bankon.parse.outline import Outline
from bankon.parse.round import RoundInfo
from bankon.sources.apw import Jibun


def context(tables: dict | None = None, **kwargs) -> DocumentContext:
    fields = {
        "doc_id": "01-2608-3-0000",
        "business_number": "2148746436",
        "details": detail.parse(tables or {}),
        "rounds": (RoundInfo(appraiser="유승민", client="삼천포수협 북부지점장"),),
        "fee": Fee(net=Decimal("12136080"), vat=Decimal("1219200"), total=Decimal("13411200"),
                   expense_parts=(Decimal("40000"), Decimal("16000"))),
        "parties": Parties(appraisers=("조경미",)),
    }
    fields.update(kwargs)
    return DocumentContext(**fields)


# 실측 2637 식 토지형(단일 필지로 축약): 3종일주, 722㎡, 단가 30,500,000.
LAND = {"land_list0": [
    {"NO": "1", "ADDR": "서울특별시 성북구 안암동5가", "JIBUN": "36-1", "JIMOK": "대",
     "YONGDO": "제3종일반주거지역", "AREA1": "722", "AREA2": "722",
     "DANGA": "30,500,000", "PRICE": "22,021,000,000"},
]}

# 집합물건(구분건물) — 실측 2609/1066 식: 건물면적(전용) 칸만, 공부/사정/단가/용도지역 비움.
SECTION = {"section_build0": [
    {"JIBUN": "135-8,"},
    {"NO": "가", "gujo": "철근콘크리트구조"},
    {"gujo": "제4층 제408호", "AREA1": "143.66", "AREA2": "143.66", "PRICE": "1,010,000,000"},
]}


class TestZone:
    def test_주거지역은_N종일주_전주(self):
        assert ssb.zone_ssb("제3종일반주거지역") == "3종일주"
        assert ssb.zone_ssb("제1종일반주거지역") == "1종일주"
        assert ssb.zone_ssb("제2종전용주거지역") == "2종전주"
        assert ssb.zone_ssb("준주거지역") == "준주거"

    def test_그밖은_지역_접미사만_뗀다(self):
        assert ssb.zone_ssb("일반상업지역") == "일반상업"          # 실측 2583
        assert ssb.zone_ssb("자연녹지지역") == "자연녹지"
        assert ssb.zone_ssb("계획관리지역") == "계획관리"

    def test_둘_나열이면_첫째만(self):
        assert ssb.zone_ssb("제2종일반주거지역, 자연녹지지역") == "2종일주"

    def test_모르는_표기는_비운다(self):
        assert ssb.zone_ssb("지구단위계획구역") is None
        assert ssb.zone_ssb(None) is None


class TestSido:
    def test_시도_축약(self):
        assert ssb._short_sido("서울특별시 강남구 대치동") == "서울 강남구 대치동"
        assert ssb._short_sido("인천광역시 중구 운서동") == "인천 중구 운서동"
        assert ssb._short_sido("전북특별자치도 전주시 완산구 효자동") == "전북 전주시 완산구 효자동"

    def test_축약할_게_없으면_그대로(self):
        assert ssb._short_sido("세종특별자치시 조치원읍") == "세종 조치원읍"
        assert ssb._short_sido(None) is None


class TestBuild:
    def test_토지형(self):
        values = ssb.build(context(LAND, jibun=Jibun(reg="11290", eub="12500", san="1", bun1="36", bun2="1")))
        assert values["물건구분코드"] == "토지"
        assert values["용도지역"] == "3종일주"
        assert values["공부면적"] == "722.00" and values["사정면적"] == "722.00"
        assert values["평가단가"] == "30500000"
        assert values["감정평가액"] == "22021000000"
        assert (values["본번지"], values["부번지"]) == ("36", "1")
        assert values["기   호"] == "1"
        assert values["건물면적"] is None

    def test_수수료는_원값이고_실비는_부가세_없이(self):
        values = ssb.build(context(LAND))
        assert values["순수수료"] == "12136080"
        assert values["부가세"] == "1219200"
        assert values["감정수수료"] == "13411200"
        assert values["실   비"] == "56000"            # 실측 2637=56,000 (지역농협식 ×1.1 아님)
        assert values["특별용역비"] == "0"

    def test_평가사는_감정평가표_서명자_우선(self):
        assert ssb.build(context(LAND))["평가사명"] == "유승민"          # par_player (apw 조경미 아님)
        no_round = context(LAND, rounds=())
        assert ssb.build(no_round)["평가사명"] == "조경미"              # 폴백 apw (실측 1310)

    def test_집합물건은_건물면적만(self):
        values = ssb.build(context(SECTION))
        assert values["물건구분코드"] == "집합물건(건물)"
        assert values["건물면적"] == "143.66"
        assert values["공부면적"] is None and values["사정면적"] is None
        assert values["평가단가"] is None and values["용도지역"] is None
        assert values["감정평가액"] == "1010000000"

    def test_라벨_없는_칸은_위치표기_키로(self):
        values = ssb.build(context(LAND))
        assert ssb.BOX_SITE in values and ssb.BOX_LEGAL_SGG in values and ssb.BOX_LEGAL_EMD in values
        assert ssb.BOX_LEGAL_SGG.endswith("[위좌]") and ssb.BOX_LEGAL_EMD.endswith("[위우]")
        assert values[ssb.BOX_LEGAL_SGG] is None          # jibun(법정동코드) 없음 → 비움

    def test_수협_폼에_없는_칸은_안_낸다(self):
        values = ssb.build(context(LAND))
        assert "건물명" not in values and "건물구조" not in values


class TestOutlineFallback:
    def test_토지_용도지역이_비면_개요값(self):
        tables = {"land_list0": [dict(LAND["land_list0"][0], YONGDO="")]}
        values = ssb.build(context(tables, outline=Outline(zone="일반상업지역")))
        assert values["용도지역"] == "일반상업"
