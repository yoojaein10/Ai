# -*- coding: utf-8 -*-
"""로그 정화·예외 위생 테스트 (지시 §15, §16)."""
import logging
import os
import tempfile
import unittest

import applog


class TestSanitize(unittest.TestCase):
    def test_strips_crlf_and_control(self):
        out = applog.sanitize_line("line1\r\nINJECTED admin\tlogin\x00x")
        self.assertNotIn("\n", out)
        self.assertNotIn("\r", out)
        self.assertNotIn("\x00", out)
        self.assertNotIn("\t", out)

    def test_strips_ansi(self):
        out = applog.sanitize_line("\x1b[31mRED\x1b[0m text")
        self.assertNotIn("\x1b", out)
        self.assertIn("RED", out)

    def test_redacts_connection_string(self):
        out = applog.sanitize_line("DRIVER={x};SERVER=host,1433;PWD=secret")
        self.assertNotIn("secret", out)
        self.assertNotIn("host", out)

    def test_redacts_path_email_phone(self):
        out = applog.sanitize_line('saved C:\\Users\\PUBLIC_USER\\pdf\\1.pdf mail contact@example.com 010-0000-0000')
        self.assertNotIn("Users", out)
        self.assertNotIn('contact@example.com', out)
        self.assertNotIn("1234", out)
        self.assertIn("[path]", out)

    def test_one_line_normalization(self):
        out = applog.sanitize_line("a\nb\nc")
        self.assertEqual(out.count("\n"), 0)


class TestFileLogging(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        # 핸들러가 파일을 잡고 있을 수 있으므로 먼저 정리
        for h in list(applog.get_logger().handlers):
            applog.get_logger().removeHandler(h)
            try:
                h.close()
            except Exception:
                pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_file_log_created_in_given_dir(self):
        logger = applog.configure_logging(enable_file=True, log_dir=self.tmp)
        logger.info("hello secret PWD=abc")
        logfile = os.path.join(self.tmp, "ytsbank.log")
        self.assertTrue(os.path.isfile(logfile))
        with open(logfile, encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("abc", content)      # 레닥션 적용됨
        self.assertIn("hello", content)

    def test_unc_dir_rejected(self):
        self.assertFalse(applog._log_dir_safe(r"\\server\share\logs"))

    def test_rotation_handler_used(self):
        logger = applog.configure_logging(enable_file=True, log_dir=self.tmp)
        kinds = [type(h).__name__ for h in logger.handlers]
        self.assertIn("RotatingFileHandler", kinds)


class TestExceptHook(unittest.TestCase):
    def test_install_and_faulthandler(self):
        applog.configure_logging(enable_file=False)
        applog.install_excepthook()
        applog.disable_faulthandler()
        import faulthandler
        self.assertFalse(faulthandler.is_enabled())
        # excepthook 이 원문 대신 안전 코드만 로깅하는지(예외 없이 동작)
        import sys
        try:
            raise ValueError("raw-secret-detail")
        except ValueError:
            et, e, tb = sys.exc_info()
        sys.excepthook(et, e, tb)   # 예외 없이 처리되어야 함


if __name__ == "__main__":
    unittest.main()
