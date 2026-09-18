# -*- coding: utf-8 -*-
"""PDF 안전 검증/추출 테스트: 손상/암호화/크기/페이지/경로탈출."""
import os
import shutil
import unittest

import security
from parsers import base

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = os.path.join(ROOT, "tmp", "_pdftest")


def _make_pdf(path, pages=1, text="SAMPLE"):
    import fitz
    doc = fitz.open()
    for _ in range(pages):
        pg = doc.new_page()
        pg.insert_text((72, 72), text)
    doc.save(path)
    doc.close()


class TestPdfSafety(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.makedirs(TMP, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TMP, ignore_errors=True)

    def test_valid_pdf(self):
        p = os.path.join(TMP, "ok.pdf")
        _make_pdf(p)
        security.validate_pdf_file(p, allowed_roots=[TMP])  # no raise
        lines = base.extract_lines(p, allowed_roots=[TMP], use_worker=False)
        self.assertTrue(any("SAMPLE" in ln for ln in lines))

    def test_corrupt_pdf(self):
        p = os.path.join(TMP, "bad.pdf")
        with open(p, "wb") as f:
            f.write(b"%PDF-1.4\n garbage not a real pdf %%EOF")
        with self.assertRaises(base.PdfExtractError):
            base.extract_lines(p, allowed_roots=[TMP], use_worker=False)

    def test_wrong_magic(self):
        p = os.path.join(TMP, "fake.pdf")
        with open(p, "wb") as f:
            f.write(b"NOTPDF data")
        with self.assertRaises(security.PdfSafetyError):
            security.validate_pdf_file(p, allowed_roots=[TMP])

    def test_encrypted_pdf(self):
        import fitz
        p = os.path.join(TMP, "enc.pdf")
        doc = fitz.open()
        doc.new_page().insert_text((72, 72), "secret")
        doc.save(p, encryption=fitz.PDF_ENCRYPT_AES_256,
                 owner_pw="o", user_pw="u")
        doc.close()
        with self.assertRaises(base.PdfExtractError):
            base.extract_lines(p, allowed_roots=[TMP], use_worker=False)

    def test_oversize(self):
        p = os.path.join(TMP, "big.pdf")
        _make_pdf(p)
        orig = security.MAX_PDF_BYTES
        try:
            security.MAX_PDF_BYTES = 10  # 강제로 작게
            with self.assertRaises(security.PdfSafetyError):
                security.validate_pdf_file(p, allowed_roots=[TMP])
        finally:
            security.MAX_PDF_BYTES = orig

    def test_page_over(self):
        p = os.path.join(TMP, "pages.pdf")
        _make_pdf(p, pages=2)
        orig = security.MAX_PDF_PAGES
        try:
            security.MAX_PDF_PAGES = 1
            with self.assertRaises(base.PdfExtractError):
                base.extract_lines(p, allowed_roots=[TMP], use_worker=False)
        finally:
            security.MAX_PDF_PAGES = orig

    def test_path_escape_rejected(self):
        p = os.path.join(TMP, "ok2.pdf")
        _make_pdf(p)
        # 허용 루트를 다른 디렉터리로 지정 → 거부
        other = os.path.join(ROOT, "tests")
        with self.assertRaises(security.PdfSafetyError):
            security.validate_pdf_file(p, allowed_roots=[other])

    def test_batch_one_failure_isolated(self):
        good = os.path.join(TMP, "g.pdf")
        bad = os.path.join(TMP, "b.pdf")
        _make_pdf(good)
        with open(bad, "wb") as f:
            f.write(b"%PDF-1.4 broken")
        results = []
        for p in (good, bad):
            try:
                base.extract_lines(p, allowed_roots=[TMP], use_worker=False)
                results.append("ok")
            except base.PdfExtractError:
                results.append("fail")
        self.assertEqual(results, ["ok", "fail"])  # 한 건 실패가 배치 중단 안 함


if __name__ == "__main__":
    unittest.main()
