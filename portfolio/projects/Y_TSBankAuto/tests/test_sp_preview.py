# -*- coding: utf-8 -*-
"""SP 미리보기 출처 태깅·마스킹·분리 테스트 (지시 §13, §16)."""
import sys
import unittest

import sp_preview
import sp_spec


def _sample_params():
    # PDF 파생 + 고정값 + NULL 이 섞인 대표 케이스
    p = {name: None for name in sp_spec.INPUT_PARAM_NAMES}
    p["Office"] = "10"
    p["AppCode"] = "300611"
    p["Jun_Master"] = 0
    p["Score"] = 1
    p["CustName"] = "우리은행 강남지점"      # PDF 파생(PII 성격) → 마스킹
    p["Addr"] = "서울특별시 강남구 역삼동"    # PDF 파생 → 마스킹
    p["CustID"] = "C12345"                  # DB 조회값
    return p


class TestSource(unittest.TestCase):
    def test_source_classification(self):
        pv = sp_preview.build_preview(_sample_params())
        by = {r["name"]: r for r in pv["rows"]}
        self.assertEqual(by["Office"]["source"], sp_preview.SRC_FIXED)
        self.assertEqual(by["CustName"]["source"], sp_preview.SRC_PDF)
        self.assertEqual(by["CustID"]["source"], sp_preview.SRC_DB)
        self.assertEqual(by["MasterID"]["source"], sp_preview.SRC_NULL)

    def test_fixed_value_shown_pdf_masked(self):
        pv = sp_preview.build_preview(_sample_params())
        by = {r["name"]: r for r in pv["rows"]}
        self.assertEqual(by["Office"]["display"], "10")          # 비PII 상수 노출
        self.assertNotIn("강남", by["CustName"]["display"])       # PDF 값 마스킹
        self.assertNotIn("역삼동", by["Addr"]["display"])
        self.assertNotIn("C12345", by["CustID"]["display"])      # DB 값 마스킹

    def test_no_raw_pii_in_lines(self):
        pv = sp_preview.build_preview(_sample_params())
        blob = "\n".join(sp_preview.format_preview_lines(pv))
        for forbidden in ("역삼동", "C12345"):
            self.assertNotIn(forbidden, blob)


class TestWarnings(unittest.TestCase):
    def test_provisional_warning_when_unpinned(self):
        pv = sp_preview.build_preview(_sample_params(), metadata_verified=False)
        self.assertTrue(pv["provisional"])
        self.assertTrue(any("provisional" in w for w in pv["warnings"]))

    def test_execute_always_disabled(self):
        pv = sp_preview.build_preview(_sample_params(),
                                      metadata_verified=True,
                                      sp_definition_source="metadata")
        self.assertFalse(pv["execute_enabled"])   # 실행은 어떤 경우에도 비활성
        # pin 되면 provisional=False 이지만 실행 버튼은 여전히 없다.
        self.assertFalse(pv["provisional"])

    def test_none_params(self):
        pv = sp_preview.build_preview(None)
        self.assertEqual(pv["rows"], [])
        self.assertFalse(pv["execute_enabled"])


class TestImportSeparation(unittest.TestCase):
    def test_preview_does_not_import_write_execution(self):
        # sp_preview 는 execute_sp/commit 을 참조하지 않는다.
        self.assertFalse(hasattr(sp_preview, "execute_sp"))
        self.assertFalse(hasattr(sp_preview, "commit_with_guards"))
        with open(sp_preview.__file__, encoding="utf-8") as f:
            src = f.read()
        # 쓰기 모듈을 import·참조하지 않는다(주석 언급은 무관, 실제 호출/import 금지).
        self.assertNotIn("import ts_db_writer", src)
        self.assertNotIn("ts_db_writer.", src)
        self.assertNotIn(".execute_sp(", src)
        self.assertNotIn("commit_with_guards(", src)

    def test_pipeline_does_not_import_write_module(self):
        import pipeline
        with open(pipeline.__file__, encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("import ts_db_writer", src)

    def test_sp_spec_has_no_execution(self):
        self.assertFalse(hasattr(sp_spec, "execute_sp"))
        self.assertFalse(hasattr(sp_spec, "commit_with_guards"))


if __name__ == "__main__":
    unittest.main()
