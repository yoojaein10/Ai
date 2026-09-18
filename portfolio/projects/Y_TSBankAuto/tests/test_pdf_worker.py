# -*- coding: utf-8 -*-
"""격리 PDF worker 테스트. 지시 §6."""
import os
import tempfile
import unittest

import config
import pdf_worker as PW


class TestScrubEnv(unittest.TestCase):
    def test_removes_db_bank24_secrets_and_switches(self):
        src = {
            "YTS_DB_SERVER": "s", "YTS_DB_NAME": "d", "YTS_DB_USER": "u",
            "YTS_DB_PASSWORD": "p", "YTS_ENABLE_READONLY_INTEGRATION": "x",
            config.ENV_BANK24_ID: "bid", config.ENV_BANK24_PASSWORD: "bpw",
            "YTS_ENABLE_BANK24_AUTOMATION": "on", "KEEP": "yes",
        }
        child = PW.scrubbed_child_env(src)
        for name in ("YTS_DB_SERVER", "YTS_DB_NAME", "YTS_DB_USER", "YTS_DB_PASSWORD",
                     "YTS_ENABLE_READONLY_INTEGRATION", config.ENV_BANK24_ID,
                     config.ENV_BANK24_PASSWORD, "YTS_ENABLE_BANK24_AUTOMATION"):
            self.assertNotIn(name, child)
        self.assertEqual(child["KEEP"], "yes")

    def test_source_not_mutated(self):
        src = {"YTS_DB_USER": "u"}
        PW.scrubbed_child_env(src)
        self.assertIn("YTS_DB_USER", src)


class _FakeModel:
    bank = "우리은행"
    addresses = ["서울특별시 강남구 역삼동 1"]

    def safe_log_dict(self):
        return {"bank": self.bank, "unit_count": len(self.addresses)}

    def field_presence(self):
        return {"bank": True}


class _FakePR:
    model = _FakeModel()
    eligible = True
    reasons = []


class TestParseToMasked(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.pdf = os.path.join(self.root, "a.pdf")
        with open(self.pdf, "wb") as f:
            f.write(b"%PDF-1.4\nx\n%%EOF\n")

    def tearDown(self):
        os.remove(self.pdf)
        os.rmdir(self.root)

    def test_parsed_masked_only(self):
        res = PW.parse_to_masked(
            self.pdf, [self.root],
            extractor=lambda p: ["line"], preparer=lambda lines: _FakePR())
        self.assertEqual(res["status"], "parsed")
        self.assertEqual(res["bank"], "우리은행")
        self.assertIn("model", res)
        # 원문 주소 미포함
        self.assertNotIn("역삼동", repr(res))

    def test_invalid_file(self):
        res = PW.parse_to_masked(os.path.join(self.root, "missing.pdf"), [self.root])
        self.assertEqual(res["status"], "pdf_invalid")

    def test_extract_failure(self):
        def boom(p):
            raise ValueError("bad")
        res = PW.parse_to_masked(self.pdf, [self.root], extractor=boom)
        self.assertEqual(res["status"], "extract_failed")


if __name__ == "__main__":
    unittest.main()
