"""APW 조회 — 가짜 커서로 SQL 결과 처리만 검증한다(DB 접속 없음)."""
from __future__ import annotations

from bankon.sources import apw


class FakeCursor:
    """execute 로 받은 쿼리와 무관하게 미리 정한 행을 돌려주는 커서."""

    def __init__(self, row):
        self._row = row
        self.queries: list[tuple] = []

    def execute(self, sql, *params):
        self.queries.append((sql, params))

    def fetchone(self):
        return self._row


class TestJibun:
    def test_실제값을_구조화한다(self):
        # 01-2608-3-2529 = 서울 서초구 서초동 1601-10 (신한 폼 화면값과 일치)
        cursor = FakeCursor(("11650", "10800", "1", "1601", "0010"))
        jibun = apw.fetch_jibun(cursor, "01-2608-3-2529")
        assert jibun.legal_code == "1165010800"   # 국민은행: 10자리 한 칸
        assert (jibun.reg, jibun.eub) == ("11650", "10800")  # 신한: 두 칸 분리
        assert jibun.jibun_kind == "일반"
        assert jibun.bun1 == "1601"
        assert jibun.bun2 == "10"

    def test_부번이_0000이면_없음(self):
        jibun = apw.fetch_jibun(FakeCursor(("43150", "25022", "1", "0709", "0000")), "x")
        assert jibun.bun1 == "709"
        assert jibun.bun2 is None

    def test_산번지(self):
        assert apw.fetch_jibun(FakeCursor(("11650", "10800", "2", "1", "0")), "x").jibun_kind == "산"

    def test_알수없는_SAN값은_비운다(self):
        assert apw.fetch_jibun(FakeCursor(("11650", "10800", "5", "1", "0")), "x").jibun_kind is None

    def test_행이_없으면_None(self):
        assert apw.fetch_jibun(FakeCursor(None), "x") is None

    def test_법정동코드가_반쪽이면_None(self):
        assert apw.fetch_jibun(FakeCursor((None, "10800", "1", "1", "0")), "x").legal_code is None


class TestReviewer:
    def test_itype2_심사자를_읽는다(self):
        cursor = FakeCursor(("전영배",))
        assert apw.fetch_reviewer(cursor, 1035863) == "전영배"
        assert "itype = 2" in cursor.queries[0][0]

    def test_심사자가_없으면_None(self):
        # 담보 2026 기준 66% 가 이 경우다.
        assert apw.fetch_reviewer(FakeCursor(None), 1) is None
        assert apw.fetch_reviewer(FakeCursor((None,)), 1) is None


class TestAppraisers:
    def test_한명(self):
        assert apw.split_appraisers("이준욱") == ("이준욱",)

    def test_복수평가사는_콤마로_나눈다(self):
        assert apw.split_appraisers("안창덕,황인석") == ("안창덕", "황인석")

    def test_공동평가_래퍼를_벗긴다(self):
        assert apw.split_appraisers("공(노승환)") == ("노승환",)
        assert apw.split_appraisers("윤도,공(황인석)") == ("윤도", "황인석")

    def test_빈값(self):
        assert apw.split_appraisers(None) == ()
        assert apw.split_appraisers(" , ") == ()


class TestOfficeBoss:
    def test_공백을_제거한다(self):
        assert apw.fetch_office_boss(FakeCursor(("정   우   종",))) == "정우종"

    def test_기본은_본사(self):
        cursor = FakeCursor(("정우종",))
        apw.fetch_office_boss(cursor)
        assert cursor.queries[0][1] == (apw.HEAD_OFFICE_ID,)


class TestAccount:
    def test_청구서_계좌를_읽는다(self):
        cursor = FakeCursor(("◈ 신한은행 : 100-025-471640 ( 예금주 :(주)대화감정평가법인 )",))
        account = apw.fetch_account(cursor, 1)
        assert account.number == "100-025-471640"
        assert account.holder == "(주)대화감정평가법인"

    def test_계좌가_비어있으면_None(self):
        # 본사 담보 2026 의 26% — 이때는 화면을 비워둔다.
        assert apw.fetch_account(FakeCursor(("",)), 1) is None
        assert apw.fetch_account(FakeCursor(None), 1) is None
