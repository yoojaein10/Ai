# -*- coding: utf-8 -*-
"""PDF 안전 다운로드·저장 테스트. 지시 §5."""
import os
import tempfile
import unittest

import pdf_download as D

VALID_PDF = b"%PDF-1.4\ncontent\n%%EOF\n"


class TestFilename(unittest.TestCase):
    def test_uuid_ts_pdf(self):
        name = D.generate_filename("2026-07-01T12:00")
        self.assertTrue(name.endswith(".pdf"))
        self.assertIn("_", name)
        # PII/원문 파일명 요소 없음: uuid hex + 숫자만
        stem = name[:-4]
        uid, _, ts = stem.partition("_")
        self.assertEqual(len(uid), 32)
        self.assertTrue(ts.isalnum())

    def test_unique(self):
        self.assertNotEqual(D.generate_filename("t"), D.generate_filename("t"))


class TestSave(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def tearDown(self):
        for f in os.listdir(self.root):
            os.remove(os.path.join(self.root, f))
        os.rmdir(self.root)

    def test_saves_valid_pdf(self):
        path = D.save_pdf_bytes(VALID_PDF, self.root, timestamp="20260701")
        self.assertTrue(os.path.isfile(path))
        self.assertTrue(D.security.is_within_root(path, self.root))
        with open(path, "rb") as f:
            self.assertTrue(f.read().startswith(b"%PDF-"))

    def test_rejects_non_pdf(self):
        with self.assertRaises(D.PdfDownloadError):
            D.save_pdf_bytes(b"NOTPDF", self.root, timestamp="t")
        self.assertEqual(os.listdir(self.root), [])   # 부분 파일 없음

    def test_rejects_oversize(self):
        import security
        big = b"%PDF-" + b"0" * (security.MAX_PDF_BYTES + 1)
        with self.assertRaises(D.PdfDownloadError):
            D.save_pdf_bytes(big, self.root, timestamp="t")
        self.assertEqual([f for f in os.listdir(self.root) if f.endswith(".part")], [])

    def test_no_overwrite(self):
        orig = D.generate_filename
        D.generate_filename = lambda ts: "fixed_name.pdf"
        try:
            D.save_pdf_bytes(VALID_PDF, self.root, timestamp="t")
            with self.assertRaises(D.PdfDownloadError):
                D.save_pdf_bytes(VALID_PDF, self.root, timestamp="t")   # 덮어쓰기 금지
        finally:
            D.generate_filename = orig

    def test_cleanup_on_stop(self):
        with self.assertRaises(D.PdfDownloadError):
            D.save_pdf_bytes(VALID_PDF, self.root, timestamp="t",
                             stop_check=lambda: True)
        self.assertEqual(os.listdir(self.root), [])

    def test_bad_root(self):
        with self.assertRaises(D.PdfDownloadError):
            D.save_pdf_bytes(VALID_PDF, os.path.join(self.root, "nope"), timestamp="t")


class TestReparse(unittest.TestCase):
    def test_normal_dir_no_reparse(self):
        d = tempfile.mkdtemp()
        try:
            self.assertFalse(D._has_reparse_point(d))
            self.assertEqual(os.path.realpath(d), D.assert_safe_root(d))
        finally:
            os.rmdir(d)

    def test_symlink_root_rejected(self):
        base = tempfile.mkdtemp()
        target = os.path.join(base, "real")
        link = os.path.join(base, "link")
        os.mkdir(target)
        try:
            try:
                os.symlink(target, link, target_is_directory=True)
            except (OSError, NotImplementedError, AttributeError):
                self.skipTest("symlink 생성 권한 없음")
            with self.assertRaises(D.PdfDownloadError):
                D.assert_safe_root(link)
        finally:
            if os.path.islink(link):
                os.remove(link)
            os.rmdir(target)
            os.rmdir(base)


if __name__ == "__main__":
    unittest.main()
