"""2823(국민 홍제동, 포천 정교리 36 공장 + 37-1 답 평가외) 담당자 완성본 대조(2026-09-14, reports/cmp_2823_20260914_145138.log).

담당자 정정 3가지:
  ① 평가외 필지(37-1 '현황 도로', PRICE 글자)는 왼쪽 물건이 아니라 **물건 1 의 세부 토지행**(건물 뒤, 단가 1·금액 0)
     → ★2026-09-17 뒤집힘. 2881 담당자 완성본(512-5 대 / 512-2 전 / 512-6 도로 = 물건 3개)과 어긋나,
       사용자 확정으로 **본번·부번이 다르면 물건 1개**(규칙 A)로 되돌렸다. 물건 하나로 합치는 건 담당자가 직접 한다.
  ② 건물 공부면적 — 3동이 등기번호 하나(1154-1996-108929)를 같이 쓰면 공부스캔 층합계 495 가 동마다 들어가 틀린다 → 명세표 198/198/99
  ③ 현장조사서 특별용역비는 칸이 있으면 0(전 은행)
"""
from __future__ import annotations

from decimal import Decimal

from bankon.mapping import kookmin
from bankon.model import DocumentContext
from bankon.parse.detail import DetailRow
from bankon.sources.apw import Jibun
from bankon.sources.scan import GongbuRow


def _land(no, jibun, cat, area, unit=None, amount=None, excluded=False, note=None):
    return DetailRow(table="land_list0", seq_no=no, jibun=jibun, category=cat, zone="계획관리지역",
                     area_public=Decimal(area), area_assessed=Decimal(area),
                     unit_price=Decimal(unit) if unit else None, amount=Decimal(amount) if amount else None,
                     excluded=excluded, note=note, unit_kind="토지")


def _bld(mark, struct, area, unit, amount):
    head = DetailRow(table="land_list0", seq_no=mark, jibun="36", category="제2종", zone=struct, unit_kind="건물")
    body = DetailRow(table="land_list0", category="시설", zone="단층", area_public=Decimal(area), area_assessed=Decimal(area),
                     unit_price=Decimal(unit), amount=Decimal(amount), unit_kind="건물")
    return head, body


def ctx_2823() -> DocumentContext:
    b1 = _bld("가", "블럭조", "198", "245000", "48510000")
    b2 = _bld("나", "블록조", "198", "245000", "48510000")
    b3 = _bld("다", "조적조", "99", "456000", "45144000")
    return DocumentContext(
        doc_id="01-2609-3-2823", business_number="2148746436", gam_category="토지건물",
        jibun=Jibun(reg="41650", eub="33025", san="1", bun1="36", bun2=None),
        details=(_land("1", "36", "공장용지", "1645", "732000", "1204140000"), *b1, *b2, *b3,
                 _land("2", "37-1", "답", "21", excluded=True, note="현황 도로")),
        gongbu=(
            GongbuRow("1", "토지", "1154-1996-047488", "경기도 포천시 가산면 정교리 36", Decimal("1645"), "공장용지"),
            GongbuRow("1", "건물", "1154-1996-108929", "경기도 포천시 가산면 정교리 36", Decimal("198"), "블럭조 스레이트지붕 단층제2종 근린생활시설"),
            GongbuRow("2", "건물", "1154-1996-108929", "경기도 포천시 가산면 정교리 36", Decimal("198"), "블록조 스레이트지붕 단층제2종 근린생활시설"),
            GongbuRow("3", "건물", "1154-1996-108929", "경기도 포천시 가산면 정교리 36", Decimal("99"), "부속건물 조적조 스레이트지붕 단층사무실 및 휴게실"),
        ),
    )


class TestExcludedParcel:
    """평가외 필지도 본번·부번이 다르면 물건 1개(사용자 확정 2026-09-17, 2881 1.png)."""

    def test_평가외_필지도_별도_물건(self):
        _, objects = kookmin.build_kb(ctx_2823())
        assert len(objects) == 2                                   # 36(공장) + 37-1(답, 평가외)
        assert [o["물건:본번지"] for o in objects] == ["36", "37"]
        assert [o["물건:부번지"] for o in objects] == [None, "1"]

    def test_평가된_물건은_토지_건물_세부_그대로(self):
        _, objects = kookmin.build_kb(ctx_2823())
        assert [d["_kind"] for d in objects[0]["_details"]] == ["토지", "건물", "건물", "건물"]

    def test_평가외_물건은_지목_콤보에_단가1_금액0_한_행(self):
        _, objects = kookmin.build_kb(ctx_2823())
        road_obj = objects[1]
        assert road_obj["물건:물건종류"] == "답"                     # 규칙 A: 토지만인 물건은 지목 콤보
        assert len(road_obj["_details"]) == 1
        road = road_obj["_details"][0]
        assert road["세부:공부지목"] == "답"
        assert road["세부:평가단가"] == "1" and road["세부:감정평가액"] == "0"
        assert road["세부:등기번호"] is None                        # 공부스캔에 37-1 없음 → 비움(담당자 수기 1154-1996-108796)

    def test_평가된_필지끼리는_종전대로_물건_분리(self):
        ctx = ctx_2823()
        ctx = DocumentContext(**{**ctx.__dict__, "details": (
            _land("1", "36", "공장용지", "1645", "732000", "1204140000"),
            _land("2", "37-1", "답", "21", "100000", "2100000"))})
        _, objects = kookmin.build_kb(ctx)
        assert [o["물건:본번지"] for o in objects] == ["36", "37"]


class TestSharedRegistryArea:
    def test_등기번호를_여러_동이_공유하면_명세표_공부면적(self):
        _, objects = kookmin.build_kb(ctx_2823())
        blds = [d for d in objects[0]["_details"] if d["_kind"] == "건물"]
        assert [d["세부:공부면적(전용면적)"] for d in blds] == ["198.00", "198.00", "99.00"]
        assert [d["세부:사정면적"] for d in blds] == ["198.00", "198.00", "99.00"]
        assert {d["세부:등기번호"] for d in blds} == {"11541996108929"}

    def test_동마다_등기번호가_다르면_공부스캔_층합계_유지(self):
        # 2418 관례(306 1동 2275+39.55=2314.55) 보존 — 그 동만의 등기번호일 때
        ctx = ctx_2823()
        ctx = DocumentContext(**{**ctx.__dict__,
            "details": (_land("1", "36", "공장용지", "1645", "732000", "1204140000"), *_bld("가", "블럭조", "198", "245000", "48510000")),
            "gongbu": (GongbuRow("1", "건물", "1154-1996-108929", "경기도 포천시 가산면 정교리 36 1동", Decimal("198"), "블럭조"),
                       GongbuRow("2", "건물", "1154-1996-108929", "경기도 포천시 가산면 정교리 36 1동", Decimal("39.55"), "블럭조"))})
        _, objects = kookmin.build_kb(ctx)
        bld = [d for d in objects[0]["_details"] if d["_kind"] == "건물"][0]
        assert bld["세부:공부면적(전용면적)"] == "237.55"
