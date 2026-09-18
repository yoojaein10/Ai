"""2881(국민 김포 월곶면 고양리 512-5 상가 + 512-2 전·512-6 도로 평가외) 담당자 완성본 대조(2026-09-17, 1.png).

사용자 확정: **본번·부번이 다르면 왼쪽 물건 행을 추가**하고 그 물건의 세부내역을 넣는다(규칙 A).
여러 필지를 물건 하나로 합치는 건 담당자가 직접 한다 — 자동화가 먼저 합치지 않는다.

담당자 화면(1.png): 물건 3개 = ① 일반상가-근린(점포)상가 512-5 ② 전 512-2 ③ 도로 512-6.
물건 1 의 세부내역은 토지 1 + 건물 2 = 3행(평가외 필지는 여기 안 들어간다).
"""
from __future__ import annotations

from decimal import Decimal

from bankon.mapping import kookmin
from bankon.model import DocumentContext
from bankon.parse.detail import DetailRow
from bankon.sources.apw import Jibun


def _land(no, jibun, cat, area, unit=None, amount=None, excluded=False):
    return DetailRow(table="land_list0", seq_no=no, jibun=jibun, category=cat, zone="계획관리",
                     area_public=Decimal(area), area_assessed=Decimal(area),
                     unit_price=Decimal(unit) if unit else None, amount=Decimal(amount) if amount else None,
                     excluded=excluded, unit_kind="토지")


def _bld(mark, area, unit, amount):
    head = DetailRow(table="land_list0", seq_no=mark, jibun="512-5", category="제2종",
                     zone="일반철골구조", unit_kind="건물")
    body = DetailRow(table="land_list0", category="시설", zone="단층", area_public=Decimal(area),
                     area_assessed=Decimal(area), unit_price=Decimal(unit), amount=Decimal(amount), unit_kind="건물")
    return head, body


def ctx_2881() -> DocumentContext:
    return DocumentContext(
        doc_id="01-2609-3-2881", business_number="2148746436", gam_category="토지건물",
        jibun=Jibun(reg="41570", eub="35024", san="1", bun1="512", bun2="5"),
        details=(_land("1", "512-5", "대", "1071", "702000", "751842000"),
                 *_bld("가", "163.20", "786000", "128275200"),
                 *_bld("나", "165.00", "786000", "129690000"),
                 _land("2", "512-2", "전", "66", excluded=True),
                 _land("3", "512-6", "도로", "24", excluded=True)),
    )


class TestObjectPerParcel:
    def test_필지_3개면_물건_3개(self):
        # 종전(2823 특례)에는 평가외 2필지가 물건 1 의 세부로 흡수돼 물건이 1개뿐이었다
        _, objects = kookmin.build_kb(ctx_2881())
        assert len(objects) == 3
        assert [o["물건:일련번호"] for o in objects] == ["1", "2", "3"]

    def test_본번_부번이_화면과_같다(self):
        _, objects = kookmin.build_kb(ctx_2881())
        assert [(o["물건:본번지"], o["물건:부번지"]) for o in objects] == [("512", "5"), ("512", "2"), ("512", "6")]

    def test_평가외_물건의_물건종류는_지목_콤보(self):
        _, objects = kookmin.build_kb(ctx_2881())
        assert objects[1]["물건:물건종류"] == "전"
        assert objects[2]["물건:물건종류"] == "도로"

    def test_물건1_세부는_토지1_건물2(self):
        _, objects = kookmin.build_kb(ctx_2881())
        assert [d["_kind"] for d in objects[0]["_details"]] == ["토지", "건물", "건물"]

    def test_평가외_물건은_단가1_금액0_한_행(self):
        _, objects = kookmin.build_kb(ctx_2881())
        for obj in objects[1:]:
            assert len(obj["_details"]) == 1
            assert obj["_details"][0]["세부:평가단가"] == "1"
            assert obj["_details"][0]["세부:감정평가액"] == "0"

    def test_평가된_토지행은_화면값_그대로(self):
        _, objects = kookmin.build_kb(ctx_2881())
        land = objects[0]["_details"][0]
        assert land["세부:공부면적"] == "1071.00" and land["세부:사정면적"] == "1071.00"
        assert land["세부:평가단가"] == "702000" and land["세부:감정평가액"] == "751842000"

    def test_평가방법은_물건마다_원가평가(self):
        _, objects = kookmin.build_kb(ctx_2881())
        assert {o["_method"] for o in objects} == {kookmin.METHOD_COST}
