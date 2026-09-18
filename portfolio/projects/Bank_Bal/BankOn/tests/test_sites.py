"""다현장 문서 — 의견서가 현장별로 여러 장인 건에서 물건마다 현장을 고르는 규칙(2026-09-10).

실측 2818(기업, 발송완료 실화면 대조): 한 문서에 감정평가표가 2장 —
  ① 경기도 김포시 통진읍 옹정리 197-50 토지·건물(의견서 '토지건물의견서(옹정리)')
  ② 서울특별시 강남구 삼성동 52-9 구분건물 1호(의견서 '구분건물의견서(삼성동)')
대표 의견서 하나만 보던 종전 코드는 ②번 물건에 ①번 값(소재지·법정동코드·준공일자·용도지역)을 넣어
실화면과 7칸이 어긋났다. 로컬 표본 610건 중 이런 다현장 문서가 18건(2645 농협 ❌2 도 같은 원인).
"""
from __future__ import annotations

from decimal import Decimal

from bankon.mapping import ibk
from bankon.model import DocumentContext, Fee, Parties, SiteInfo
from bankon.parse import address
from bankon.parse.detail import DetailRow
from bankon.parse.outline import Outline
from bankon.sources.apw import Jibun
from bankon.sources.scan import GongbuRow


class TestJibunKey:
    def test_표기가_달라도_같은_지번(self):
        assert address.jibun_key("52-9,") == address.jibun_key("0052-0009") == "52-9"
        assert address.jibun_key("197-50외 1필지") == "197-50"
        assert address.jibun_key("산 12-3") == "12-3"

    def test_부번_0_은_본번만(self):
        assert address.jibun_key("708-0") == address.jibun_key("708") == "708"

    def test_지번이_없으면_None(self):
        assert address.jibun_key(None) is None
        assert address.jibun_key("가동") is None


class TestDongTail:
    def test_앞이_잘린_주소도_꼬리로_견준다(self):
        # 의견서 개요 소재지는 시도·시군구가 빠지기도 한다(2818 '옹정리 197-50')
        assert address.dong_tail("경기도 김포시 통진읍 옹정리 197-50") == "옹정리"
        assert address.dong_tail("옹정리 197-50") == "옹정리"
        assert address.dong_tail('서울특별시 강남구 삼성동 52-9외 "삼성 리치빌"') == "삼성동"

    def test_없으면_None(self):
        assert address.dong_tail(None) is None


SITE_A = SiteInfo(name="토지건물의견서(옹정리)",
                  outline=Outline(address="옹정리 197-50", zone="계획관리지역", approval_date="2021-10-20"))
SITE_B = SiteInfo(name="구분건물의견서(삼성동)", legal_code="1168010500",
                  outline=Outline(address='서울특별시 강남구 삼성동 52-9외 "삼성 리치빌"', approval_date="2003-03-21"),
                  legal_text="기호(1)~(3) 각 공히 준주거지역 , 지구단위계획구역(청담지구)")


def _ctx(**kw) -> DocumentContext:
    base = dict(doc_id="01-2609-3-2818", business_number="2148746436",
                sites=(SITE_A, SITE_B),
                legal_codes=(("서울특별시 강남구 삼성동", "1168010500"),))
    base.update(kw)
    return DocumentContext(**base)


class TestSiteFor:
    def test_현장이_하나면_늘_대표(self):
        one = _ctx(sites=(SITE_A,))
        assert one.site_for("52-9", "서울특별시 강남구 삼성동") is SITE_A     # 종전 동작 — 갈리지 않는다

    def test_지번으로_고른다(self):
        assert _ctx().site_for("52-9,") is SITE_B
        assert _ctx().site_for("197-50") is SITE_A

    def test_지번이_안_맞으면_소재지_법정동으로(self):
        # 197-51(도로 필지)은 어느 개요 소재지에도 없다 — 동으로 가린다
        assert _ctx().site_for("197-51", "경기도 김포시 통진읍 옹정리") is SITE_A

    def test_같은_동에_현장이_둘이면_지번이_가른다(self):
        # 실측 2602-3-0467: 부천 옥길동 775-7 / 795-1 — 동이 같아 지번으로만 갈린다
        a = SiteInfo(outline=Outline(address="경기도 부천시 소사구 옥길동 775-7번지"))
        b = SiteInfo(outline=Outline(address="경기도 부천시 소사구 옥길동 795-1번지"))
        ctx = _ctx(sites=(a, b))
        assert ctx.site_for("795-1", "경기도 부천시 소사구 옥길동") is b
        # 지번이 없으면 동이 둘 다 맞아 불명확 → 대표로 물러선다
        assert ctx.site_for(None, "경기도 부천시 소사구 옥길동") is a

    def test_불명확하면_대표(self):
        assert _ctx().site_for("999-9", "어디도 아닌 동") is SITE_A

    def test_대표_판정과_법정동코드(self):
        ctx = _ctx()
        assert ctx.is_primary_site(SITE_A) and not ctx.is_primary_site(SITE_B)
        assert ctx.legal_code_for("서울특별시 강남구 삼성동") == "1168010500"
        assert ctx.legal_code_for("경기도 김포시 통진읍 옹정리") is None      # 대표 현장은 APW 코드를 쓴다
        assert ctx.legal_code_for(None) is None

    def test_sites_가_비면_문서_값으로_대표를_만든다(self):
        ctx = DocumentContext(doc_id="x", business_number="y", outline=Outline(address="십정동 565-10"))
        assert ctx.primary_site.outline.address == "십정동 565-10"
        assert ctx.is_primary_site(ctx.primary_site)


def _row(**kw) -> DetailRow:
    base = dict(table="land_list0")
    base.update(kw)
    return DetailRow(**base)


def ctx_2818() -> DocumentContext:
    """2818 축약 — 옹정리 토지 1필지 + 삼성동 구분건물 1호(발송완료 실화면 2026-09-10 대조)."""
    return DocumentContext(
        doc_id="01-2609-3-2818", business_number="2148746436",
        parties=Parties(appraisers=("전영배",)),
        fee=Fee(net=Decimal("1512624"), vat=Decimal("169400"), total=Decimal("1863400")),
        jibun=Jibun(reg="41570", eub="25029", san="1", bun1="197", bun2="50"),
        outline=SITE_A.outline, sites=(SITE_A, SITE_B),
        legal_codes=(("서울특별시 강남구 삼성동", "1168010500"),),
        price_point_date="2026-09-09", total_amount=Decimal("1791601000"),
        gongbu=(
            GongbuRow("1", "토지", "1244-1996-136462", "경기도 김포시 통진읍 옹정리 197-50", Decimal("636"), "대"),
            GongbuRow("1", "토지", "1146-2003-005004", "서울특별시 강남구 삼성동 52-9", Decimal("519.1"), "대"),
            GongbuRow("4", "건물", "1146-2003-005004",
                      "서울특별시 강남구 삼성동 52-9외 2필지 삼성리치빌 제1층 제111호", Decimal("59.08"),
                      "전유부분 철근콘크리트조"),
        ),
        details=(
            _row(seq_no="1", location="경기도 김포시 통진읍 옹정리", jibun="197-50", category="대",
                 zone="계획관리지역", area_public=Decimal("1071"), area_assessed=Decimal("1071"),
                 unit_price=Decimal("831000"), amount=Decimal("890001000"), unit_kind="토지"),
            _row(table="section_build0", seq_no="가", location="제1층 제111호", jibun="52-9,",
                 struct="철근콘크리트조", area_public=Decimal("59.08"), area_assessed=Decimal("59.08"),
                 amount=Decimal("691000000"), unit_kind="건물"),
        ),
    )


class TestIbk2818:
    """실화면(발송완료, 담당자 작성본)과 같은 값이 나와야 한다 — 종전엔 아래 4가지가 김포 값이었다."""

    def _objects(self):
        return ibk.build_ibk(ctx_2818())[1]

    def test_옹정리_물건은_문서_대표값(self):
        land = self._objects()[0]
        assert land["물건:소재지"] == "경기도 김포시 통진읍 옹정리"
        assert land["물건:법정동코드"] == "4157025029"        # APW 문서 코드
        assert land["탭:용도지역"] == "계획관리지역"

    def test_삼성동_구분건물은_그_현장값(self):
        condo, condo_land = self._objects()[1], self._objects()[2]
        assert condo["물건:소재지"] == "서울특별시 강남구 삼성동"
        assert condo["물건:법정동코드"] == "1168010500"        # 주소로 찾은 코드(문서 코드 아님)
        assert condo["탭:준공일자"] == "2003-03-21"            # 삼성동 의견서(대표는 2021-10-20)
        assert condo_land["탭:용도지역"] == "준주거지역"         # 삼성동 의견서 공법관계(대표는 계획관리지역)

    def test_현장을_모르면_법정동코드를_비운다(self):
        # 코드를 못 찾은 다현장 물건에 문서 코드를 넣으면 **틀린 코드**가 된다 → 빈칸(사람이 채움)
        ctx = ctx_2818()
        objects = ibk.build_ibk(DocumentContext(**{**ctx.__dict__, "legal_codes": ()}))[1]
        assert objects[1]["물건:법정동코드"] is None
        assert objects[0]["물건:법정동코드"] == "4157025029"   # 대표 현장은 그대로


class TestHeaderObjectType:
    def test_이용상황_공업용만으로는_공장이_아니다(self):
        # 2818 실측: 지목 대 · 이용상황 공업용 · 건물 제2종근린생활시설 → 화면 '근린생활시설'
        header = ibk.build_ibk(DocumentContext(**{
            **ctx_2818().__dict__,
            "outline": Outline(address="옹정리 197-50", usage="공업용", building_use="제2종근린 생활시설"),
            "sites": (SiteInfo(outline=Outline(address="옹정리 197-50", usage="공업용",
                                               building_use="제2종근린 생활시설")), SITE_B),
        }))[0]
        assert header["헤더:물건종류"] == "근린생활시설"

    def test_지목_공장용지면_근생이어도_공장(self):
        # 2714 실측 — 등기 지목은 강한 신호라 그대로 둔다
        ctx = ctx_2818()
        rows = (
            _row(seq_no="1", location="포천시 소흘읍 고모리", jibun="595-3", category="공장용지",
                 zone="계획관리지역", area_public=Decimal("1000"), area_assessed=Decimal("1000"),
                 unit_price=Decimal("100000"), amount=Decimal("100000000"), unit_kind="토지"),
            _row(seq_no="가", location="동소", jibun="595-3,", category="제2종근린생활시설",
                 zone="철골구조", area_public=Decimal("187"), area_assessed=Decimal("187"),
                 unit_price=Decimal("500000"), amount=Decimal("93500000"), unit_kind="건물"),
        )
        header = ibk.build_ibk(DocumentContext(**{**ctx.__dict__, "details": rows, "sites": (SITE_A,)}))[0]
        assert header["헤더:물건종류"] == "공장"
