# -*- coding: utf-8 -*-
"""탁상 조회 기간 계산: 월요일=금~월, 그 외=전날~당일."""
import unittest
from datetime import date

import bank24_backend as B


class TestComputeQueryRange(unittest.TestCase):
    def test_monday_goes_back_to_friday(self):
        # 2026-07-13 is Monday
        d = date(2026, 7, 13)
        self.assertEqual(d.weekday(), 0)
        start, end = B.compute_query_range(d)
        self.assertEqual(start, "2026-07-10")  # 지난 금요일
        self.assertEqual(end, "2026-07-13")

    def test_tuesday_uses_yesterday(self):
        d = date(2026, 7, 14)  # Tuesday
        self.assertEqual(d.weekday(), 1)
        start, end = B.compute_query_range(d)
        self.assertEqual(start, "2026-07-13")
        self.assertEqual(end, "2026-07-14")

    def test_friday_uses_thursday(self):
        d = date(2026, 7, 17)  # Friday
        self.assertEqual(d.weekday(), 4)
        start, end = B.compute_query_range(d)
        self.assertEqual(start, "2026-07-16")
        self.assertEqual(end, "2026-07-17")

    def test_end_is_always_today(self):
        for offset in range(7):
            d = date(2026, 7, 13 + offset)
            _, end = B.compute_query_range(d)
            self.assertEqual(end, d.strftime("%Y-%m-%d"))

    def test_start_before_or_equal_end(self):
        for offset in range(14):
            d = date(2026, 7, 1 + offset)
            start, end = B.compute_query_range(d)
            self.assertLessEqual(start, end)


class _Rect:
    def __init__(self, top, left):
        self.top = top
        self.left = left


class _FakeEdit:
    def __init__(self, name, top, left):
        self.name = name
        self._rect = _Rect(top, left)

    def rectangle(self):
        return self._rect


class TestOrderStartEndEdits(unittest.TestCase):
    def test_vertical_top_is_start(self):
        # 세로 배치: 위(top 작은)=시작일. descendant 순서가 반대여도 위치로 바로잡는다.
        bottom = _FakeEdit("end", top=200, left=50)    # 조회종료일(아래)
        top = _FakeEdit("start", top=150, left=50)     # 조회시작일(위)
        start_edit, end_edit = B.order_start_end_edits([bottom, top])
        self.assertEqual(start_edit.name, "start")
        self.assertEqual(end_edit.name, "end")

    def test_horizontal_left_is_start(self):
        # 같은 높이면 왼쪽=시작일.
        right = _FakeEdit("end", top=100, left=300)
        left = _FakeEdit("start", top=100, left=100)
        start_edit, end_edit = B.order_start_end_edits([right, left])
        self.assertEqual(start_edit.name, "start")
        self.assertEqual(end_edit.name, "end")

    def test_rectangle_failure_keeps_order(self):
        class _Boom:
            def __init__(self, name):
                self.name = name
            def rectangle(self):
                raise RuntimeError("no coords")
        a, b = _Boom("first"), _Boom("second")
        start_edit, end_edit = B.order_start_end_edits([a, b])
        self.assertEqual(start_edit.name, "first")
        self.assertEqual(end_edit.name, "second")


if __name__ == "__main__":
    unittest.main()
