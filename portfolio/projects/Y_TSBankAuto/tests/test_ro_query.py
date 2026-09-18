# -*- coding: utf-8 -*-
"""고정 쿼리 레지스트리/실행기 테스트 (fake cursor). 지시 §8."""
import unittest

import ro_query as Q
from tests import _fakes


class TestLikeEscape(unittest.TestCase):
    def test_escape_specials(self):
        self.assertEqual(Q.escape_like("a%b_c[d\\e"), "a\\%b\\_c\\[d\\\\e")

    def test_prefix_contains(self):
        self.assertEqual(Q.like_prefix("50%"), "50\\%%")
        self.assertEqual(Q.like_contains("a_b"), "%a\\_b%")

    def test_sql_escape_char_matches_python(self):
        # SQL 의 ESCAPE 문자와 Python escape 문자가 일치
        sql = Q.get_registered("LOOKUP_REGHIST").sql
        self.assertIn(f"ESCAPE '{Q.LIKE_ESCAPE_CHAR}'", sql)
        self.assertIn(f"ESCAPE '{Q.LIKE_ESCAPE_CHAR}'", Q.get_registered("LOOKUP_CUSTOMER").sql)


class TestRegistry(unittest.TestCase):
    def test_registry_self_validates(self):
        Q.validate_registry()  # 위반이면 예외

    def test_only_registered_ops(self):
        self.assertEqual(
            Q.ALLOWED_OP_IDS,
            {"VERIFY_TARGET", "VERIFY_ROLES", "VERIFY_PERMISSIONS",
             "READ_SP_METADATA", "LOOKUP_REGHIST", "LOOKUP_CUSTOMER",
             "LOOKUP_CUSTOMER_EXACT", "LOOKUP_MANAGER"})

    def test_unregistered_default_deny(self):
        with self.assertRaises(Q.UnregisteredOperation):
            Q.get_registered("DROP_EVERYTHING")

    def test_param_count_matches_placeholders(self):
        for op in Q.ALLOWED_OP_IDS:
            q = Q.get_registered(op)
            self.assertEqual(q.sql.count("?"), q.param_count, op)

    def test_no_semicolon_no_multistatement(self):
        for op in Q.ALLOWED_OP_IDS:
            self.assertNotIn(";", Q.get_registered(op).sql, op)

    def test_deterministic_top_and_order(self):
        for op in ("LOOKUP_REGHIST", "LOOKUP_CUSTOMER"):
            sql = Q.get_registered(op).sql
            self.assertIn("TOP", sql, op)
            self.assertIn("ORDER BY", sql, op)


class TestSafetyGuard(unittest.TestCase):
    def test_rejects_write_keywords(self):
        for bad in ("INSERT INTO t VALUES(1)", "UPDATE t SET a=1",
                    "DELETE FROM t", "SELECT * INTO x FROM y",
                    "EXEC sp_who", "MERGE t USING s",
                    "SELECT 1; DROP TABLE t"):
            with self.assertRaises(Q.QueryContract, msg=bad):
                Q.assert_safe_sql(bad)

    def test_rejects_openrowset_linked(self):
        with self.assertRaises(Q.QueryContract):
            Q.assert_safe_sql("SELECT * FROM OPENROWSET('x','y','z')")

    def test_permission_literal_not_flagged(self):
        # 문자열 리터럴 안의 권한명(INSERT 등)은 statement 키워드가 아니므로 통과
        Q.assert_safe_sql(Q.get_registered("VERIFY_PERMISSIONS").sql)

    def test_set_statements_only(self):
        for stmt in Q.SESSION_SETUP_STATEMENTS:
            Q.assert_safe_sql(stmt, kind="set")
        with self.assertRaises(Q.QueryContract):
            Q.assert_safe_sql("SET ROLE admin", kind="set")

    def test_set_and_query_not_combined(self):
        # 세션 설정문은 조회문과 분리돼 있어야 한다
        for op in Q.ALLOWED_OP_IDS:
            self.assertNotIn("ISOLATION LEVEL", Q.get_registered(op).sql, op)
            self.assertNotIn("LOCK_TIMEOUT", Q.get_registered(op).sql, op)


class TestExecutor(unittest.TestCase):
    def test_executes_registered_and_bounds(self):
        rows = [(f"r{i}",) * 7 for i in range(10)]
        conn = _fakes.make_ro_conn({"LOOKUP_REGHIST": rows})
        cur = conn.cursor()
        out = Q.execute_registered(cur, "LOOKUP_REGHIST", ["a%", "b%"])
        self.assertEqual(len(out), Q.REGHIST_TOP)   # fetchmany 상한

    def test_param_count_mismatch(self):
        conn = _fakes.make_ro_conn()
        cur = conn.cursor()
        with self.assertRaises(Q.QueryContract):
            Q.execute_registered(cur, "LOOKUP_REGHIST", ["only-one"])

    def test_unregistered_rejected(self):
        conn = _fakes.make_ro_conn()
        cur = conn.cursor()
        with self.assertRaises(Q.UnregisteredOperation):
            Q.execute_registered(cur, "NOPE", [])

    def test_fake_cursor_rejects_raw_sql(self):
        # fake cursor 도 미등록 SQL 을 직접 받으면 실패
        conn = _fakes.make_ro_conn()
        cur = conn.cursor()
        with self.assertRaises(AssertionError):
            cur.execute("SELECT 1", [])

    def test_apply_session_uses_only_set(self):
        conn = _fakes.make_ro_conn()
        cur = conn.cursor()
        Q.apply_readonly_session(cur)
        self.assertEqual([e[0] for e in cur.executed], list(Q.SESSION_SETUP_STATEMENTS))


if __name__ == "__main__":
    unittest.main()
