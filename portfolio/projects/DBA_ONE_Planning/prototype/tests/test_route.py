# -*- coding: utf-8 -*-
"""로컬 라우팅 규칙 테스트 (v0.17 §2) — LLM 없이 순수 함수로 검증."""
import unittest

from tests._bootstrap import app


def cand(obj, kind="U", score=4.0, why=("이름 정확 일치(x)",)):
    return {"obj": obj, "kind": kind, "score": score, "why": list(why)}


class RouteTest(unittest.TestCase):
    def r(self, q, cands=(), hist=False):
        return app.local_route(q, list(cands), hist)

    def test_count_questions_go_to_data(self):
        # v0.16 기준선에서 metadata로 새던 유형 — 항상 data여야 한다
        for q in ("APW_Master 테이블 전체 건수 알려줘", "APW_Judgment 테이블 행 수 알려줘",
                  "APW_Inventory 총 건수는?", "BANK_KB_PROCESS에 데이터가 몇 건 있는지 세어줘"):
            self.assertEqual(self.r(q, [cand("dbo.X")])[0], "data", q)

    def test_metadata_questions(self):
        for q in ("어제 새로 만들어지거나 수정된 프로시저 있어?",
                  "제일 큰 테이블 상위 5개가 뭐야?",
                  "APW_Process 테이블은 언제 마지막으로 수정됐어?"):
            self.assertEqual(self.r(q)[0], "metadata", q)

    def test_metadata_change_with_object(self):
        route, obj = self.r("SP_IW_S_SIJOLIST 프로시저 최근에 뭐가 바뀌었어?",
                            [cand("dbo.SP_IW_S_SIJOLIST", "P")])
        self.assertEqual(route, "metadata")
        self.assertEqual(obj, "dbo.SP_IW_S_SIJOLIST")

    def test_proc_diagnosis(self):
        for q in ("SP_S_KW_SHINHAN_DAYCOUNT가 요즘 느린 것 같은데 원인 좀 봐줘",
                  "SP_IW_MonTong 프로시저 분석해줘",
                  "SP_S_USER_INFO_SYNC 코드에 성능 문제 있는지 리뷰해줘"):
            route, obj = self.r(q, [cand("dbo.SP_X", "P")])
            self.assertEqual(route, "proc", q)
            self.assertEqual(obj, "dbo.SP_X")

    def test_proc_intent_without_object_is_not_proc(self):
        self.assertNotEqual(self.r("요즘 뭐가 느린지 분석해줘")[0], "proc")

    def test_general_questions(self):
        for q in ("지금 서버 상태 어때? 블로킹 있어?", "Query Store가 뭐고 왜 켜야 해?",
                  "요즘 제일 문제 되는 거 뭐야?"):
            self.assertEqual(self.r(q)[0], "general", q)

    def test_ambiguous_data_still_data(self):
        # 재질문 트리거는 검색 확신도가 담당 — 라우팅은 data로
        self.assertEqual(self.r("어제 몇 건 들어왔어?")[0], "data")
        self.assertEqual(self.r("접수 건수 알려줘")[0], "data")

    def test_followup_defaults_to_data(self):
        self.assertEqual(self.r("그럼 어제는?", hist=True)[0], "data")

    def test_no_signal_no_history_goes_general(self):
        self.assertEqual(self.r("안녕")[0], "general")

    def test_value_lookup_with_named_table_goes_to_data(self):
        # v0.17 회귀: '~가 뭐야'가 general로 새서 상담 경로에 갇히던 유형
        route, _ = self.r(
            "APW_RegHist가 법정동코드랑 주소 테이블인데 단주리 법정동 코드가 뭐야?",
            [cand("dbo.APW_RegHist")])
        self.assertEqual(route, "data")

    def test_value_lookup_followup_goes_to_data(self):
        self.assertEqual(self.r("그럼 그거 코드가 뭐야?", hist=True)[0], "data")

    def test_value_words_go_to_data_without_fresh_context(self):
        # 대상을 아직 못 찾았더라도 status 상담으로 보내지 말고 data 재질문 경로로 보낸다
        for q in ("단주리 법정동 코드가 뭐야?", "이 주소 값 찾아줘", "고객번호 알려줘"):
            self.assertEqual(self.r(q)[0], "data", q)

    def test_glossary_synonym_is_named_entity(self):
        route, _ = self.r(
            "등록이력에서 단주리 법정동 코드가 뭐야?",
            [cand("dbo.APW_RegHist", why=("동의어 일치(등록이력)",))])
        self.assertEqual(route, "data")

    def test_status_words_win_over_named_object(self):
        self.assertEqual(
            self.r("지금 블로킹 있어? 상태 어때?", [cand("dbo.APW_RegHist")])[0],
            "general")
        self.assertEqual(
            self.r("APW_RegHist 코드 조회 때문에 블로킹 있어?", [cand("dbo.APW_RegHist")])[0],
            "general")


if __name__ == "__main__":
    unittest.main()
