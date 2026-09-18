# -*- coding: utf-8 -*-
"""v0.17 §4·§5 회귀 테스트 — 권한 지문·캐시·문맥 압축·마스킹 유지."""
import unittest

from tests._bootstrap import app


class PermFingerprintTest(unittest.TestCase):
    def test_demo_mode_constant(self):
        self.assertEqual(app.perm_fingerprint(), "demo")

    def test_sig_changes_with_permissions(self):
        objs = [{"schema_name": "dbo", "name": "T", "modified": "2026-01-01", "created": ""}]
        a = app._search_sig(objs, [], perm="p1")
        b = app._search_sig(objs, [], perm="p2")
        self.assertNotEqual(a, b)  # 권한 변경 → 색인 재구축 유도

    def test_sig_changes_with_glossary_and_objects(self):
        objs = [{"schema_name": "dbo", "name": "T", "modified": "2026-01-01", "created": ""}]
        base = app._search_sig(objs, [], perm="p")
        self.assertNotEqual(base, app._search_sig(objs, [{"term": "x", "mapping": "y"}], perm="p"))
        objs2 = objs + [{"schema_name": "dbo", "name": "U", "modified": "2026-01-02", "created": ""}]
        self.assertNotEqual(base, app._search_sig(objs2, [], perm="p"))

    def test_obj_cache_invalidation(self):
        app._OBJ_CACHE.update(target="demo", ts=1e18, objs=[{"x": 1}], perm="p")
        app.invalidate_obj_cache()
        self.assertIsNone(app._OBJ_CACHE["objs"])


class ContextCompressionTest(unittest.TestCase):
    def setUp(self):
        app.reset_chat_state()

    def tearDown(self):
        app.reset_chat_state()

    def test_model_history_capped_at_4_turns(self):
        for i in range(10):
            app._history_add("user", f"질문{i}")
            app._history_add("model", f"답{i}")
        self.assertEqual(len(app.CHAT_HISTORY), app.CHAT_HISTORY_MAX)  # 로컬 16
        sent = app._history_for_model()
        self.assertEqual(len(sent), app.CHAT_MODEL_TURNS)  # 전송 4
        self.assertEqual(sent[-1]["text"], "답9")

    def test_reset_clears_state(self):
        app._history_add("user", "q")
        app.CHAT_STATE.update(tables=["dbo.T"], rows=5)
        app.reset_chat_state()
        self.assertEqual(app.CHAT_HISTORY, [])
        self.assertEqual(app.CHAT_STATE, {"tables": [], "rows": None})

    def test_masked_sql_has_no_literals(self):
        sql = "SELECT * FROM dbo.T WHERE name = N'홍길동' AND id = 12345 -- memo 010-0000-0000"
        masked = app.mask_sql(sql)
        for leak in ("홍길동", "12345", "010", "memo"):
            self.assertNotIn(leak, masked)


class GateRegressionTest(unittest.TestCase):
    """단일 호출 경로에서도 기존 실행 게이트가 그대로 동작해야 한다."""

    def test_validate_select_still_blocks(self):
        for bad in ("DROP TABLE x", "SELECT 1; DELETE FROM t",
                    "SELECT * INTO #t FROM x", "EXEC xp_cmdshell 'dir'"):
            self.assertIsNotNone(app.validate_select(bad), bad)
        self.assertIsNone(app.validate_select("SELECT COUNT(*) FROM dbo.T"))

    def test_chat_run_blocks_in_demo_and_unsafe(self):
        res = app.chat_run({"sql": "SELECT 1"})
        self.assertFalse(res["ok"])  # 데모 모드 = 실행 불가
        res2 = app.chat_run({"sql": "DROP TABLE x"})
        self.assertFalse(res2["ok"])
        self.assertIn("차단", res2["error"])


if __name__ == "__main__":
    unittest.main()
