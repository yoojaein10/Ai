# -*- coding: utf-8 -*-
"""save_result() 0건 저장 생략 단위 테스트."""
import sys, os, io, types, unittest, tempfile, pathlib
from unittest.mock import MagicMock

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(__file__))

# ── pywinauto / pyautogui stub (실제 패키지 임포트 차단) ──────────────────
def _stub(name):
    m = types.ModuleType(name)
    return m

for _n in ("pywinauto", "pywinauto.application", "pywinauto.base_wrapper",
           "pywinauto.keyboard"):
    if _n not in sys.modules:
        sys.modules[_n] = _stub(_n)

import pywinauto as _pw
_pw.Application = MagicMock()
_pw.Desktop     = MagicMock()

import pywinauto.keyboard as _pwk
_pwk.send_keys = MagicMock()

_pag = _stub("pyautogui")
_pag.FAILSAFE = False
_pag.PAUSE    = 0.0
_pag.click    = MagicMock()
_pag.hotkey   = MagicMock()
_pag.press    = MagicMock()
sys.modules["pyautogui"] = _pag

for _n in ("pynput", "pynput.mouse", "pynput.keyboard",
           "pyperclip", "win32api", "win32con", "win32gui"):
    if _n not in sys.modules:
        sys.modules[_n] = _stub(_n)

import extract_shinhan as _es

_COUNTS = {
    "total": 0, "total_dambo": 0,
    "shinhan_all": 0, "shinhan_dambo": 0,
    "pdf_tried": 0, "pdf_success": 0,
    "pdf_parse_success": 0, "pdf_parse_fail": 0,
}

_ITEM_OK   = {"처리상태": "성공", "의뢰번호": "TEST-001"}
_ITEM_FAIL = {"처리상태": "실패", "의뢰번호": "TEST-002", "실패사유": "테스트"}


class TestSaveResultEmpty(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._orig_dir = _es.OUTPUT_DIR
        _es.OUTPUT_DIR = pathlib.Path(self._tmp)

    def tearDown(self):
        _es.OUTPUT_DIR = self._orig_dir

    # ── 0건 → None 반환, 파일 미생성 ─────────────────────────────────────
    def test_빈items_None반환(self):
        result = _es.save_result([], _COUNTS)
        self.assertIsNone(result, "items=[] 이면 None 반환해야 함")

    def test_빈items_파일미생성(self):
        _es.save_result([], _COUNTS)
        files = list(pathlib.Path(self._tmp).glob("*.txt"))
        self.assertEqual(files, [], "items=[] 이면 txt 파일 생성 안 해야 함")

    # ── 성공 1건 → 파일 생성 ──────────────────────────────────────────────
    def test_성공1건_파일생성(self):
        result = _es.save_result([_ITEM_OK], _COUNTS)
        self.assertIsNotNone(result, "성공 item 있으면 파일 경로 반환해야 함")
        self.assertTrue(pathlib.Path(result).exists(), "반환된 파일 경로가 실제 존재해야 함")

    # ── 실패 1건 → 파일 생성 ──────────────────────────────────────────────
    def test_실패1건_파일생성(self):
        result = _es.save_result([_ITEM_FAIL], _COUNTS)
        self.assertIsNotNone(result, "실패 item 있으면 파일 경로 반환해야 함")
        self.assertTrue(pathlib.Path(result).exists())

    # ── 성공+실패 혼합 → 파일 생성 ──────────────────────────────────────
    def test_혼합_파일생성(self):
        result = _es.save_result([_ITEM_OK, _ITEM_FAIL], _COUNTS)
        self.assertIsNotNone(result)
        self.assertTrue(pathlib.Path(result).exists())

    # ── None이 "None" 문자열로 노출되지 않아야 함 ─────────────────────
    def test_None_문자열_미노출(self):
        fname = _es.save_result([], _COUNTS)
        file_str = str(fname) if fname else ""
        self.assertNotEqual(file_str, "None",
                            "None 반환값을 str()하면 'None' 문자열이 되면 안 됨")
        self.assertEqual(file_str, "",
                         "items=0건일 때 file 필드는 빈 문자열이어야 함")


if __name__ == "__main__":
    unittest.main(verbosity=2)
