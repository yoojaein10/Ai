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


class TestIdentify:
    """물건 고유값으로 등기번호 고르기 — 순번(No)은 물건과 어긋난다."""

    # 실측 01-2608-3-2625: 408호·409호가 **둘 다 No=3**. 화면 물건①(90.48㎡)은 …047.
    UNITS = [
        ("3", "건물", "1357-2016-011048",
         "경기도 하남시 망월동 968-1외 1필지 미사센트럴프라자 제4층 제409호",
         Decimal("96.7200"), "전유부분 철근콘크리트구조"),
        ("3", "건물", "1357-2016-011047",
         "경기도 하남시 망월동 968-1외 1필지 미사센트럴프라자 제4층 제408호",
         Decimal("90.4800"), "전유부분 철근콘크리트구조"),
    ]
    # 실측 01-2607-3-2399: 세 필지가 **전부 No=1**. 화면 물건①(2,612㎡)은 …449.
    PARCELS = [
        ("1", "토지", "1951-1996-264450", "경상남도 창녕군 창녕읍 교리 815-3",
         Decimal("2466.0000"), "답"),
        ("1", "토지", "1951-1996-264449", "경상남도 창녕군 창녕읍 교리 815-1",
         Decimal("2612.0000"), "답"),
    ]

    def test_면적이_사실상_유일키(self):
        rows = scan.fetch_rows(FakeCursor(self.UNITS), "x")
        assert scan.registry_for(rows, area=Decimal("90.48")) == "13572016011047"
        assert scan.registry_for(rows, area=Decimal("96.72")) == "13572016011048"

    def test_소수자리_표기가_달라도_같은_수면_맞춘다(self):
        rows = scan.fetch_rows(FakeCursor(self.UNITS), "x")
        assert scan.registry_for(rows, area=Decimal("90.4800")) == "13572016011047"

    def test_면적이_없으면_호로_고른다(self):
        rows = scan.fetch_rows(FakeCursor(self.UNITS), "x")
        assert scan.registry_for(rows, location="제4층 제408호") == "13572016011047"

    def test_필지는_지번으로도_고른다(self):
        rows = scan.fetch_rows(FakeCursor(self.PARCELS), "x")
        assert scan.registry_for(rows, jibun="815-1") == "19511996264449"
        assert scan.registry_for(rows, area=Decimal("2612")) == "19511996264449"

    def test_순번이_겹쳐도_고유값이_이긴다(self):
        # 예전 규칙(순번 → 첫 행)이면 …048 을 골라 틀렸다.
        rows = scan.fetch_rows(FakeCursor(self.UNITS), "x")
        assert scan.registry_for(rows, seq_no="3") == "13572016011048"          # 예전 동작
        assert scan.registry_for(rows, seq_no="3", area=Decimal("90.48")) \
            == "13572016011047"                                                  # 고유값 우선

    def test_못_좁히면_예전_동작(self):
        rows = scan.fetch_rows(FakeCursor(REAL_ROWS), "x")
        assert scan.registry_for(rows, area=Decimal("9999")) == "13571996070593"

    def test_고유값을_안_주면_무회귀(self):
        rows = scan.fetch_rows(FakeCursor(REAL_ROWS), "x")
        assert scan.registry_for(rows, kind="토지") == "13571996071919"


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
