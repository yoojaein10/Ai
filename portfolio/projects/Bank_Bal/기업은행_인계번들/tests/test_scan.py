"""공부 스캔(T_SCAN_GONGBU) 등기번호 — 실제 값으로 검증."""
from __future__ import annotations

from decimal import Decimal

from bankon.model import DocumentContext
from bankon.parse.mullist import parse as parse_mullist
from bankon.sources import scan


class FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.queries: list[tuple] = []

    def execute(self, sql, *params):
        self.queries.append((sql, params))

    def fetchall(self):
        return self._rows


# 실제 값 (01-2608-2-0099)
REAL_ROWS = [
    ("1", "건물", "1357-1996-070593", "경기도 하남시 하산곡동 240-2 제2호",
     Decimal("211.0000"), "시멘부록조스레이트지붕단 독 주택및영업소"),
    ("1", "토지", "1357-1996-071919", "경기도 하남시 하산곡동 240-2",
     Decimal("179.0000"), "대"),
]


class TestFetch:
    def test_행을_구조화한다(self):
        rows = scan.fetch_rows(FakeCursor(REAL_ROWS), "01-2608-2-0099")
        assert len(rows) == 2
        assert rows[0].is_building and not rows[0].is_land
        assert rows[1].is_land
        assert rows[1].note == "대"          # 토지의 Bigo 는 지목

    def test_등기번호는_하이픈을_뗀다(self):
        rows = scan.fetch_rows(FakeCursor(REAL_ROWS), "x")
        assert rows[0].registry_no == "13571996070593"   # 14자리
        assert len(rows[0].registry_no) == 14

    def test_행이_없으면_빈튜플(self):
        assert scan.fetch_rows(FakeCursor([]), "x") == ()


class TestPick:
    def test_기본은_건물_우선(self):
        rows = scan.fetch_rows(FakeCursor(REAL_ROWS), "x")
        assert scan.registry_for(rows) == "13571996070593"

    def test_종류로_고른다(self):
        rows = scan.fetch_rows(FakeCursor(REAL_ROWS), "x")
        assert scan.registry_for(rows, kind="토지") == "13571996071919"

    def test_없는_종류면_None(self):
        rows = scan.fetch_rows(FakeCursor(REAL_ROWS[:1]), "x")
        assert scan.registry_for(rows, kind="토지") is None

    def test_비어있으면_None(self):
        assert scan.registry_for(()) is None


MULLIST_ROW = {
    "NO": "1", "DABO_JONG_SUB": "집합상가", "MUL_GUBUN": "건물",
    "ADDR_NEW": "서울시", "P_PRICE": "1", "DUNG_NO": "1701-2018-002982",
}


class TestContext:
    def test_mullist가_있으면_그것을_쓴다(self):
        ctx = DocumentContext(
            doc_id="x", business_number="1",
            properties=parse_mullist({"mullist0": [MULLIST_ROW]}),
            gongbu=scan.fetch_rows(FakeCursor(REAL_ROWS), "x"),
        )
        assert ctx.registry_no(kind="건물") == "1701-2018-002982"

    def test_mullist가_없으면_공부스캔으로_보완한다(self):
        # 국민 건 전부, 신한의 32% 가 이 경로다.
        ctx = DocumentContext(
            doc_id="x", business_number="1",
            gongbu=scan.fetch_rows(FakeCursor(REAL_ROWS), "x"),
        )
        assert ctx.registry_no() == "13571996070593"
        assert ctx.registry_no(kind="토지") == "13571996071919"

    def test_둘_다_없으면_None(self):
        # 지사 건 — 공부 스캔은 본사 전용이라 비어 있다.
        ctx = DocumentContext(doc_id="x", business_number="1")
        assert ctx.registry_no() is None
