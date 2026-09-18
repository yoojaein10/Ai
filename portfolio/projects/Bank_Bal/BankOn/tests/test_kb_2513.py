"""2513(국민 파주 오도동 5-4·5-16 + 5-17·27-6 도로 평가외) — 물건종류가 안 들어간 원인 2가지(2026-09-17, 1.png).

담당자 제보: 물건 1·2 의 물건종류가 빈 채로 저장됐다. 의견서 원문에는 용도가 **있었다** —
읽지 못한 쪽이 둘이었다.

  ① 의견서 '2. 건물' 표 머리글이 `공부상 용도(현황 용도)` 인데 파서는 `용도`/`용 도` 정확 일치만 봤다
     → use 가 통째로 None (buildings._index_of 에 부분 일치 폴백 추가)
  ② 셀 안에서 줄바꿈돼 `제2종근린 생활시설 (제조업소)` 로 들어오는데 키워드는 `근린생활` 이라 또 빗나갔다
     → building_object_type 에서 공백 제거(unit_object_type 은 종전부터 떼고 있었다)
"""
from __future__ import annotations

from decimal import Decimal

from bankon.mapping import kookmin
from bankon.model import DocumentContext
from bankon.parse import buildings
from bankon.parse.detail import DetailRow
from bankon.parse.standard_land import StandardLand
from bankon.sources.apw import Jibun

# 1.png 실물 머리글·값 그대로(셀 안 줄바꿈 포함)
BODY_2513 = (
    '<table>'
    '<tr><td>기호</td><td>소재지</td><td>공부상 용도\n(현황 용도)</td><td>구조/지붕</td>'
    '<td>연면적(㎡)</td><td>층 수</td><td>사용승인일자</td></tr>'
    '<tr><td>가</td><td>오도동\n5-4</td><td>제2종근린\n생활시설\n(제조업소)</td><td>일반철골구조\n/기타지붕</td>'
    '<td>307.2</td><td>지상 1층</td><td>2007.11.14</td></tr>'
    '<tr><td>나</td><td>오도동\n5-16</td><td>제1종근린\n생활시설\n(제조업소)</td><td>일반철골구조\n/기타지붕</td>'
    '<td>324</td><td>지상 1층</td><td>2008.05.07</td></tr>'
    '<tr><td>다</td><td>오도동\n5-16</td><td>제2종근린\n생활시설\n(사무실)</td><td>일반목구조\n/기타지붕</td>'
    '<td>73.6</td><td>지상 2층</td><td>2020.07.22</td></tr>'
    '</table>'
)


class TestBuildingUseHeader:
    def test_공부상_용도_머리글도_읽는다(self):
        rows = buildings.parse(BODY_2513)
        assert [r.mark for r in rows] == ["가", "나", "다"]
        assert all(r.use for r in rows), [r.use for r in rows]   # 종전엔 전부 None

    def test_용도_말고_다른_칸을_집지_않는다(self):
        rows = buildings.parse(BODY_2513)
        가 = buildings.by_mark(rows, "가")
        assert "근린" in 가.use and "제조업소" in 가.use
        assert 가.struct == "일반철골구조"                        # 구조 칸을 용도로 착각하지 않는다
        assert 가.approval_date == "2007-11-14"

    def test_종전_머리글도_그대로(self):
        body = BODY_2513.replace("공부상 용도\n(현황 용도)", "용 도")
        rows = buildings.parse(body)
        assert buildings.by_mark(rows, "나").use is not None


class TestBuildingObjectType:
    def test_셀_줄바꿈된_용도도_키워드가_맞는다(self):
        # 종전: '제2종근린 생활시설' 에 '근린생활' 이 없어 None → 화면 물건종류가 빈 채로 저장됐다
        assert kookmin.building_object_type("대", "제2종근린 생활시설 (제조업소)") == "일반상가-근린(점포)상가"
        assert kookmin.building_object_type("대", "제1종근린\n생활시설\n(제조업소)") == "일반상가-근린(점포)상가"

    def test_붙여쓴_용도는_종전대로(self):
        assert kookmin.building_object_type("대", "제2종 근린생활시설") == "일반상가-근린(점포)상가"

    def test_지목이_먼저다(self):
        assert kookmin.building_object_type("공장용지", "제2종근린 생활시설") == "일반공장"

    def test_근거가_없으면_여전히_None(self):
        assert kookmin.building_object_type("대", None) is None


def _land(no, jibun, cat, area, unit=None, amount=None, excluded=False, area_public=None):
    """평가외 필지는 명세표에 공부면적이 없다(area_public=None) — 2513 실측."""
    return DetailRow(table="land_list0", seq_no=no, jibun=jibun, category=cat, zone="계획관리",
                     area_public=Decimal(area_public) if area_public else None,
                     area_assessed=Decimal(area),
                     unit_price=Decimal(unit) if unit else None, amount=Decimal(amount) if amount else None,
                     excluded=excluded, unit_kind="토지")


def ctx_parcels() -> DocumentContext:
    return DocumentContext(
        doc_id="01-2608-3-2513", business_number="2148746436", gam_category="토지",
        jibun=Jibun(reg="41480", eub="11000", san="1", bun1="5", bun2="4"),
        standard_land=StandardLand(address="오도동 3-3", price=Decimal("575500"), base_date="2026-01-01"),
        details=(_land("1", "5-4", "대", "774", "1430000", "1106820000", area_public="774"),
                 _land("2", "5-17", "도로", "92", excluded=True),
                 _land("3", "27-6", "도로", "77", excluded=True)),
    )


class TestStandardLandOnEveryObject:
    """표준지 3칸은 문서 대표값 — 물건마다 같다(담당자 지시 2026-09-17). 종전엔 물건 1 에만 들어갔다."""

    def test_모든_물건에_표준지가_들어간다(self):
        _, objects = kookmin.build_kb(ctx_parcels())
        assert len(objects) == 3
        for obj in objects:
            assert obj["물건:표준지소재지"] == "오도동 3-3"
            assert obj["물건:표준지공시지가"] == "575500"
            assert obj["물건:공시기준일"] == "2026-01-01"


class TestPublicAreaFallback:
    """공부면적이 명세표에 없으면 사정면적으로(평가외 필지가 빈 채 저장됨 — 담당자 지시 2026-09-17)."""

    def test_평가외_필지는_사정면적을_공부면적으로(self):
        _, objects = kookmin.build_kb(ctx_parcels())
        for obj, area in zip(objects[1:], ("92.00", "77.00")):
            row = obj["_details"][0]
            assert row["세부:공부면적"] == area and row["세부:사정면적"] == area

    def test_공부면적이_있으면_그대로(self):
        _, objects = kookmin.build_kb(ctx_parcels())
        assert objects[0]["_details"][0]["세부:공부면적"] == "774.00"


class TestAlwaysOverwrite:
    """Bank24 는 물건 행을 추가하면 직전 행 값을 복사한다 — 물건 식별 칸은 항상 덮어쓴다.

    2513 실측: 물건 3 부번지가 물건 2 의 '16' 그대로 남고 우리 값 '17' 이 안 들어갔다.
    """

    def test_식별칸과_표준지는_항상_덮어쓴다(self):
        for label in ("물건:일련번호", "물건:물건종류", "물건:법정동코드", "물건:번지구분",
                      "물건:본번지", "물건:부번지", "물건:소재지",
                      "물건:표준지소재지", "물건:표준지공시지가", "물건:공시기준일"):
            assert label in kookmin.ALWAYS_OVERWRITE, label

    def test_금액_면적칸은_덮어쓰지_않는다(self):
        # 담당자가 손본 값을 지우면 안 되는 칸들
        for label in ("세부:감정평가액", "세부:평가단가", "세부:사정면적", "물건:비   고"):
            assert label not in kookmin.ALWAYS_OVERWRITE, label
