# -*- coding: utf-8 -*-
"""fixtures 가 합성/비식별 자료인지 검사 (S2/S15).

- 시크릿 패턴 부재
- 실데이터 의심 패턴(11자리 휴대폰, 주민번호 형태) 부재
- 합성 마커('샘플') 존재
"""
import glob
import os
import re
import unittest

import security

FIX = os.path.join(os.path.dirname(__file__), "fixtures")

_REAL_PHONE = re.compile(r"(?<!\d)01[016789]-?\d{3,4}-?\d{4}(?!\d)")
_JUMIN = re.compile(r"\b\d{6}-?[1-4]\d{6}\b")


class TestFixturesClean(unittest.TestCase):
    def test_no_secrets_no_pii(self):
        files = glob.glob(os.path.join(FIX, "*.txt"))
        self.assertTrue(files, "fixture 파일이 없음")
        for fp in files:
            with open(fp, encoding="utf-8") as f:
                text = f.read()
            findings = [x for x in security.scan_text_for_secrets(text) if x["is_value"]]
            self.assertFalse(findings, f"{fp}: 시크릿 의심")
            self.assertIsNone(_REAL_PHONE.search(text), f"{fp}: 실 휴대폰 의심")
            self.assertIsNone(_JUMIN.search(text), f"{fp}: 주민번호 의심")
            self.assertIn("샘플", text, f"{fp}: 합성 마커 없음")


if __name__ == "__main__":
    unittest.main()
