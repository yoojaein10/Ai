# -*- coding: utf-8 -*-
"""APW_Customer_Manager 담당자 기반 저장 제외(EXCLUDED_MANAGER) 검증.

2026-07-28 규칙:
- 1927 이 재직 담당자 목록에 '포함'되면 모든 은행에서 제외.
- 1115 는 기업은행 의뢰에서만, '포함'이면 제외.
- 0명/조회 실패/빈 CustID 는 제외하지 않음(fail-open = 저장 진행).
- CustID 는 `?` 바인딩, Office 는 고정 상수 필터. 값은 로그로 남기지 않음.
"""
import unittest

import ro_query
import ro_lookups
import tabletop_save


class FakeCursor:
    """execute(sql, params) → fetchmany(n) 만 흉내내는 최소 커서."""

    def __init__(self, rows=None, raise_on_execute=False):
        self._rows = list(rows or [])
        self._raise = raise_on_execute
        self.last_sql = None
        self.last_params = None

    def execute(self, sql, params=None):
        self.last_sql = sql
        self.last_params = params
        if self._raise:
            raise RuntimeError("db down")
        return self

    def fetchmany(self, n):
        head, self._rows = self._rows[:n], self._rows[n:]
        return head


class TestLookupManagers(unittest.TestCase):
    def test_binds_custid_and_uses_fixed_office(self):
        cur = FakeCursor(rows=[("1115",)])
        ro_lookups.lookup_managers(cur, "C123")
        self.assertIn("CustID = ?", cur.last_sql)
        self.assertIn("Office = '10'", cur.last_sql)
        self.assertEqual(cur.last_params, ["C123"])

    def test_single_manager(self):
        self.assertEqual(ro_lookups.lookup_managers(FakeCursor([("1115",)]), "C"), ["1115"])

    def test_int_column_normalized_to_str(self):
        self.assertEqual(ro_lookups.lookup_managers(FakeCursor([(1115,)]), "C"), ["1115"])

    def test_distinct_dedup(self):
        # 같은 담당자가 여러 행 → distinct 1개
        self.assertEqual(
            ro_lookups.lookup_managers(FakeCursor([("1115",), ("1115",)]), "C"), ["1115"])

    def test_multiple_distinct(self):
        self.assertEqual(
            ro_lookups.lookup_managers(FakeCursor([("1115",), ("2222",)]), "C"),
            ["1115", "2222"])

    def test_empty_and_none_filtered(self):
        self.assertEqual(
            ro_lookups.lookup_managers(FakeCursor([(None,), ("",), ("  ",), ("1927",)]), "C"),
            ["1927"])

    def test_no_rows(self):
        self.assertEqual(ro_lookups.lookup_managers(FakeCursor([]), "C"), [])

    def test_empty_custid(self):
        self.assertEqual(ro_lookups.lookup_managers(FakeCursor([("1115",)]), ""), [])
        self.assertEqual(ro_lookups.lookup_managers(FakeCursor([("1115",)]), None), [])

    def test_query_failure_fail_open(self):
        self.assertEqual(
            ro_lookups.lookup_managers(FakeCursor(raise_on_execute=True), "C"), [])


class TestExclusionDecision(unittest.TestCase):
    """tabletop_save.manager_exclusion_applies 의 은행별 '포함' 판정."""

    def _excluded(self, bank, rows):
        mgrs = ro_lookups.lookup_managers(FakeCursor(rows), "C")
        return tabletop_save.manager_exclusion_applies(bank, mgrs)

    # --- 1927: 모든 은행 ---
    def test_1927_alone_excluded_any_bank(self):
        self.assertTrue(self._excluded("우리은행", [("1927",)]))
        self.assertTrue(self._excluded("기업은행", [("1927",)]))

    def test_1927_among_many_excluded(self):
        self.assertTrue(self._excluded("국민은행", [("1927",), ("2222",)]))

    def test_1927_int_column(self):
        self.assertTrue(self._excluded("하나은행", [(1927,)]))

    # --- 1115: 기업은행만 ---
    def test_1115_alone_ibk_excluded(self):
        self.assertTrue(self._excluded("기업은행", [("1115",)]))

    def test_1115_among_many_ibk_excluded(self):
        self.assertTrue(self._excluded("기업은행", [("1115",), ("2222",)]))

    def test_1115_alone_other_bank_not_excluded(self):
        self.assertFalse(self._excluded("우리은행", [("1115",)]))
        self.assertFalse(self._excluded("새마을금고", [("1115",)]))

    def test_1115_and_1927_other_bank_excluded_by_1927(self):
        self.assertTrue(self._excluded("우리은행", [("1115",), ("1927",)]))

    # --- fail-open ---
    def test_not_excluded_other_manager(self):
        self.assertFalse(self._excluded("기업은행", [("9999",)]))

    def test_not_excluded_no_rows(self):
        self.assertFalse(self._excluded("기업은행", []))

    def test_empty_bank_uses_all_banks_rule_only(self):
        self.assertTrue(self._excluded("", [("1927",)]))
        self.assertFalse(self._excluded("", [("1115",)]))

    def test_excluded_managers_constants(self):
        self.assertEqual(sorted(tabletop_save.EXCLUDED_MANAGERS_ALL_BANKS), ["1927"])
        self.assertEqual(
            {b: sorted(v) for b, v in tabletop_save.EXCLUDED_MANAGERS_BY_BANK.items()},
            {"기업은행": ["1115"]})


class TestRegistry(unittest.TestCase):
    def test_manager_query_registered_and_safe(self):
        ro_query.validate_registry()
        q = ro_query.get_registered("LOOKUP_MANAGER")
        self.assertEqual(q.param_count, 1)
        self.assertEqual(q.sql.count("?"), 1)
        ro_query.assert_safe_sql(q.sql, kind="select")
        self.assertIn("APW_Customer_Manager", q.sql)

    def test_manager_query_excludes_retired(self):
        """퇴사자 제외: 사용자 마스터 LEFT JOIN + RTRM_FL 필터 + USR_SEQ 조인키."""
        q = ro_query.get_registered("LOOKUP_MANAGER")
        self.assertIn("TMWCMN_USR_BAC_INFO", q.sql)
        self.assertIn("USR_SEQ", q.sql)
        self.assertIn("RTRM_FL", q.sql)
        # 미매칭 Manager 코드 보존을 위해 LEFT JOIN + IS NULL 허용이어야 한다.
        self.assertIn("LEFT JOIN", q.sql.upper())
        self.assertIn("IS NULL", q.sql.upper())
        # CustID 바인딩은 여전히 정확히 하나여야 한다(조인 추가로 늘어나면 안 됨).
        self.assertEqual(q.sql.count("?"), 1)


if __name__ == "__main__":
    unittest.main()
