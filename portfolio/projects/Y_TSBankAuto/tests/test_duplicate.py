# -*- coding: utf-8 -*-
"""중복 후보 조회 테스트. 지시 §8 중복."""
import unittest

import ro_duplicate as DUP


class TestDuplicate(unittest.TestCase):
    def test_no_key_undecidable_no_query(self):
        # cur 를 넘겨도 confirmed_key 없으면 쿼리하지 않는다(판정 불가)
        called = {"n": 0}

        class Cur:
            def execute(self, *a, **k):
                called["n"] += 1
        res = DUP.check_duplicate(Cur(), confirmed_key=None)
        self.assertEqual(res.status, DUP.UNDECIDABLE)
        self.assertEqual(called["n"], 0)

    def test_confirmed_key_still_no_registered_query(self):
        res = DUP.check_duplicate(None, confirmed_key={"CustID": "C1"})
        self.assertEqual(res.status, DUP.UNDECIDABLE)

    def test_classify_none(self):
        self.assertEqual(DUP.classify_rows([]), DUP.NO_DUPLICATE)

    def test_classify_candidate(self):
        self.assertEqual(DUP.classify_rows([("row",)]), DUP.CANDIDATE)

    def test_three_states_distinct(self):
        self.assertEqual(len({DUP.NO_DUPLICATE, DUP.CANDIDATE, DUP.UNDECIDABLE}), 3)

    def test_repr_safe(self):
        self.assertNotIn("row", repr(DUP.DuplicateResult(DUP.CANDIDATE, 1)))


if __name__ == "__main__":
    unittest.main()
