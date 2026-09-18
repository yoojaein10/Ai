# -*- coding: utf-8 -*-
"""GUI 마스킹 표시 함수 테스트(tkinter 없이). 지시 §11."""
import unittest

import gui
import ro_lookups
from orchestrator import RunReport


class TestFormatReport(unittest.TestCase):
    def _report(self):
        r = RunReport()
        r.add("download_pdf", True, "저장됨")
        r.add("parse", True, "parsed")
        r.parse_masked = {"status": "parsed", "bank": "우리은행", "multi_unit": True}
        r.customer_status = ro_lookups.SINGLE
        r.customer_dtos = [ro_lookups.MaskedCustomerDTO("C*1", "우*점", "Y")]
        r.reghist_status = ro_lookups.MULTIPLE
        r.reghist_dtos = [ro_lookups.MaskedRegHistDTO("R*0", "E*", "리*"),
                          ro_lookups.MaskedRegHistDTO("R*1", "E*", "리*")]
        r.duplicate_status = "undecidable"
        r.metadata_status = "provisional"
        r.fingerprint_status = "provisional"
        r.decision = {"status": "unprocessable",
                      "reasons": ["SP 메타데이터 미검증(provisional/미pin/불일치)"]}
        r.db_connected = True
        return r

    def test_masked_lines(self):
        lines = gui.format_report_for_gui(self._report())
        blob = "\n".join(lines)
        self.assertIn("Customer: single_result", blob)
        self.assertIn("RegHist: multiple_results", blob)
        self.assertIn("중복: undecidable", blob)
        self.assertIn("처리불가 사유", blob)
        self.assertIn("COMMIT: False", blob)
        self.assertIn("SP 실행: False", blob)

    def test_multi_unit_policy_shown(self):
        lines = gui.format_report_for_gui(self._report())
        self.assertTrue(any("대표 물건" in ln for ln in lines))

    def test_no_raw_pii_or_secrets(self):
        # DTO 는 마스킹만; 원문 값이 없어야 한다.
        lines = gui.format_report_for_gui(self._report())
        blob = "\n".join(lines)
        for forbidden in ("PWD", "DRIVER=", "SERVER=", "홍길동", "010-"):
            self.assertNotIn(forbidden, blob)

    def test_import_does_not_open_window(self):
        # gui import 만으로 tkinter 창을 띄우지 않는다(여기까지 왔으면 통과)
        self.assertTrue(hasattr(gui, "main"))


if __name__ == "__main__":
    unittest.main()
