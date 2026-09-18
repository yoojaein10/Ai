# -*- coding: utf-8 -*-
"""SP 메타데이터 정규화/fingerprint/pin/diff 테스트. 지시 §10, §11."""
import unittest

import ro_metadata as M
import ts_db_writer as W


# READ_SP_METADATA 컬럼: parameter_id, name, is_output, type_name, is_user_defined,
# base_type_name, max_length, precision, scale
def _rows_from_specs():
    rows = []
    pid = 0
    for spec in W.INPUT_PARAM_SPECS:
        pid += 1
        rows.append((pid, "@" + spec.name, 0, "varchar", 0, "varchar", 40, 0, 0))
    for spec in W.OUTPUT_PARAM_SPECS:
        pid += 1
        rows.append((pid, "@" + spec.name, 1, "int", 0, "int", 4, 10, 0))
    return rows


class TestNormalize(unittest.TestCase):
    def test_normalize_strips_at_and_sorts(self):
        rows = [(2, "@B", 1, "int", 0, "int", 4, 10, 0),
                (1, "@A", 0, "varchar", 0, "varchar", 30, 0, 0)]
        norm = M.normalize_rows(rows)
        self.assertEqual([p.name for p in norm], ["A", "B"])
        self.assertEqual(norm[0].parameter_id, 1)
        self.assertTrue(norm[1].is_output)

    def test_null_lengths(self):
        rows = [(1, "@A", 0, "varchar", 0, "varchar", None, None, None)]
        norm = M.normalize_rows(rows)
        self.assertIsNone(norm[0].max_length)


class TestFingerprint(unittest.TestCase):
    def test_stable(self):
        norm = M.normalize_rows(_rows_from_specs())
        self.assertEqual(M.compute_fingerprint(norm), M.compute_fingerprint(norm))

    def test_change_detected(self):
        rows = _rows_from_specs()
        fp1 = M.compute_fingerprint(M.normalize_rows(rows))
        rows2 = list(rows)
        pid, name, isout, ty, udt, bt, ml, pr, sc = rows2[0]
        rows2[0] = (pid, name, isout, ty, udt, bt, 99, pr, sc)   # 길이 변경
        fp2 = M.compute_fingerprint(M.normalize_rows(rows2))
        self.assertNotEqual(fp1, fp2)

    def test_order_independent_of_input_order(self):
        rows = _rows_from_specs()
        fp1 = M.compute_fingerprint(M.normalize_rows(rows))
        fp2 = M.compute_fingerprint(M.normalize_rows(list(reversed(rows))))
        self.assertEqual(fp1, fp2)   # parameter_id 로 정렬


class TestPin(unittest.TestCase):
    def test_unpinned_provisional(self):
        res = M.evaluate_pin("abc", allowlist_target_ok=True, pinned=None)
        self.assertEqual(res["status"], "provisional")
        self.assertFalse(res["metadata_verified"])

    def test_pin_match_verified_only_if_target_ok(self):
        res = M.evaluate_pin("abc", allowlist_target_ok=True, pinned="abc")
        self.assertTrue(res["metadata_verified"])
        res2 = M.evaluate_pin("abc", allowlist_target_ok=False, pinned="abc")
        self.assertFalse(res2["metadata_verified"])

    def test_mismatch_blocks(self):
        res = M.evaluate_pin("abc", allowlist_target_ok=True, pinned="xyz")
        self.assertEqual(res["status"], "mismatch")
        self.assertFalse(res["metadata_verified"])

    def test_default_pin_is_none(self):
        self.assertIsNone(M.PINNED_FINGERPRINT)   # 자동 pin 금지


class TestStructureDiff(unittest.TestCase):
    def test_matches_current_definition(self):
        norm = M.normalize_rows(_rows_from_specs())
        diff = M.structure_diff(norm)
        self.assertEqual(diff["only_in_db"], [])
        self.assertEqual(diff["only_in_code"], [])
        self.assertEqual(diff["direction_mismatch"], [])
        self.assertTrue(diff["order_matches"])
        self.assertIn("nullability", diff["unknown_semantics"])

    def test_detects_extra_db_param(self):
        rows = _rows_from_specs()
        rows.append((999, "@ExtraCol", 0, "varchar", 0, "varchar", 10, 0, 0))
        diff = M.structure_diff(M.normalize_rows(rows))
        self.assertIn("ExtraCol", diff["only_in_db"])

    def test_detects_direction_mismatch(self):
        rows = _rows_from_specs()
        # 첫 입력 파라미터를 output 으로 뒤집음
        pid, name, isout, ty, udt, bt, ml, pr, sc = rows[0]
        rows[0] = (pid, name, 1, ty, udt, bt, ml, pr, sc)
        diff = M.structure_diff(M.normalize_rows(rows))
        self.assertTrue(diff["direction_mismatch"])

    def test_no_record_values(self):
        # diff 결과에 실제 레코드 값이 없어야 한다(구조/이름만)
        diff = M.structure_diff(M.normalize_rows(_rows_from_specs()))
        self.assertNotIn("rows", diff)


if __name__ == "__main__":
    unittest.main()
