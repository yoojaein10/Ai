# -*- coding: utf-8 -*-
"""PDF worker 자원제한·격리 하드닝 테스트 (지시 §11, §11-a, §16)."""
import json
import os
import socket
import tempfile
import unittest

import pdf_worker as PW


class TestResultSchema(unittest.TestCase):
    def test_valid(self):
        obj = {"status": "parsed", "bank": "우리은행", "eligible": True}
        self.assertEqual(PW.validate_result_obj(obj)["status"], "parsed")

    def test_non_dict(self):
        self.assertEqual(PW.validate_result_obj([1, 2])["status"], "worker_output_invalid")

    def test_missing_status(self):
        self.assertEqual(PW.validate_result_obj({"bank": "x"})["status"],
                         "worker_output_invalid")

    def test_unknown_key_rejected(self):
        self.assertEqual(
            PW.validate_result_obj({"status": "parsed", "evil": "x"})["status"],
            "worker_output_invalid")


class TestResultFile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.rp = os.path.join(self.tmp, "result.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_read_valid(self):
        with open(self.rp, "w", encoding="utf-8") as f:
            f.write(json.dumps({"status": "parsed"}))
        self.assertEqual(PW._read_result_file(self.rp)["status"], "parsed")

    def test_missing_returns_none(self):
        self.assertIsNone(PW._read_result_file(self.rp))

    def test_oversize_rejected(self):
        with open(self.rp, "w", encoding="utf-8") as f:
            f.write("x" * (PW.MAX_RESULT_BYTES + 10))
        self.assertEqual(PW._read_result_file(self.rp)["status"], "worker_output_invalid")

    def test_write_exclusive_create(self):
        PW._write_result_file(self.rp, json.dumps({"status": "parsed"}))
        # 이미 존재 → exclusive-create 실패(덮어쓰기 금지)
        with self.assertRaises(OSError):
            PW._write_result_file(self.rp, json.dumps({"status": "parsed"}))


class TestExeValidation(unittest.TestCase):
    def test_invalid_exe(self):
        res = PW.run_isolated("x.pdf", [os.getcwd()],
                              python_exe=os.path.join(tempfile.gettempdir(), "nope.exe"))
        self.assertEqual(res["status"], "worker_exe_invalid")


class TestNoNetwork(unittest.TestCase):
    def test_module_has_no_network_imports(self):
        # 모듈 네임스페이스에 네트워크 라이브러리가 로드되어 있지 않아야 한다.
        for name in ("socket", "urllib", "requests", "http", "ftplib", "winhttp"):
            self.assertFalse(hasattr(PW, name), f"{name} 가 worker 에 import 됨")

    def test_source_has_no_network_tokens(self):
        with open(PW.__file__, encoding="utf-8") as f:
            src = f.read().lower()
        for token in ("import socket", "import urllib", "import requests",
                      "import ftplib", "winhttp", "urlopen"):
            self.assertNotIn(token, src)

    def test_parse_makes_no_socket(self):
        # parse_to_masked 는 소켓을 만들지 않는다(가드로 확인).
        made = []
        orig = socket.socket

        def guard(*a, **k):
            made.append(1)
            return orig(*a, **k)

        socket.socket = guard
        try:
            root = tempfile.mkdtemp()
            pdf = os.path.join(root, "a.pdf")
            with open(pdf, "wb") as f:
                f.write(b"%PDF-1.4\nx\n%%EOF\n")
            PW.parse_to_masked(pdf, [root],
                               extractor=lambda p: ["l"], preparer=None)
        finally:
            socket.socket = orig
        self.assertEqual(made, [])


class TestIntegration(unittest.TestCase):
    def test_run_isolated_returns_status(self):
        # 실제 자식 프로세스 spawn(Job Object 또는 fallback). 결과에 status 존재.
        root = tempfile.mkdtemp()
        pdf = os.path.join(root, "a.pdf")
        with open(pdf, "wb") as f:
            f.write(b"%PDF-1.4\nx\n%%EOF\n")
        try:
            res = PW.run_isolated(pdf, [root], timeout=60)
            self.assertIn("status", res)
        finally:
            import shutil
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
