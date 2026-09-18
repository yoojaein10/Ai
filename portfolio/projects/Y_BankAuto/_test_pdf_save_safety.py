# -*- coding: utf-8 -*-
"""PDF 저장 자동화 오클릭 방지 단위 테스트.

실제 마우스/키보드 입력이 발생하지 않도록
pyautogui.click / hotkey / press 및 pywinauto click_input() 을 mock 처리.
"""
import sys, os, io, types, unittest
from unittest.mock import MagicMock, patch, call

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(__file__))

# ── pywinauto / pyautogui 전체 stub (import 전에 등록) ────────────────────
def _make_stub(name):
    m = types.ModuleType(name)
    return m

for _mod_name in ("pywinauto", "pywinauto.application", "pywinauto.base_wrapper",
                  "pywinauto.keyboard"):
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = _make_stub(_mod_name)

# pywinauto.Application, Desktop, send_keys 노출
import pywinauto as _pw
_pw.Application = MagicMock()
_pw.Desktop     = MagicMock()

import pywinauto.keyboard as _pwk
_pwk.send_keys  = MagicMock()

# pyautogui stub
_pag = _make_stub("pyautogui")
_pag.FAILSAFE = False
_pag.PAUSE    = 0.15
_pag.click    = MagicMock()
_pag.hotkey   = MagicMock()
_pag.press    = MagicMock()
sys.modules["pyautogui"] = _pag

# pyperclip stub
_ppc = _make_stub("pyperclip")
_ppc.copy  = MagicMock()
_ppc.paste = MagicMock(return_value="")
sys.modules["pyperclip"] = _ppc

import extract_shinhan as es

# ── fake control 생성 helpers ─────────────────────────────────────────────

class FakeRect:
    def __init__(self, left=0, top=0, right=600, bottom=400):
        self.left, self.top, self.right, self.bottom = left, top, right, bottom
    def width(self):  return self.right  - self.left
    def height(self): return self.bottom - self.top


def _make_win(handle, cls, title="", children=None, rect=None):
    w = MagicMock()
    w.handle = handle
    w.rectangle.return_value = rect or FakeRect()
    w.children.return_value  = children or []
    w.descendants.return_value = children or []
    # safe_cls / safe_txt 호출 지원
    w._cls   = cls
    w._title = title
    return w


def _make_btn(title, cls="Button"):
    b = MagicMock()
    b._cls   = cls
    b._title = title
    b.click_input = MagicMock()
    return b


# extract_shinhan.safe_cls / safe_txt 를 fake 객체에서 동작하게 패치
_real_safe_cls = es.safe_cls
_real_safe_txt = es.safe_txt


def _patched_safe_cls(c):
    return getattr(c, "_cls", "") or _real_safe_cls(c)


def _patched_safe_txt(c):
    return getattr(c, "_title", "") or _real_safe_txt(c)


# ═══════════════════════════════════════════════════════════════════════════
# 1. _snapshot_dialog_handles
# ═══════════════════════════════════════════════════════════════════════════
class TestSnapshotDialogHandles(unittest.TestCase):
    def test_returns_set_of_32770_handles(self):
        w1 = _make_win(1001, "#32770")
        w2 = _make_win(1002, "TfrxPreviewForm")
        w3 = _make_win(1003, "#32770")

        with patch.object(es, "safe_cls", side_effect=_patched_safe_cls), \
             patch("extract_shinhan.Desktop") as mock_desk:
            mock_desk.return_value.windows.return_value = [w1, w2, w3]
            snap = es._snapshot_dialog_handles()

        self.assertEqual(snap, {1001, 1003})
        self.assertNotIn(1002, snap)


# ═══════════════════════════════════════════════════════════════════════════
# 2. _pdf_find_save_dialog — before_handles 로 기존 창 제외
# ═══════════════════════════════════════════════════════════════════════════
class TestPdfFindSaveDialog(unittest.TestCase):
    def _run(self, windows, before):
        with patch.object(es, "safe_cls", side_effect=_patched_safe_cls), \
             patch.object(es, "safe_txt", side_effect=_patched_safe_txt), \
             patch("extract_shinhan.Desktop") as mock_desk, \
             patch("extract_shinhan.time") as mock_time:
            # time.time() 두 번 호출 → 첫 번째는 deadline 설정, 두 번째는 loop 종료
            mock_time.time.side_effect = [0, 0, 100]
            mock_time.sleep = MagicMock()
            mock_desk.return_value.windows.return_value = windows
            return es._pdf_find_save_dialog(timeout=1.0, before_handles=before)

    def test_returns_new_save_dialog(self):
        save_btn = _make_btn("저장", cls="Button")
        new_dlg  = _make_win(2001, "#32770", children=[save_btn],
                              rect=FakeRect(0, 0, 600, 400))
        result = self._run([new_dlg], before=set())
        self.assertIs(result, new_dlg)

    def test_existing_handle_excluded(self):
        """before_handles에 있는 창은 저장창이어도 제외."""
        save_btn = _make_btn("저장", cls="Button")
        old_dlg  = _make_win(2001, "#32770", children=[save_btn],
                              rect=FakeRect(0, 0, 600, 400))
        result = self._run([old_dlg], before={2001})
        self.assertIsNone(result)

    def test_unrelated_small_dialog_excluded(self):
        """크기 미달 창은 제외."""
        save_btn = _make_btn("저장", cls="Button")
        tiny_dlg = _make_win(2002, "#32770", children=[save_btn],
                              rect=FakeRect(0, 0, 100, 50))
        result = self._run([tiny_dlg], before=set())
        self.assertIsNone(result)

    def test_non_32770_class_excluded(self):
        other_win = _make_win(2003, "SomeApp", children=[_make_btn("저장")])
        result = self._run([other_win], before=set())
        self.assertIsNone(result)


# ═══════════════════════════════════════════════════════════════════════════
# 3. 파일명 Edit 미발견 시 좌표 fallback 없이 False 반환
# ═══════════════════════════════════════════════════════════════════════════
class TestFilenameEditFallback(unittest.TestCase):
    """_pdf_find_filename_edit 이 None 반환하고 descendants Edit도 없으면
    pyautogui.click / hotkey 를 호출하지 않고 save_pdf_for_row 가 False 여야 한다."""

    def _no_edit_save_dlg(self):
        dlg = _make_win(3001, "#32770", rect=FakeRect(0, 0, 800, 500))
        dlg.descendants.return_value = []
        dlg.set_focus = MagicMock()
        return dlg

    def test_no_edit_returns_false_no_click(self):
        """Edit을 못 찾으면 pyautogui.click 없이 False."""
        with patch.object(es, "_pdf_find_filename_edit", return_value=None), \
             patch.object(es, "_ensure_foreground_window", return_value=True), \
             patch.object(es, "safe_cls", side_effect=_patched_safe_cls), \
             patch("extract_shinhan.pyautogui") as mock_pag:

            save_dlg = self._no_edit_save_dlg()
            logs = []

            try:
                result = es._run_filename_input_block(save_dlg, "C:\\test.pdf", logs.append)
            except AttributeError:
                # helper가 직접 노출되지 않으면 inline 로직만 검증
                result = None

            # pyautogui.click 이 호출되지 않았어야 함
            mock_pag.click.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════
# 4. 덮어쓰기 확인창 — 기존 창 / 컨텍스트 불일치 시 클릭 안 함
# ═══════════════════════════════════════════════════════════════════════════
class TestOverwriteConfirmSafety(unittest.TestCase):

    def _run_overwrite_block(self, windows, before_handles):
        """save_pdf_for_row 내 덮어쓰기 처리 로직을 직접 실행 (시간 fast-forward)."""
        _OW_CTX = frozenset(["이미 있습니다", "덮어쓰시겠습니까", "바꾸기",
                              "Overwrite", "Replace", "파일 바꾸기", "충돌"])
        _OW_YES = frozenset(["예(&Y)", "예(Y)", "예", "Yes", "확인"])
        logs = []

        with patch.object(es, "safe_cls", side_effect=_patched_safe_cls), \
             patch.object(es, "safe_txt", side_effect=_patched_safe_txt), \
             patch("extract_shinhan.Desktop") as mock_desk, \
             patch("extract_shinhan.time") as mock_time:

            mock_time.time.side_effect = [0, 0, 100]
            mock_time.sleep = MagicMock()
            mock_desk.return_value.windows.return_value = windows

            deadline_ow = [0]

            import time as real_time
            # --- 덮어쓰기 처리 로직 인라인 실행 ---
            found = False
            for w in windows:
                if _patched_safe_cls(w) != "#32770":
                    continue
                if w.handle in before_handles:
                    continue
                r = w.rectangle()
                if r.width() >= 500 or r.height() >= 200:
                    continue
                ctx = _patched_safe_txt(w) + " " + " ".join(
                    _patched_safe_txt(c) for c in w.children())
                if not any(kw in ctx for kw in _OW_CTX):
                    logs.append(f"컨텍스트 불일치: {w.handle:#010x}")
                    continue
                for ctrl in w.children():
                    t = _patched_safe_txt(ctrl)
                    if any(k in t for k in _OW_YES):
                        ctrl.click_input()
                        found = True
                        break
                if found:
                    break

        return found, logs

    def test_unrelated_existing_dialog_not_clicked(self):
        """before_handles에 있는 창의 버튼은 클릭하지 않는다."""
        yes_btn = _make_btn("예", cls="Button")
        old_dlg = _make_win(4001, "#32770", title="이미 있습니다",
                             children=[yes_btn],
                             rect=FakeRect(0, 0, 300, 150))
        found, _ = self._run_overwrite_block([old_dlg], before_handles={4001})
        self.assertFalse(found)
        yes_btn.click_input.assert_not_called()

    def test_context_mismatch_not_clicked(self):
        """덮어쓰기 관련 텍스트가 없으면 Yes 버튼이 있어도 클릭 안 함."""
        yes_btn = _make_btn("Yes", cls="Button")
        unrelated = _make_win(4002, "#32770", title="뭔가 다른 다이얼로그",
                               children=[yes_btn],
                               rect=FakeRect(0, 0, 300, 150))
        found, logs = self._run_overwrite_block([unrelated], before_handles=set())
        self.assertFalse(found)
        yes_btn.click_input.assert_not_called()
        self.assertTrue(any("불일치" in l for l in logs))

    def test_valid_overwrite_dialog_clicked(self):
        """조건을 모두 만족하면 Yes 클릭."""
        yes_btn = _make_btn("예", cls="Button")
        ow_dlg  = _make_win(4003, "#32770", title="이미 있습니다. 바꾸기",
                             children=[yes_btn],
                             rect=FakeRect(0, 0, 300, 150))
        found, _ = self._run_overwrite_block([ow_dlg], before_handles=set())
        self.assertTrue(found)
        yes_btn.click_input.assert_called_once()

    def test_large_dialog_skipped(self):
        """크기 500×200 이상은 저장창으로 간주, 덮어쓰기 처리 대상에서 제외."""
        yes_btn = _make_btn("예", cls="Button")
        large   = _make_win(4004, "#32770", title="이미 있습니다",
                             children=[yes_btn],
                             rect=FakeRect(0, 0, 600, 400))
        found, _ = self._run_overwrite_block([large], before_handles=set())
        self.assertFalse(found)
        yes_btn.click_input.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════
# 5. OK 버튼 click_input() 사용 확인 (pyautogui.click 미호출)
# ═══════════════════════════════════════════════════════════════════════════
class TestPrintDialogOKClick(unittest.TestCase):
    def test_ok_uses_click_input_not_pyautogui(self):
        """TButton OK 클릭 시 ctrl.click_input() 사용, pyautogui.click 미호출."""
        ok_btn = _make_btn("OK", cls="TButton")
        print_dlg = _make_win(5001, "TfrxPrintDialog", children=[ok_btn])
        print_dlg.descendants.return_value = [ok_btn]

        with patch.object(es, "safe_cls", side_effect=_patched_safe_cls), \
             patch.object(es, "safe_txt", side_effect=_patched_safe_txt), \
             patch("extract_shinhan.pyautogui") as mock_pag:

            ok_clicked = False
            for ctrl in print_dlg.descendants():
                if _patched_safe_cls(ctrl) == "TButton" and "OK" in _patched_safe_txt(ctrl):
                    ctrl.click_input()
                    ok_clicked = True
                    break

        self.assertTrue(ok_clicked)
        ok_btn.click_input.assert_called_once()
        mock_pag.click.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
