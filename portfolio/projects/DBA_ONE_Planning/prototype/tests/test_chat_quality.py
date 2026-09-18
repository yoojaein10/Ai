# -*- coding: utf-8 -*-
"""실사용 챗봇 품질 회귀 — 값 조회·업무 의미·후보 범위·로컬 결과 표시."""
import json
import unittest
from unittest.mock import patch

from tests._bootstrap import app
from eval.run_eval import judge


class GeneratedScopeTest(unittest.TestCase):
    def test_allows_selected_table_and_brackets(self):
        allowed = ["dbo.APW_RegHist"]
        self.assertIsNone(app.validate_generated_table_scope(
            "SELECT TOP 1 [REG] FROM [dbo].[APW_RegHist]", allowed))

    def test_allows_cte_based_on_selected_table(self):
        sql = ("WITH x AS (SELECT REG FROM dbo.APW_RegHist) "
               "SELECT REG FROM x")
        self.assertIsNone(app.validate_generated_table_scope(sql, ["dbo.APW_RegHist"]))

    def test_blocks_hallucinated_or_unscoped_table(self):
        reason = app.validate_generated_table_scope(
            "SELECT code FROM dbo.LegalDistrict", ["dbo.APW_RegHist"])
        self.assertIn("후보 범위 밖", reason)
        self.assertIsNotNone(app.validate_generated_table_scope("SELECT GETDATE()", []))

    def test_single_value_without_where_requires_clarification(self):
        self.assertTrue(app.missing_value_filter(
            "APW_RegHist 우편번호가 뭐야?",
            "SELECT TOP 100 Zip FROM dbo.APW_RegHist"))
        self.assertFalse(app.missing_value_filter(
            "단주리 법정동 코드가 뭐야?",
            "SELECT REG2 FROM dbo.APW_RegHist WHERE NAME=N'단주리'"))
        self.assertFalse(app.missing_value_filter(
            "REG 값 목록 보여줘", "SELECT TOP 100 REG FROM dbo.APW_RegHist"))


class DomainMeaningTest(unittest.TestCase):
    CANDS = [{"obj": "dbo.APW_RegHist", "kind": "U", "score": 4.0,
              "why": ["이름 정확 일치(apw_reghist)"]}]

    def test_detects_table_meaning_but_does_not_save(self):
        before = app.load_knowledge()["glossary"]
        s = app.glossary_suggestion(
            "APW_RegHist가 법정동코드랑 주소 테이블인데 단주리 코드는 뭐야?",
            self.CANDS)
        self.assertEqual(s["mapping"].split()[0], "dbo.APW_RegHist")
        self.assertIn("법정동코드", s["term"])
        self.assertEqual(app.load_knowledge()["glossary"], before)

    def test_rejects_unknown_object_statement(self):
        self.assertIsNone(app.glossary_suggestion(
            "SecretTable이 고객정보 테이블인데 찾아줘", self.CANDS))


class LocalResultAndPrivacyTest(unittest.TestCase):
    def test_single_value_has_local_summary(self):
        self.assertEqual(app.local_result_summary(["법정동코드"], [['REDACTED_CONFIGURE_LOCALLY7890']]),
                         {"label": "법정동코드", "value": 'REDACTED_CONFIGURE_LOCALLY7890'})
        self.assertIsNone(app.local_result_summary(["코드", "주소"], [[1, "x"]]))

    def test_question_masking(self):
        masked = app.mask_question('메일 contact@example.com 전화 010-0000-0000 고객번호 REDACTED_CONFIGURE_LOCALLY78')
        for leak in ('contact@example.com', '010-0000-0000', 'REDACTED_CONFIGURE_LOCALLY78'):
            self.assertNotIn(leak, masked)

    def test_audit_never_writes_raw_question(self):
        path = app.DATA_DIR / "audit.log"
        path.unlink(missing_ok=True)
        app.audit("test.chat", {"question": '고객번호 REDACTED_CONFIGURE_LOCALLY78 조회'})
        rec = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
        self.assertNotIn("question", rec)
        self.assertIn("q_hmac", rec)


class EvaluationPolicyTest(unittest.TestCase):
    def test_ambiguous_value_accepts_clarify_or_scoped_sql(self):
        q = {"expect": {"clarify_or_sql": True,
                        "acceptable_tables": ["dbo.APW_DH_HF_LINK"]}}
        self.assertTrue(judge(q, {"answer": "어느 주소 컬럼인가요?"})["clarify_ok"])
        self.assertTrue(judge(q, {"sql": "SELECT x FROM dbo.APW_DH_HF_LINK",
                                  "tables": ["dbo.APW_DH_HF_LINK"]})["clarify_ok"])
        self.assertFalse(judge(q, {"sql": "SELECT x FROM dbo.Other",
                                   "tables": ["dbo.Other"]})["clarify_ok"])


class KnowledgeTargetIsolationTest(unittest.TestCase):
    def setUp(self):
        self.k = app._normalize_knowledge({
            "glossary": [
                {"term": "접수", "mapping": "dbo.A", "target_id": "A/db"},
                {"term": "접수", "mapping": "dbo.B", "target_id": "B/db"},
                {"term": "공통", "mapping": "DBA 개념", "target_id": app.KNOW_GLOBAL},
                {"term": "구버전", "mapping": "확인 필요"},
            ],
            "history": [
                {"question": "A 질문 조건", "sql": "SELECT ?", "target_id": "A/db"},
                {"question": "B 질문 조건", "sql": "SELECT ?", "target_id": "B/db"},
                {"question": "기존 질문 조건", "sql": "SELECT ?"},
            ],
        })

    def test_old_entries_become_legacy_not_current(self):
        legacy = [g for g in self.k["glossary"] if g["term"] == "구버전"][0]
        self.assertEqual(legacy["target_id"], app.KNOW_LEGACY)
        self.assertNotIn(legacy, app.glossary_for_target(self.k, "A/db"))

    def test_current_plus_global_only_and_local_overrides(self):
        a = app.glossary_for_target(self.k, "A/db")
        self.assertEqual({g["mapping"] for g in a}, {"dbo.A", "DBA 개념"})
        self.assertNotIn("dbo.B", {g["mapping"] for g in a})

    def test_history_is_target_scoped(self):
        self.assertEqual([h["question"] for h in app.history_for_target(self.k, "B/db")],
                         ["B 질문 조건"])

    def test_similar_examples_never_cross_target(self):
        with patch.object(app, "load_knowledge", return_value=self.k), \
                patch.object(app, "TARGET_ID", "A/db"):
            got = app.similar_examples("질문 조건")
        self.assertEqual([h["target_id"] for h in got], ["A/db"])

    def test_new_history_gets_current_target(self):
        captured = {}
        with patch.object(app, "load_knowledge", return_value={"glossary": [], "history": []}), \
                patch.object(app, "save_knowledge", side_effect=lambda k: captured.update(k)), \
                patch.object(app, "TARGET_ID", "A/db"):
            app.add_history({"question": "q", "sql": "SELECT ?"})
        self.assertEqual(captured["history"][0]["target_id"], "A/db")


if __name__ == "__main__":
    unittest.main()
