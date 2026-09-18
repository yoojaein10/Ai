# -*- coding: utf-8 -*-
"""외부 회귀 unittest 래퍼. 외부 PDF 디렉터리가 있을 때만 실행(없으면 skip)."""
import unittest

from tests import regression_external as R


class TestRegression(unittest.TestCase):
    def test_all_eligible(self):
        r = R.run()
        if not r["available"]:
            self.skipTest(f"외부 PDF 없음: {R.DEFAULT_DIR}")
        # 37건 전부 적격, 파싱 실패 0
        self.assertEqual(r["parse_fail"], 0)
        self.assertEqual(r["eligible"], r["total"])
        self.assertEqual(r["total"], 37)

    def test_required_fields_full_presence(self):
        r = R.run()
        if not r["available"]:
            self.skipTest("외부 PDF 없음")
        for f in ("request_no", "request_datetime", "branch"):
            got, tot = r["presence"][f]
            self.assertEqual(got, tot, f"{f} 존재율 미달")


if __name__ == "__main__":
    unittest.main()
