# -*- coding: utf-8 -*-
"""의뢰기관 제외(주택도시보증공사) 판정 및 부작용 차단 테스트.

실제 PDF/DB/Bank24 에 접근하지 않고 합성 텍스트와 fake 로만 검증한다(§23).
"""
import os
import unittest

import parsers
import pipeline
import tabletop_save
from parsers import base

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def load(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return [ln.rstrip("\n") for ln in f]


class TestAgencyExtraction(unittest.TestCase):
    def test_a_exact_match_excluded(self):
        lines = ["탁상자문의뢰서",
                 "의뢰기관: 주택도시보증공사      의뢰번호: T1  자문번호: 01-1"]
        self.assertTrue(base.requesting_agency_excluded(lines))
        self.assertEqual(base.collect_agency_values(lines), ["주택도시보증공사"])
        with self.assertRaises(parsers.ExcludedRequest) as cm:
            parsers.parse_request(lines)
        self.assertEqual(cm.exception.code, "EXCLUDED_HUG")

    def test_b_spaces_and_fullwidth_normalized(self):
        # 앞뒤·연속 공백 + 전각 공백(U+3000) + 전각 콜론(：) → NFKC 후 제외.
        lines = ["탁상자문의뢰서",
                 "의뢰기관：　  주택도시보증공사 　 의뢰번호: T1"]
        self.assertEqual(base.collect_agency_values(lines), ["주택도시보증공사"])
        self.assertTrue(base.requesting_agency_excluded(lines))

    def test_c_kookmin_not_excluded_and_parses(self):
        lines = load("kookmin_synth.txt")
        self.assertFalse(base.requesting_agency_excluded(lines))
        m = parsers.parse_request(lines)   # 제외 아님 → 기존 정상 처리
        self.assertEqual(m.bank, "국민은행")

    def test_d_mention_in_other_fields_not_excluded(self):
        # 의뢰기관 값은 우리은행. 비고/주소/본문에만 주택도시보증공사 언급 → 제외 아님.
        lines = [
            "탁상자문의뢰서",
            "의뢰기관: 우리은행      의뢰번호: T1  자문번호: 01-1",
            "참고사항   주택도시보증공사 관련 건",
            "주 소   서울특별시 중구 주택도시보증공사로 1",
        ]
        self.assertFalse(base.requesting_agency_excluded(lines))

    def test_e_similar_name_not_excluded(self):
        for value in ("주택도시보증공사서울지사", "주택도시보증", "한국주택도시보증공사"):
            lines = ["탁상자문의뢰서", f"의뢰기관: {value}   의뢰번호: T1"]
            self.assertFalse(base.requesting_agency_excluded(lines),
                             f"{value} 는 정확 일치가 아님")

    def test_f1_missing_agency_and_bank_excluded_no_bank(self):
        # 의뢰기관 라벨 없음 + 은행명 미판별 → HUG 제외는 아니고,
        # 2026-07-28 규칙으로 EXCLUDED_NO_BANK 저장 제외.
        lines = ["어떤문서", "의뢰번호: X1", "내용"]
        self.assertFalse(base.requesting_agency_excluded(lines))
        with self.assertRaises(parsers.ExcludedRequest) as cm:
            parsers.parse_request(lines)
        self.assertEqual(cm.exception.code, "EXCLUDED_NO_BANK")

    def test_f2_ambiguous_multiple_candidates_not_hug_excluded(self):
        # 서로 다른 의뢰기관 값 복수(모호) → HUG 제외 아님. 은행명 미판별이라
        # EXCLUDED_NO_BANK 로 저장 제외.
        lines = [
            "어떤문서",
            "의뢰기관: 주택도시보증공사   의뢰번호: T1",
            "의뢰기관: 한국자산관리공사   의뢰번호: T2",
        ]
        self.assertEqual(len(set(base.collect_agency_values(lines))), 2)
        self.assertFalse(base.requesting_agency_excluded(lines))
        with self.assertRaises(parsers.ExcludedRequest) as cm:
            parsers.parse_request(lines)
        self.assertEqual(cm.exception.code, "EXCLUDED_NO_BANK")

    def test_f3_empty_value_cell_not_excluded(self):
        lines = ["탁상자문의뢰서", "의뢰기관:            의뢰번호: T1"]
        self.assertEqual(base.collect_agency_values(lines), [""])
        self.assertFalse(base.requesting_agency_excluded(lines))

    def test_hug_fixture_excluded(self):
        with self.assertRaises(parsers.ExcludedRequest):
            parsers.parse_request(load("hug_synth.txt"))


class _RecordingConnector:
    """호출되면 즉시 실패시켜 '연결 시도 자체'를 감지."""
    def __init__(self):
        self.called = False

    def __call__(self, *a, **k):
        self.called = True
        raise AssertionError("제외 건에서 DB connector 가 호출되었다")


class TestExcludedNoSideEffects(unittest.TestCase):
    def test_g_no_db_connect_for_excluded(self):
        # base.extract_lines 를 합성 제외 라인으로 대체(실 PDF 미접근).
        excluded_lines = ["탁상자문의뢰서",
                          "의뢰기관: 주택도시보증공사   의뢰번호: T1"]
        old = base.extract_lines
        base.extract_lines = lambda path, **k: list(excluded_lines)
        conn = _RecordingConnector()
        lookup = _RecordingConnector()
        try:
            import config
            app = config.AppConfig()
            app.db = config.DbConfig(enabled=True, server="S", database="D",
                                     username='REDACTED_CONFIGURE_LOCALLY', password='REDACTED_CONFIGURE_LOCALLY',
                                     lookup_server="L")
            with self.assertRaises(parsers.ExcludedRequest):
                tabletop_save.save_pdf_batch(
                    ["x.pdf"], app, allowed_roots=["."],
                    connector=conn, lookup_connector=lookup)
        finally:
            base.extract_lines = old
        self.assertFalse(conn.called, "DB connector 미호출이어야 함")
        self.assertFalse(lookup.called, "lookup connector 미호출이어야 함")


class TestKookminBranchCut(unittest.TestCase):
    def test_j_branch_excludes_manager_label_same_row(self):
        # 영업점 값과 담당자명 라벨이 같은 추출 행에 병렬로 온 경우.
        lines = [
            "담보감정평가의뢰서",
            "의뢰기관: 국민은행   의뢰번호: 300000001  감정서번호: 01-1",
            "의뢰일자   2026-01-01   영 업 점   샘플종합금융센터   담당자명   홍길순",
            "전화번호   0200000000",
            "일련번호   1",
            "물건           서울특별시 마포구 합정동 200-2 샘플타워",
            "주 소",
        ]
        m = parsers.parse_request(lines)
        self.assertEqual(m.branch, "샘플종합금융센터")
        self.assertNotIn("담당자명", m.branch)
        self.assertNotIn("홍길순", m.branch)
        self.assertEqual(m.staff_name, "홍길순")

    def test_j_regression_branch_preserved_when_no_label(self):
        # 기존 fixture(담당자명이 다음 줄) → 지점명 무손실.
        m = parsers.parse_request(load("kookmin_synth.txt"))
        self.assertEqual(m.branch, "샘플종합금융센터")
        self.assertEqual(parsers.build_custname(m), "국민은행 샘플종합금융센터")


class TestNoBankNoBranchExcluded(unittest.TestCase):
    """2026-07-28 규칙 1: 은행명/지점명 미상 건은 실패가 아닌 저장 제외."""

    def test_no_bank_excluded_before_parser(self):
        lines = ["탁상자문의뢰서", "의뢰기관: 어떤기관   의뢰번호: T1"]
        with self.assertRaises(parsers.ExcludedRequest) as cm:
            parsers.parse_request(lines)
        self.assertEqual(cm.exception.code, "EXCLUDED_NO_BANK")

    def test_no_branch_excluded_after_parse(self):
        # 은행은 판별되지만 영업점 값이 끝내 비면 EXCLUDED_NO_BRANCH.
        lines = [
            "담보감정평가의뢰서",
            "의뢰기관: 국민은행   의뢰번호: 300000001  감정서번호: 01-1",
            "의뢰일자   2026-01-01",
            "일련번호   1",
            "물건           서울특별시 마포구 합정동 200-2 샘플타워",
            "주 소",
        ]
        with self.assertRaises(parsers.ExcludedRequest) as cm:
            parsers.parse_request(lines)
        self.assertEqual(cm.exception.code, "EXCLUDED_NO_BRANCH")

    def test_excluded_no_bank_skips_db(self):
        # 은행명 미상 제외 건도 DB connector 미호출(§14-15 동등).
        old = base.extract_lines
        base.extract_lines = lambda path, **k: ["어떤문서", "의뢰번호: X1"]
        conn = _RecordingConnector()
        lookup = _RecordingConnector()
        try:
            import config
            app = config.AppConfig()
            app.db = config.DbConfig(enabled=True, server="S", database="D",
                                     username='REDACTED_CONFIGURE_LOCALLY', password='REDACTED_CONFIGURE_LOCALLY',
                                     lookup_server="L")
            with self.assertRaises(parsers.ExcludedRequest):
                tabletop_save.save_pdf_batch(
                    ["x.pdf"], app, allowed_roots=["."],
                    connector=conn, lookup_connector=lookup)
        finally:
            base.extract_lines = old
        self.assertFalse(conn.called)
        self.assertFalse(lookup.called)


class TestRegressionEligible(unittest.TestCase):
    def test_k_supported_banks_still_eligible(self):
        for fn in ("woori_synth.txt", "kookmin_synth.txt", "saemaeul_synth.txt",
                   "ibk_synth.txt", "nonghyup_synth.txt", "suhyup_synth.txt"):
            self.assertFalse(base.requesting_agency_excluded(load(fn)), fn)
            pr = pipeline.prepare(load(fn))
            self.assertTrue(pr.eligible, f"{fn}: {pr.reasons}")


if __name__ == "__main__":
    unittest.main()
