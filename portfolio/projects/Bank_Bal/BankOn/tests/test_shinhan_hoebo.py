"""의견서 없는 '감정평가회보' 건(2819) — 명세표 폴백·지하층·구분건물 소재지·행 복사(2026-09-14).

실측 01-2609-3-2819(신한 이태원, 집합상가 6호, 담당자 완성본 실화면 대조 reports/cmp_2819_20260914_104052.log):
  .gam 에 HWP 의견서가 없어(answer0.tt='감정평가회보') outline·units 가 전부 None → 대지권면적·총층수 빈칸.
  담당자 값: 대지권면적 15.80/7.73/…(명세표 '소유권대지권' AREA2) · 총층수 20(명세표 '20층') · 해당층수 -1(제지1층)
  · 소재지 '1601-10외 3필지 서초어반하이오피스텔 제지1층 제비01호'(등기 표제부 주소 그대로).
로컬 619건 중 의견서 없는 건 36건(회보 34건) — 2403·2831·2739 포함.
"""
from __future__ import annotations

from decimal import Decimal

from bankon.mapping import shinhan
from bankon.model import DocumentContext
from bankon.parse import detail
from bankon.parse.mullist import MullistRow
from bankon.sources.scan import GongbuRow

# section_build0 (2819) 축약 — 표제부 층별면적 + 호별 블록 2개
SPEC_ROWS = [
    {"ATTR": "CCCCCRRRL", "GUBUN": "D"},
    {"GUBUN": "D", "ADDR": "서울특별시", "JIBUN": "1601-10,", "JIMOK": "업무시설", "gujo": "철근콘크리트구조"},
    {"GUBUN": "D", "JIBUN": "1601-5", "JIMOK": "근린생활", "gujo": "20층"},
    {"GUBUN": "D", "ADDR": "서울특별시", "gujo": "1층", "AREA1": "681.06"},
    {"GUBUN": "D", "ADDR": "서초구", "gujo": "2층 ~ 19층 각", "AREA1": "625.64"},
    {"GUBUN": "D", "gujo": "20층", "AREA1": "488.3"},
    {"GUBUN": "D", "gujo": "지1층", "AREA1": "1,105.89"},
    {"GUBUN": "D", "gujo": "지5층", "AREA1": "926.11"},
    {"GUBUN": "D", "NO": "1", "ADDR": "동 소", "JIBUN": "1601-10", "JIMOK": "대", "gujo": "일반상업지역", "AREA1": "509.3"},
    {"GUBUN": "D", "gujo": "(내)"},
    {"GUBUN": "D", "NO": "가", "gujo": "철근콘크리트구조"},
    {"GUBUN": "D", "gujo": "제지1층 제비01호", "AREA1": "88.22", "AREA2": "88.22", "PRICE": "459,000,000", "BIGO": "비준가액"},
    {"GUBUN": "D", "gujo": "1, 2, 3, 4", "AREA1": "15.8", "BIGO": "101.24㎡"},
    {"GUBUN": "D", "gujo": "소유권대지권", "AREA1": "------", "AREA2": "15.8", "BIGO": "포함)"},
    {"GUBUN": "D", "AREA1": "1,382.1"},
    {"GUBUN": "D", "NO": "나", "gujo": "철근콘크리트구조"},
    {"GUBUN": "D", "gujo": "제지1층 제비02호", "AREA1": "43.18", "AREA2": "43.18", "PRICE": "225,000,000", "BIGO": "비준가액"},
    {"GUBUN": "D", "gujo": "소유권대지권", "AREA1": "------", "AREA2": "7.73", "BIGO": "포함)"},
]


class TestSpecExtras:
    def test_층수와_호별_대지권(self):
        x = detail.spec_extras({"section_build0": SPEC_ROWS, "section_build_20": []})
        assert x.ground_floors == 20            # '20층'·'2층 ~ 19층 각' 중 최대
        assert x.basement_floors == 5           # '지5층'
        assert x.land_rights == {"가": Decimal("15.8"), "나": Decimal("7.73")}
        assert x.land_right_for("가") == Decimal("15.8")
        assert x.land_right_for("다") is None and x.land_right_for(None) is None

    def test_호_표기의_층은_층수로_안_센다(self):
        x = detail.spec_extras({"section_build0": [{"NO": "가", "gujo": "철근콘크리트구조"},
                                                  {"gujo": "제3층 제301호", "PRICE": "1"}]})
        assert x.ground_floors is None and x.basement_floors is None

    def test_표가_없으면_빈값(self):
        x = detail.spec_extras({"land_list0": [{"NO": "1", "gujo": "3층"}]})
        assert x.ground_floors is None and x.land_rights == {}
        assert DocumentContext(doc_id="x", business_number="y").spec_extras.land_rights == {}

    def test_parse_는_그대로(self):
        # 기존 물건행 파싱은 영향 없음 — 회귀 방지
        rows = detail.parse({"section_build0": SPEC_ROWS})
        assert [r.amount for r in rows if r.amount] == [Decimal("459000000"), Decimal("225000000")]


class TestFloorNo:
    def test_지상(self):
        assert shinhan._floor_no("서울특별시 강동구 길동 415-9 제103동 제6층 제607호") == "6"

    def test_지하는_음수(self):
        assert shinhan._floor_no("서울특별시 서초구 서초동 1601-10 외 3필지 제지1층 제비01호") == "-1"
        assert shinhan._floor_no("… 제지하2층 제비201호") == "-2"

    def test_없으면_None(self):
        assert shinhan._floor_no("도곡리 356-2 외 1필지") is None
        assert shinhan._floor_no(None) is None


def _unit(mark: str, ho: str, area: str, amount: str, reg: str) -> MullistRow:
    return MullistRow(seq_no="1", mark=mark, collateral_group="집합건물", collateral_kind="집합상가",
                      object_kind="건물", struct_or_category="철근콘크리트구조", zone="일반상업지역",
                      address=f"서울특별시 서초구 서초동 1601-10 외 3필지 제지1층 제비{ho}호",
                      area_public=Decimal(area), area_assessed=Decimal(area), amount=Decimal(amount),
                      registry_no=reg, ledger_no="1165010800-3-16010010",
                      useful_years=50, remaining_years=43, approval_date="2018-12-26")


def ctx_2819() -> DocumentContext:
    return DocumentContext(
        doc_id="01-2609-3-2819", business_number="2148746436",
        properties=(_unit("가", "01", "88.22", "459000000", "1101-2019-000029"),
                    _unit("나", "02", "43.18", "225000000", "1101-2019-000030")),
        gongbu=(
            GongbuRow("1", "토지", "1101-2019-000030", "서울특별시 서초구 서초동 1601-10", Decimal("509.3"), "대"),
            GongbuRow("5", "건물", "1101-2019-000030",
                      "서울특별시 서초구 서초동 1601-10외 3필지 서초어반하이오피스텔 제지1층 제비02호",
                      Decimal("43.18"), "전유부분 철근콘크리트구조"),
        ),
        spec_extras=detail.spec_extras({"section_build0": SPEC_ROWS}),
    )


class TestBuild2819:
    def test_의견서_없어도_명세표로_대지권_총층수(self):
        a, b = shinhan.build(ctx_2819())
        assert a["대지권면적"] == "15.80" and b["대지권면적"] == "7.73"     # 화면 표기(소수 2자리)
        assert a["총층수"] == b["총층수"] == "20"
        assert a["해당층수"] == b["해당층수"] == "-1"

    def test_소재지는_등기번호가_맞는_공부스캔_주소(self):
        a, b = shinhan.build(ctx_2819())
        # '나' 만 공부스캔에 건물 행이 있다 → 건물명 포함. '가' 는 없으니 종전(mullist 주소) 그대로 — fail-closed
        assert b["소재지"] == "1601-10외 3필지 서초어반하이오피스텔 제지1층 제비02호"
        assert a["소재지"] == "1601-10 외 3필지 제지1층 제비01호"

    def test_의견서_값이_있으면_그쪽이_우선(self):
        from bankon.parse.outline import Outline
        ctx = ctx_2819()
        ctx = DocumentContext(**{**ctx.__dict__, "outline": Outline(floors_text="지하 5층 / 지상 12층", area_land_right=Decimal("9.9"))})
        a, _ = shinhan.build(ctx)
        assert a["총층수"] == "12" and a["대지권면적"] == "9.90"


class TestBelowDong:
    def test_외가_붙은_지번(self):
        assert shinhan._below_dong("서울특별시 서초구 서초동 1601-10외 3필지 서초어반하이오피스텔 제지1층 제비03호") \
            == "1601-10외 3필지 서초어반하이오피스텔 제지1층 제비03호"
