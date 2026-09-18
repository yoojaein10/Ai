"""국민 담보폼 `총층수/층수` — 라벨 하나에 칸이 **둘**이다(2026-09-10 실화면 1.png).

    총층수/층수  [ 7 ][ 1 ]      왼쪽 = 건물 총층수 · 오른쪽 = 이 물건이 있는 층

종전엔 왼쪽만 채워 오른쪽이 빈 채로 저장됐다 — 담당자 제보 '2804 구분건물 층수 누락'.
담당자가 완성해 둔 실화면을 읽어 규칙을 확정했다(reports/kb_floors_20260910_160640.log):

    문서    건물 층수   총층수(왼)   층수(오른)
    2804      1          7           1
    2715      1         13           1
    2742     12         27          12
    2788    지1          4          -1     ← 지하는 **음수**

지하 표기(`제지1층`)를 못 읽어 `1` 로 집던 것도 같이 고쳤다 — 안 고치면 오른쪽 칸에 +1 이 들어간다.
"""
from __future__ import annotations

from decimal import Decimal

from bankon.mapping import kookmin
from bankon.model import DocumentContext
from bankon.parse.detail import DetailRow
from bankon.parse.kb import KbSummary
from bankon.parse.outline import Outline
from bankon.sources.scan import GongbuRow


class TestFloorText:
    def test_지하_표기를_정리한다(self):
        assert kookmin._floor_text("지하 1") == "지1"
        assert kookmin._floor_text("지1") == "지1"
        assert kookmin._floor_text(" 12 ") == "12"
        assert kookmin._floor_text(None) is None


class TestFloorNumber:
    """오른쪽 칸 값 — 숫자만, 지하는 음수."""

    def test_지상층은_그대로(self):
        assert kookmin.floor_number("1") == "1"
        assert kookmin.floor_number("12") == "12"

    def test_지하층은_음수(self):
        assert kookmin.floor_number("지1") == "-1"
        assert kookmin.floor_number("지하 2") == "-2"

    def test_못_읽으면_비운다(self):
        for bad in (None, "", "옥탑", "1-2", "지"):
            assert kookmin.floor_number(bad) is None, bad


class TestUnitAddr:
    def test_지하_층호를_읽는다(self):
        # 실측 2788 공부스캔 '…제지1층 제비108호' — 종전 정규식은 층을 '1'(지상)로 집었다
        m = kookmin._UNIT_ADDR.search("서울특별시 강남구 개포동 1284 개포자이프레지던스 제개포자이스퀘어동 제지1층 제비108호")
        assert (kookmin._floor_text(m.group(1)), m.group(2)) == ("지1", "비108")

    def test_지상_층호는_종전대로(self):
        m = kookmin._UNIT_ADDR.search("서울특별시 송파구 문정동 628 가든파이브툴 제4층 제4-에이17호")
        assert (m.group(1), m.group(2)) == ("4", "4-에이17")

    def test_소재지_꼬리의_지하층(self):
        assert kookmin._floor_no("… 개포자이프레지던스 제개포스퀘어동 제지1층 비108호") == "지1"
        assert kookmin._floor_no("… 제4층 제403호") == "4"


def _condo_context(*, unit_addr: str, scan_addr: str, floors: str, area="105.2987") -> DocumentContext:
    """구분소유 문서 한 호 — 토지 필지가 없어 `_build_units` 경로를 탄다."""
    return DocumentContext(
        doc_id="01-2609-3-0000", business_number="2148746436",
        outline=Outline(address="개포동 1284", floors_text=floors, building_use="근린생활시설",
                        struct="철근콘크리트구조", approval_date="2025-01-02"),
        kb_summary=KbSummary(address=unit_addr, category="구분건물"),
        gongbu=(GongbuRow("1", "건물", "1101-2025-005586", scan_addr, Decimal(area), "전유부분 철근콘크리트구조"),),
        details=(DetailRow(table="section_build0", seq_no="가", struct="철근콘크리트구조",
                           area_public=Decimal(area), area_assessed=Decimal(area),
                           amount=Decimal("1000000000"), unit_kind="건물"),),
    )


class TestBuildFloors:
    def test_지상_구분건물(self):
        # 2804 꼴: 1층 103호, 지하 3층/지상 7층
        ctx = _condo_context(unit_addr="경기도 화성시 동탄구 산척동 723 풍산리치안타워 1층 103호",
                             scan_addr="경기도 화성시 동탄구 산척동 723 풍산리치안타워 제1층 제103호",
                             floors="지하 3층/지상 7층")
        obj = kookmin.build_kb(ctx)[1][0]
        assert obj["물건:건물 층수"] == "1"
        assert obj["물건:총층수/층수"] == "7"
        assert obj["물건:총층수/층수@2"] == "1"      # ← 종전엔 안 채워 빈 칸이었다
        assert obj["물건:호"] == "103"

    def test_지하_구분건물은_음수(self):
        # 2788 꼴: 지하 1층 비108호
        ctx = _condo_context(
            unit_addr="서울특별시 강남구 개포동 1284 개포자이프레지던스 제개포스퀘어동 제지1층 비108호",
            scan_addr="서울특별시 강남구 개포동 1284 개포자이프레지던스 제개포자이스퀘어동 제지1층 제비108호",
            floors="지하 3층 / 지상 4층")
        obj = kookmin.build_kb(ctx)[1][0]
        assert obj["물건:건물 층수"] == "지1"
        assert obj["물건:총층수/층수"] == "4"
        assert obj["물건:총층수/층수@2"] == "-1"
        assert obj["물건:호"] == "비108"            # 등기 표제부 표기(문서 대표주소 꼬리는 '108' 로 접두를 잃는다)

    def test_총층수를_모르면_왼쪽만_비운다(self):
        # 2742 꼴: 개요 '층수' 행에 세대수가 들어와 총층수를 모른다 → 왼쪽은 사람이, 오른쪽은 우리가 채운다
        ctx = _condo_context(unit_addr="경기도 파주시 동패동 415-13 파주운정3제일풍경채  604동 12층 1205호외",
                             scan_addr="경기도 파주시 동패동 415-13 파주운정3제일풍경채 제604동 제12층 제1205호",
                             floors="383세대")
        obj = kookmin.build_kb(ctx)[1][0]
        assert obj["물건:총층수/층수"] is None
        assert obj["물건:총층수/층수@2"] == "12"

    def test_토지_물건에는_안_넣는다(self):
        land = kookmin.build(DocumentContext(
            doc_id="01-2608-3-0000", business_number="2148746436",
            outline=Outline(address="십정동 565-10", floors_text="지상 3층"),
            details=(DetailRow(table="land_list0", seq_no="1", jibun="565-10", category="공장용지",
                               area_public=Decimal("100"), amount=Decimal("1000"), unit_kind="토지"),),
        ), "1")
        assert land["총층수/층수"] is None and land["총층수/층수@2"] is None
