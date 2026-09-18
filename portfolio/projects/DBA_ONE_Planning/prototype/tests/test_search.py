# -*- coding: utf-8 -*-
"""schema_search 격리 테스트 — 한글 하이브리드 검색·FTS 주입 안전성 (v0.17 §1)."""
import tempfile
import unittest
from pathlib import Path

from tests._bootstrap import *  # noqa: F401,F403 — DBAONE_DATA_DIR 격리
from schema_search import SchemaSearch, fts_query, tokenize

TARGET = "TEST/db"

ENTRIES = [
    {"obj": "dbo.APW_Master", "kind": "U",
     "words": "dbo.APW_Master APW_Master 마스터 접수 원장 ReceiptNo CustomerName"},
    {"obj": "dbo.APW_RegHist", "kind": "U", "syns": ["등록이력"],
     "words": "dbo.APW_RegHist APW_RegHist 등록이력 등록 이력 MDATE RegNo"},
    {"obj": "dbo.APW_Process", "kind": "U",
     "words": "dbo.APW_Process APW_Process 처리 프로세스 ProcessDate Indate ISSUEDATE"},
    {"obj": "dbo.SP_IW_S_SHINHANRESEND", "kind": "P",
     "words": "dbo.SP_IW_S_SHINHANRESEND SP_IW_S_SHINHANRESEND 신한 재전송 조회"},
    {"obj": "dbo.logdatas", "kind": "U",
     "words": "dbo.logdatas logdatas 로그 접속기록 logint logoutt userid"},
]


class SearchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.s = SchemaSearch(Path(cls.tmp.name) / "search.db")
        cls.s.rebuild(TARGET, ENTRIES, "2026-07-21 00:00:00", "sig1")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _objs(self, question, n=5):
        return [r["obj"] for r in self.s.search(TARGET, question, n)["results"]]

    # ── 토큰화·질의 생성 안전성
    def test_tokenize_drops_operators_and_stopwords(self):
        self.assertNotIn("near", tokenize("NEAR 테이블 건수 알려줘"))
        self.assertNotIn("건수", tokenize("접수 건수"))
        self.assertIn("접수", tokenize("접수 건수"))

    def test_fts_query_quotes_tokens(self):
        q = fts_query(['ab"c', "def"])
        self.assertEqual(q, '"ab""c" OR "def"')

    def test_injection_strings_do_not_crash(self):
        for evil in ['" OR 1=1 --', "NEAR(a b)", "words:secret", "col: NOT x",
                     "((((", '"""""', "-접수 *마스터", "a" * 500]:
            res = self.s.search(TARGET, evil)  # 예외 없이 결과 구조 반환
            self.assertIn("results", res)

    # ── 한글 검색 품질
    def test_two_char_korean_term(self):
        # 순수 trigram이면 실패하는 케이스 — 2글자 '접수'로 매치돼야 한다
        self.assertIn("dbo.APW_Master", self._objs("접수 현황 알려줘"))

    def test_glossary_synonym_hit(self):
        res = self.s.search(TARGET, "등록이력 건수 몇 건이야?")
        self.assertEqual(res["results"][0]["obj"], "dbo.APW_RegHist")
        self.assertFalse(res["low_confidence"])  # 동의어 일치는 강한 근거

    def test_weak_text_match_is_low_confidence(self):
        # 이름·동의어 일치 없이 설명 텍스트에만 나오는 용어 — 특정 실패로 봐야 한다
        res = self.s.search(TARGET, "접수 현황 알려줘")
        self.assertTrue(res["low_confidence"])

    def test_spacing_variants(self):
        a = self._objs("등록이력 조회")
        b = self._objs("등록 이력 조회")
        self.assertIn("dbo.APW_RegHist", a)
        self.assertIn("dbo.APW_RegHist", b)

    def test_english_object_name(self):
        self.assertEqual(self._objs("APW_Process 오늘 처리 건수")[0], "dbo.APW_Process")

    def test_particle_attached_to_english_name(self):
        # 'logdatas에서'처럼 조사가 붙어도 영문명이 정확 일치로 잡혀야 한다
        res = self.s.search(TARGET, "logdatas에서 오늘 로그인 기록 보여줘")
        self.assertEqual(res["results"][0]["obj"], "dbo.logdatas")
        self.assertFalse(res["low_confidence"])
        res2 = self.s.search(TARGET, "APW_Master와 APW_Process 각각 몇 건이야?")
        objs = [r["obj"] for r in res2["results"][:2]]
        self.assertIn("dbo.APW_Master", objs)
        self.assertIn("dbo.APW_Process", objs)

    def test_substring_object_name(self):
        # SHINHANRESEND의 부분 문자열 (trigram 또는 이름 부분 일치로)
        self.assertIn("dbo.SP_IW_S_SHINHANRESEND", self._objs("shinhan 재전송 프로시저"))

    def test_nonexistent_term_low_confidence(self):
        res = self.s.search(TARGET, "고객주문 매출 합계")
        self.assertTrue(res["low_confidence"])

    def test_rebuild_replaces_target(self):
        s2 = SchemaSearch(Path(self.tmp.name) / "search2.db")
        s2.rebuild(TARGET, ENTRIES[:2], "t1", "s1")
        s2.rebuild(TARGET, ENTRIES[2:], "t2", "s2")
        objs = [r["obj"] for r in s2.search(TARGET, "APW_Process 처리")["results"]]
        self.assertIn("dbo.APW_Process", objs)
        self.assertNotIn("dbo.APW_Master", objs)
        info = s2.build_info(TARGET)
        self.assertEqual(info["n_items"], 3)
        self.assertEqual(info["schema_sig"], "s2")

    def test_target_isolation(self):
        # 다른 target의 색인이 검색에 섞이지 않는다 (권한 경계·서버 전환)
        self.s.rebuild("OTHER/db", [{"obj": "dbo.Secret", "kind": "U",
                                     "words": "dbo.Secret Secret 접수"}], "t", "s")
        self.assertNotIn("dbo.Secret", self._objs("접수 현황"))


if __name__ == "__main__":
    unittest.main()
