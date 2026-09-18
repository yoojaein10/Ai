# -*- coding: utf-8 -*-
"""보안 유틸 테스트: 마스킹, 파일명, 경로, 시크릿 검출."""
import os
import unittest

import security


class TestMasking(unittest.TestCase):
    def test_name(self):
        self.assertEqual(security.mask_name("홍길동"), "홍*동")
        self.assertEqual(security.mask_name("김나윤"), "김*윤")
        self.assertEqual(security.mask_name("홍길"), "홍*")
        self.assertEqual(security.mask_name("김"), "*")

    def test_phone(self):
        self.assertEqual(security.mask_phone('010-0000-0000'), "*******5678")
        self.assertEqual(security.mask_phone("0236736357"), "******6357")

    def test_address(self):
        masked = security.mask_address("서울특별시 강남구 역삼동 100-1 샘플빌딩 501호")
        self.assertNotIn("100-1", masked)
        self.assertNotIn("501호", masked)
        self.assertIn("강남구", masked)

    def test_connection_string_blocked(self):
        cs = 'DRIVER={ODBC Driver 18};SERVER=host,1433;UID=u;PWD=REDACTED_CONFIGURE_LOCALLY;'
        self.assertEqual(security.mask_connection_string(cs), "[BLOCKED connection-string]")

    def test_secret_kv_masked(self):
        out = security.mask_connection_string('PWD=REDACTED_CONFIGURE_LOCALLY; other=1')
        self.assertNotIn("topsecret", out)
        self.assertIn("PWD=***", out)

    def test_request_no(self):
        self.assertEqual(security.mask_request_no("T260613250"), "T2******50")


class TestFilename(unittest.TestCase):
    def test_strip_traversal(self):
        out = security.sanitize_filename("..\\..\\evil.pdf")
        self.assertNotIn("..", out)
        self.assertNotIn("\\", out)

    def test_reserved(self):
        out = security.sanitize_filename("CON.pdf")
        self.assertTrue(out.startswith("_"))

    def test_trailing_dot_space(self):
        out = security.sanitize_filename("name. ")
        self.assertFalse(out.endswith(" "))
        self.assertFalse(out.endswith("."))

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            security.sanitize_filename("   ")


class TestPath(unittest.TestCase):
    def test_within_root(self):
        root = os.path.dirname(os.path.abspath(__file__))
        inside = os.path.join(root, "fixtures", "x.pdf")
        self.assertTrue(security.is_within_root(inside, root))

    def test_escape_rejected(self):
        root = os.path.dirname(os.path.abspath(__file__))
        outside = os.path.join(root, "..", "..", "x.pdf")
        self.assertFalse(security.is_within_root(outside, root))

    def test_safe_join_escape(self):
        root = os.path.dirname(os.path.abspath(__file__))
        # 정화로 traversal 제거되어 루트 내부 경로가 됨
        p = security.safe_join_under_root(root, "..\\evil.pdf")
        self.assertTrue(security.is_within_root(p, root))


class TestSecretScan(unittest.TestCase):
    def test_detects_real_password(self):
        f = security.scan_text_for_secrets('password = Abcd1234!')
        self.assertTrue(any(x["is_value"] for x in f))

    def test_ignores_placeholder(self):
        f = security.scan_text_for_secrets('password = YOUR_PASSWORD')
        self.assertFalse(any(x["is_value"] for x in f))

    def test_detects_conn_string(self):
        f = security.scan_text_for_secrets("DRIVER={x};SERVER=h;UID=u;PWD=p")
        self.assertTrue(f)


if __name__ == "__main__":
    unittest.main()
