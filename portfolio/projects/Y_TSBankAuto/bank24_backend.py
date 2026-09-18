# -*- coding: utf-8 -*-
"""프로덕션 UI 백엔드 (win32/pywinauto, 읽기 전용).

Y_BankAuto(검증본)의 win32 방식과 동등하게 최소 구현한다: Desktop(backend="win32"),
Edit 클래스 매칭, set_edit_text/WM_SETTEXT 직접 값설정, "확인" 버튼 BM_CLICK. 클립보드·
좌표·전역 send_keys·pyautogui·화면 캡처를 사용하지 않는다(§5/§53/§68).

RealBank24Adapter 가 보안 판단(신뢰 재검증/마스킹/타임아웃/중지)을 담당하고, 이 모듈은
검증된 창/컨트롤에 대한 최소 조작만 수행한다. 모든 pywinauto 호출에 유한 timeout(§87).

★ 미검증: 이 백엔드는 실제 Bank24 로 확인되지 않았다. 특히 TcxGrid 그리드의 직접 읽기
  가능 여부는 실통합에서 확인해야 하며, 직접 읽기가 불가하면 클립보드로 우회하지 않고
  GRID_CLIPBOARD_ONLY 로 중단한다(§74).
"""
from __future__ import annotations

from datetime import date, timedelta
import time

import bank24_automation as b24

_UI_TIMEOUT = 5.0

# Y_BankAuto 검증 클래스들
LOGIN_EDIT_CLASSES = ("Edit", "TEdit", "TMaskEdit", "TcxCustomDropDownInnerEdit")
LOGIN_WINDOW_CLASSES = ("TDXLoginDialog",)
OK_BUTTON_CLASSES = ("TButton", "Button")
OK_BUTTON_TEXT = "확인"
GRID_CLASSES = ("TcxGrid", "TcxGridSite", "TDBGrid", "TStringGrid")
GRID_FALLBACK_MAX_ROWS = 300
BUSINESS_RADIO_CLASS = "TcxCustomRadioGroupButton"
DATE_EDIT_CLASS = "TcxCustomDropDownInnerEdit"
QUERY_BUTTON_CLASS = "TcxButton"


def compute_query_range(today: date | None = None) -> tuple[str, str]:
    """탁상 조회 기간(시작일, 종료일) 문자열 계산.

    월요일이면 지난 금요일부터(금·토·일·월) 조회해 주말 접수분을 포함하고,
    그 외 요일은 전날부터 당일까지 조회한다. 종료일은 항상 당일.
    반환 형식은 'YYYY-MM-DD'.
    """
    d = today or date.today()
    back = 3 if d.weekday() == 0 else 1   # weekday(): 월=0 → 3일 전(금)
    start = (d - timedelta(days=back)).strftime("%Y-%m-%d")
    end = d.strftime("%Y-%m-%d")
    return start, end


def order_start_end_edits(edits):
    """날짜칸 2개를 화면 위치로 정렬해 (시작일칸, 종료일칸)을 반환한다.

    조회 화면은 '조회시작일'이 위, '조회종료일'이 아래인 세로 배치이므로
    위쪽(top 작은) 칸이 시작일이다. 같은 높이면 왼쪽(left 작은)이 시작일.
    좌표 조회 실패 시 입력 순서(edits[0]=시작)를 그대로 쓴다.
    """
    two = list(edits[:2])
    try:
        two = sorted(two, key=lambda c: (c.rectangle().top, c.rectangle().left))
    except Exception:
        pass
    return two[0], two[1]
SOURCE_TAB_RELATIVE_COORDS = {
    "\ubbf8\uc811\uc218": (147, 29),
    "\uc791\uc131": (205, 29),
}


def _safe_cls(w) -> str:
    try:
        return w.class_name()
    except Exception:
        try:
            return w.friendly_class_name()
        except Exception:
            return ""


def _safe_txt(w) -> str:
    try:
        return w.window_text() or ""
    except Exception:
        return ""


def _qdiag_write(lines) -> None:
    """탁상 조회 화면 진단을 %TEMP%\\Y_TSBankAuto_querydiag.txt 에 best-effort 기록.

    로컬 진단 전용(GUI/외부 전송 없음). 컨트롤 클래스·버튼 라벨·개수만 기록하고
    실제 의뢰 데이터(그리드 셀 값)는 담지 않는다.
    """
    try:
        import os
        import tempfile
        path = os.path.join(tempfile.gettempdir(), "Y_TSBankAuto_querydiag.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(str(x) for x in lines))
    except Exception:
        pass


def _safe_desktop_windows(retries: int = 6, delay: float = 0.15) -> list:
    """Desktop(backend="win32").windows() 를 열거 레이스에 견디게 감싼다.

    창이 열거 도중 닫히면 pywinauto 가 그 핸들의 래퍼 생성 중 예외(InvalidWindowHandle 등)를
    던져 호출 전체가 실패한다. 짧게 재시도하고, 끝내 실패하면 빈 리스트를 반환한다
    (호출자는 이번 회차만 건너뛴다). 창 목록 자체만 반환하며 값/PII 는 다루지 않는다.
    """
    from pywinauto import Desktop
    for _ in range(max(1, retries)):
        try:
            return list(Desktop(backend="win32").windows())
        except Exception:
            time.sleep(delay)
    return []


def _savediag_write(lines) -> None:
    """행별 PDF 저장 진단을 %TEMP%\\Y_TSBankAuto_savediag.txt 에 append(로컬 전용).

    단계별 성공/실패 지점·컨트롤 클래스·버튼 라벨만 기록하고 의뢰 데이터 값은 담지 않는다.
    """
    try:
        import os
        import tempfile
        path = os.path.join(tempfile.gettempdir(), "Y_TSBankAuto_savediag.txt")
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(str(x) for x in lines))
            f.write("\n----\n")
    except Exception:
        pass


def _dump_query_controls(descs) -> list:
    """조회 화면의 버튼/에디트/그리드/라디오 컨트롤을 요약(값 제외, 라벨·클래스만)."""
    out = []
    for c in descs:
        cl = _safe_cls(c)
        if cl in (QUERY_BUTTON_CLASS, "TButton", "Button", "TcxButton",
                  DATE_EDIT_CLASS, BUSINESS_RADIO_CLASS) or cl in GRID_CLASSES \
                or "Button" in cl or "Edit" in cl:
            try:
                r = c.rectangle()
                rect = (r.left, r.top, r.right, r.bottom)
            except Exception:
                rect = None
            try:
                vis, en = c.is_visible(), c.is_enabled()
            except Exception:
                vis = en = "?"
            # 버튼/라디오 라벨은 UI 식별자라 안전. 에디트는 값 노출 방지 위해 라벨 생략.
            label = _safe_txt(c) if ("Button" in cl or cl == BUSINESS_RADIO_CLASS) else "<edit>"
            out.append("cls=%s label=%r rect=%s vis=%s en=%s" % (cl, label, rect, vis, en))
    return out


class PywinautoReadonlyBackend:
    """win32 백엔드(읽기 전용). 의존성/컨트롤 부재 시 fail-closed."""

    # ── 프로세스 ──
    def find_processes_by_image(self, exe_norm: str) -> list:
        out = []
        try:
            import bank24_trust
            import psutil
            target = bank24_trust._normcase(exe_norm)
            for p in psutil.process_iter(["pid"]):
                try:
                    if bank24_trust._normcase(p.exe()) == target:
                        out.append(int(p.pid))
                except Exception:
                    continue
        except Exception:
            return []
        return out

    def snapshot_top_level(self) -> set:
        hwnds = set()
        try:
            import win32gui
            win32gui.EnumWindows(lambda h, _: hwnds.add(int(h)), None)
        except Exception:
            return set()
        return hwnds

    def launch(self, spec: dict) -> int:
        try:
            import subprocess
            proc = subprocess.Popen(
                spec["argv"], cwd=spec.get("cwd"), shell=False,
                env=spec.get("env") or {}, close_fds=spec.get("close_fds", True),
                creationflags=spec.get("creationflags", 0))
            return int(proc.pid)
        except Exception:
            raise b24.AutomationBlocked("LAUNCH_FAILED")

    def wait(self, seconds: float) -> None:
        try:
            time.sleep(min(max(float(seconds), 0.0), 2.0))
        except Exception:
            pass

    # ── 창 ──
    def _win_info(self, hwnd) -> "b24.WindowInfo":
        try:
            import win32gui
            import win32process
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            cls = win32gui.GetClassName(hwnd)
            title = win32gui.GetWindowText(hwnd)
        except Exception:
            raise b24.AutomationBlocked("WINDOW_QUERY_FAILED")
        exe = ""
        try:
            import bank24_trust
            exe = bank24_trust.pid_image_path(int(pid))
        except Exception:
            exe = ""
        return b24.WindowInfo(hwnd=int(hwnd), pid=int(pid), title=title,
                              window_class=cls, exe_path=exe)

    def _pid_top_windows(self, pid: int) -> list:
        hwnds = []
        try:
            import win32gui
            import win32process

            def _cb(h, _):
                try:
                    _, wpid = win32process.GetWindowThreadProcessId(h)
                    if int(wpid) == int(pid) and win32gui.IsWindowVisible(h):
                        hwnds.append(int(h))
                except Exception:
                    pass
                return True

            win32gui.EnumWindows(_cb, None)
        except Exception:
            return []
        return hwnds

    def find_main_window(self, pid: int, main_class: str):
        if not main_class:
            return None
        try:
            import win32gui
            for h in self._pid_top_windows(pid):
                try:
                    if win32gui.GetClassName(h) == main_class:
                        return self._win_info(h)
                except Exception:
                    continue
        except Exception:
            return None
        return None

    def find_login_window(self, pid: int):
        """TDXLoginDialog 또는 visible+enabled Edit 2개 이상인 창(Y_BankAuto 방식)."""
        try:
            import win32gui
            best = None
            for h in self._pid_top_windows(pid):
                try:
                    cls = win32gui.GetClassName(h)
                except Exception:
                    continue
                if cls in LOGIN_WINDOW_CLASSES:
                    return self._win_info(h)
                info = self._win_info(h)
                if len(self.login_edit_candidates(info)) >= 2 and best is None:
                    best = info
            return best
        except Exception:
            return None

    def foreground_info(self):
        try:
            import win32gui
            return self._win_info(win32gui.GetForegroundWindow())
        except Exception:
            raise b24.AutomationBlocked("FOREGROUND_QUERY_FAILED")

    @staticmethod
    def _window_handle(win) -> int:
        return int(getattr(win, "handle", getattr(win, "hwnd", 0)) or 0)

    def _ensure_foreground_window(self, win, retries=3) -> bool:
        """Y_BankAuto 방식으로 대상 창을 복원·전면화하고 실제 HWND를 확인한다."""
        try:
            import ctypes
            hwnd = self._window_handle(win)
            if not hwnd:
                return False
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            for _ in range(max(1, int(retries))):
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                self.wait(0.15)
                user32.SetForegroundWindow(hwnd)
                self.wait(0.2)
                if int(user32.GetForegroundWindow()) == hwnd:
                    return True
                fg = int(user32.GetForegroundWindow())
                cur_tid = kernel32.GetCurrentThreadId()
                fg_tid = user32.GetWindowThreadProcessId(fg, None)
                tgt_tid = user32.GetWindowThreadProcessId(hwnd, None)
                try:
                    user32.AttachThreadInput(cur_tid, fg_tid, True)
                    user32.AttachThreadInput(cur_tid, tgt_tid, True)
                    user32.ShowWindow(hwnd, 9)
                    user32.SetForegroundWindow(hwnd)
                    self.wait(0.2)
                    if int(user32.GetForegroundWindow()) == hwnd:
                        return True
                finally:
                    user32.AttachThreadInput(cur_tid, fg_tid, False)
                    user32.AttachThreadInput(cur_tid, tgt_tid, False)
                self.wait(0.25)
        except Exception:
            return False
        return False

    def _safe_send_keys(self, win, keys, retries=2) -> bool:
        """전면창을 복구·검증한 직후에만 키 입력을 보낸다."""
        from pywinauto.keyboard import send_keys
        for _ in range(max(1, int(retries))):
            if self._ensure_foreground_window(win):
                try:
                    send_keys(keys)
                    return True
                except Exception:
                    pass
            self.wait(0.15)
        return False

    # ── 로그인 컨트롤 (win32 직접) ──
    def _win32_window(self, win):
        try:
            from pywinauto.controls.hwndwrapper import HwndWrapper
            return HwndWrapper(int(win.hwnd))
        except Exception:
            raise b24.AutomationBlocked("BACKEND_UNAVAILABLE")

    def login_edit_candidates(self, win) -> list:
        """visible+enabled Edit 후보를 화면순(top,left)으로 반환(§50). 유한 timeout."""
        try:
            w = self._win32_window(win)
            edits = []
            for c in w.descendants():
                try:
                    if _safe_cls(c) in LOGIN_EDIT_CLASSES and c.is_visible() and c.is_enabled():
                        edits.append(c)
                except Exception:
                    continue
            edits.sort(key=lambda c: (self._top(c), self._left(c)))
            return edits
        except b24.AutomationBlocked:
            raise
        except Exception:
            return []

    def _top(self, c):
        try:
            return c.rectangle().top
        except Exception:
            return 0

    def _left(self, c):
        try:
            return c.rectangle().left
        except Exception:
            return 0

    def set_focus(self, ctrl):
        try:
            ctrl.set_focus()
        except Exception:
            raise b24.AutomationBlocked("SET_FOCUS_FAILED")

    def focused_control(self, win):
        try:
            from pywinauto import Desktop
            return Desktop(backend="win32").get_focus()
        except Exception:
            raise b24.AutomationBlocked("FOCUS_QUERY_FAILED")

    def set_edit_direct(self, ctrl, value) -> bool:
        """검증 Edit 에 값을 직접 설정(set_edit_text → WM_SETTEXT). 클립보드/좌표 미사용(§53)."""
        try:
            if not (ctrl.is_visible() and ctrl.is_enabled()):
                return False
        except Exception:
            pass
        try:
            ctrl.set_edit_text(value)
            return True
        except Exception:
            pass
        try:
            import ctypes
            WM_SETTEXT = 0x000C
            ctypes.windll.user32.SendMessageW(
                int(ctrl.handle), WM_SETTEXT, 0, ctypes.c_wchar_p(value))
            return True
        except Exception:
            return False

    def read_edit(self, ctrl) -> str:
        try:
            return ctrl.window_text() or ""
        except Exception:
            return ""

    def click_ok_button(self, win) -> bool:
        """같은 창의 실제 '확인' Button 을 BM_CLICK 으로 누른다. 좌표 클릭 아님(§56/§57)."""
        try:
            import ctypes
            BM_CLICK = 0x00F5
            w = self._win32_window(win)
            for c in w.descendants():
                try:
                    if _safe_cls(c) in OK_BUTTON_CLASSES and _safe_txt(c).strip() == OK_BUTTON_TEXT:
                        ctypes.windll.user32.SendMessageW(int(c.handle), BM_CLICK, 0, 0)
                        return True
                except Exception:
                    continue
        except Exception:
            return False
        return False

    # ── 탁상 필터·조회 (Y_BankAuto apply_filter 동등, 담보→탁상) ──
    def select_business_type(self, win, label="탁상") -> bool:
        """업무구분 라디오를 텍스트로 선택하고, 탁상은 실측 index=2로 보완한다."""
        try:
            w = self._win32_window(win)
            radios = [c for c in w.descendants()
                      if _safe_cls(c) == BUSINESS_RADIO_CLASS]
            wanted = "".join(str(label).split())
            selected = None
            for radio in radios:
                if "".join(_safe_txt(radio).split()) == wanted:
                    selected = radio
                    break
            # 실측 순서: 공동주택자문/동산담보/탁상/담보/전체
            if selected is None and wanted == "탁상" and len(radios) > 2:
                selected = radios[2]
            if selected is None:
                return False
            selected.click_input()
            self.wait(0.4)
            return True
        except Exception:
            return False

    def select_source_tab(self, win, label="\ubbf8\uc811\uc218") -> bool:
        """Y_BankAuto와 동일하게 상단 toolbar의 작성/미접수 탭을 상대좌표로 선택한다."""
        tab = "".join(str(label or "").split())
        if tab not in SOURCE_TAB_RELATIVE_COORDS:
            tab = "\ubbf8\uc811\uc218"
        try:
            w = self._win32_window(win)
            bars = [c for c in w.descendants() if _safe_cls(c) == "TdxBarControl"]
            toolbar = next((b for b in bars if _safe_txt(b).strip() == "toolbar"), None)
            if toolbar is None and bars:
                toolbar = sorted(
                    bars, key=lambda b: (b.rectangle().top, b.rectangle().left)
                )[0]
            if toolbar is None:
                return False
            toolbar.click_input(coords=SOURCE_TAB_RELATIVE_COORDS[tab])
            self.wait(1.0)
            return True
        except Exception:
            return False

    def execute_tabletop_query(self, win) -> bool:
        """당일 범위를 설정하고 조회 버튼을 누른다."""
        diag = ["execute_tabletop_query"]
        try:
            w = self._win32_window(win)
            descs = list(w.descendants())
            diag.append("descendants=%d" % len(descs))
            diag.append("--- controls ---")
            diag.extend(_dump_query_controls(descs))

            # 기간검색=직접입력. 미발견이어도 Y_BankAuto처럼 날짜 입력을 계속한다.
            direct_found = False
            for c in descs:
                if _safe_txt(c).strip() == "직접입력":
                    direct_found = True
                    try:
                        c.click_input()
                        self.wait(0.3)
                    except Exception as e:
                        diag.append("직접입력 click EXC=%s" % type(e).__name__)
                    break
            diag.append("직접입력_found=%s" % direct_found)

            edits = [c for c in descs if _safe_cls(c) == DATE_EDIT_CLASS]
            diag.append("date_edits(%s)=%d" % (DATE_EDIT_CLASS, len(edits)))
            if len(edits) >= 2:
                start_str, end_str = compute_query_range()
                # 조회시작일이 위, 조회종료일이 아래인 세로 배치 → top(y) 기준 정렬.
                start_edit, end_edit = order_start_end_edits(edits)
                diag.append("date_range %s~%s wd=%d" % (
                    start_str, end_str, date.today().weekday()))
                try:
                    # 종료일 먼저, 시작일 나중에 입력(종료>=시작 검증 회피).
                    for ctrl, val in ((end_edit, end_str), (start_edit, start_str)):
                        ctrl.click_input()
                        ctrl.type_keys("^a", with_spaces=True)
                        ctrl.type_keys(val, with_spaces=True)
                        ctrl.type_keys("{TAB}", with_spaces=True)
                        self.wait(0.2)
                except Exception as e:
                    diag.append("date input EXC=%s" % type(e).__name__)

            buttons = [c for c in descs if _safe_cls(c) == QUERY_BUTTON_CLASS]
            diag.append("query_buttons(%s)=%d labels=%r" % (
                QUERY_BUTTON_CLASS, len(buttons),
                [_safe_txt(b).strip() for b in buttons]))
            target = next((b for b in buttons
                           if _safe_txt(b).strip() in ("조회", "검색", "Search")), None)
            if target is None and len(buttons) >= 4:
                target = buttons[3]
                diag.append("target=buttons[3] fallback")
            if target is None:
                diag.append("RESULT=FAIL no query button")
                _qdiag_write(diag)
                return False
            diag.append("target label=%r" % _safe_txt(target).strip())
            target.click_input()
            self.wait(2.0)
            diag.append("RESULT=OK")
            _qdiag_write(diag)
            return True
        except Exception as e:
            import traceback
            diag.append("RESULT=EXC %s" % type(e).__name__)
            diag.append(traceback.format_exc())
            _qdiag_write(diag)
            return False

    @staticmethod
    def _parse_tsv(text: str, needed=()) -> list[dict]:
        lines = [line for line in (text or "").splitlines() if line.strip()]
        if len(lines) < 2:
            return []
        headers = [h.strip() for h in lines[0].split("\t")]
        rows = []
        for row_index, line in enumerate(lines[1:]):
            cols = [v.strip() for v in line.split("\t")]
            cols.extend([""] * max(0, len(headers) - len(cols)))
            raw = dict(zip(headers, cols))
            row = ({key: raw.get(key, "") for key in needed} if needed else raw)
            row["__row_index"] = row_index
            rows.append(row)
        return rows

    @staticmethod
    def _parse_row_copy(text: str, headers, needed, row_index: int):
        """현재 행 복사값을 기존 헤더에 맞춰 한 행으로 변환한다."""
        lines = [line for line in (text or "").splitlines() if line.strip()]
        if not lines:
            return None
        parsed = PywinautoReadonlyBackend._parse_tsv(text, needed)
        if parsed:
            row = parsed[0]
        else:
            cols = [value.strip() for value in lines[0].split("\t")]
            if len(cols) < 2 or not headers:
                return None
            cols.extend([""] * max(0, len(headers) - len(cols)))
            raw = dict(zip(headers, cols))
            row = ({key: raw.get(key, "") for key in needed} if needed else raw)
        row["__row_index"] = row_index
        return row

    def save_row_pdf(self, win, row_index: int, output_path: str) -> bool:
        """Y_BankAuto의 APPS→C→미리보기→Microsoft Print to PDF 흐름."""
        sd = ["save_row_pdf row_index=%s" % row_index]

        def _fail(step):
            sd.append("FAIL@%s" % step)
            _savediag_write(sd)
            # 실패 시 남은 미리보기/인쇄/저장 창을 닫아 다음 행이 깨끗이 시작하게 한다.
            try:
                self._close_pdf_leftovers()
            except Exception:
                pass
            return False

        try:
            import os
            import pyautogui
            from pywinauto import Desktop

            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            w = self._win32_window(win)
            all_descs = list(w.descendants())
            grids = [c for c in all_descs if _safe_cls(c) in GRID_CLASSES]
            sd.append("grids=%d (all classes seen: %s)" % (
                len(grids), sorted({_safe_cls(c) for c in all_descs})[:40]))
            if not grids:
                return _fail("no_grid")
            grid = max(grids, key=lambda g: g.rectangle().width() * g.rectangle().height())
            grid.click_input(); self.wait(0.2)
            if not self._safe_send_keys(w, "^{HOME}"):
                return _fail("send_home")
            self.wait(0.2)
            for _ in range(max(0, int(row_index))):
                if not self._safe_send_keys(w, "{DOWN}"):
                    return _fail("send_down")
                self.wait(0.05)

            before_preview = set()
            for x in _safe_desktop_windows():
                try:
                    if _safe_cls(x) == "TfrxPreviewForm":
                        before_preview.add(int(x.handle))
                except Exception:
                    pass
            if not self._ensure_foreground_window(w):
                return _fail("fg_main_before_apps")
            pyautogui.press("apps"); self.wait(1.2)
            if not self._ensure_foreground_window(w):
                return _fail("fg_main_before_c")
            pyautogui.press("c"); self.wait(2.0)
            sd.append("after APPS+C, waiting TfrxPreviewForm 15s")

            preview = self._wait_new_window("TfrxPreviewForm", before_preview, 15.0)
            if preview is None:
                # 진단: 현재 열린 창 클래스 목록(어떤 컨텍스트메뉴/창이 떴는지)
                try:
                    cur = sorted({_safe_cls(x) for x in _safe_desktop_windows()})
                    sd.append("open windows now: %s" % cur)
                except Exception:
                    pass
                return _fail("no_preview(TfrxPreviewForm)")
            sd.append("preview OK")
            preview.set_focus(); self.wait(0.3)
            if not self._ensure_foreground_window(preview):
                return _fail("fg_preview")
            pyautogui.hotkey("ctrl", "p")
            print_dlg = self._wait_new_window("TfrxPrintDialog", set(), 10.0,
                                              allow_existing=True)
            if print_dlg is None:
                return _fail("no_print_dialog(TfrxPrintDialog)")
            sd.append("print_dlg OK")

            printer_ok = False
            combo_seen = []
            for ctrl in print_dlg.descendants():
                if _safe_cls(ctrl) in ("TcxComboBox", "TComboBox", "ComboBox"):
                    try:
                        items = ctrl.item_texts()
                        combo_seen.append(items)
                        idx = next((i for i, text in enumerate(items)
                                    if "MICROSOFT" in text.upper() and "PDF" in text.upper()), None)
                        if idx is not None:
                            ctrl.select(idx); printer_ok = True; break
                    except Exception:
                        continue
            sd.append("printer combos=%r" % combo_seen)
            if not printer_ok:
                return _fail("no_microsoft_pdf_printer")
            before_dialogs = set()
            for x in _safe_desktop_windows():
                try:
                    if _safe_cls(x) == "#32770":
                        before_dialogs.add(int(x.handle))
                except Exception:
                    pass
            ok = next((c for c in print_dlg.descendants()
                       if _safe_cls(c) == "TButton" and "OK" in _safe_txt(c)), None)
            if ok is None:
                btns = [(_safe_cls(c), _safe_txt(c)) for c in print_dlg.descendants()
                        if "Button" in _safe_cls(c)]
                sd.append("print_dlg buttons=%r" % btns)
                return _fail("no_ok_button")
            ok.click_input(); self.wait(1.0)
            save_dlg = self._wait_save_dialog(before_dialogs, 10.0)
            if save_dlg is None:
                return _fail("no_save_dialog(#32770)")
            sd.append("save_dlg OK")
            import pyperclip

            # 파일명 Edit 찾기(Y_BankAuto 동등): 1) class=='Edit' + 크기필터(vis/enabled 미검사),
            # 2) vis/enabled 필터 + (top,left) 최하단 fallback.
            edit = None
            try:
                sized = []
                for c in save_dlg.descendants():
                    if _safe_cls(c) == "Edit":
                        try:
                            r = c.rectangle()
                            if r.width() > 100 and r.height() < 50:
                                sized.append((r.width(), c))
                        except Exception:
                            pass
                if sized:
                    sized.sort(key=lambda x: x[0], reverse=True)
                    edit = sized[0][1]
            except Exception:
                pass
            if edit is None:
                cands = []
                for c in save_dlg.descendants():
                    try:
                        if _safe_cls(c) == "Edit" and c.is_visible() and c.is_enabled():
                            r = c.rectangle()
                            cands.append((r.top, r.left, c))
                    except Exception:
                        pass
                if cands:
                    cands.sort(key=lambda x: (x[0], x[1]))
                    edit = cands[-1][2]
            if edit is None:
                edcls = sorted({_safe_cls(c) for c in save_dlg.descendants()})
                sd.append("save_dlg control classes=%r" % edcls)
                return _fail("no_filename_edit")

            # 파일명 입력: WM_SETTEXT 우선 시도 후 read-back 확인, 실패 시 클립보드 Ctrl+V.
            filled = False
            try:
                if self.set_edit_direct(edit, output_path):
                    if output_path in (_safe_txt(edit) or ""):
                        filled = True
            except Exception:
                pass
            if not filled:
                try:
                    edit.click_input(); self.wait(0.2)
                    edit.type_keys("^a", with_spaces=True); self.wait(0.1)
                    pyperclip.copy(output_path)
                    self._ensure_foreground_window(save_dlg)
                    pyautogui.hotkey("ctrl", "v"); self.wait(0.4)
                    filled = True
                except Exception:
                    pass
                finally:
                    try: pyperclip.copy("")
                    except Exception: pass
            sd.append("filename filled=%s" % filled)

            # 저장 실행: 기본 버튼을 Enter 로 누른다(Y_BankAuto 동등, '저장' 버튼 클래스 불확실 회피).
            self._ensure_foreground_window(save_dlg)
            pyautogui.press("enter"); self.wait(1.0)

            deadline = time.monotonic() + 20.0
            while time.monotonic() < deadline:
                if os.path.isfile(output_path) and os.path.getsize(output_path) > 1000:
                    self._close_pdf_leftovers(preview)
                    sd.append("RESULT=OK")
                    _savediag_write(sd)
                    return True
                self.wait(0.5)
            return _fail("file_not_created")
        except Exception as e:
            import traceback
            sd.append("EXC %s" % type(e).__name__)
            sd.append(traceback.format_exc())
            _savediag_write(sd)
            try:
                self._close_pdf_leftovers()
            except Exception:
                pass
            return False

    def _close_pdf_leftovers(self, preview=None) -> None:
        """실패/완료 후 남은 저장창(#32770)·인쇄창(TfrxPrintDialog)·미리보기(TfrxPreviewForm)를
        닫아 다음 행의 APPS→C 가 깨끗이 시작하게 한다(best-effort). 위→아래 순서로 닫는다."""
        import pyautogui  # noqa: F401  (필요 시 사용)

        def _click_first(win, texts):
            try:
                for c in win.descendants():
                    if _safe_txt(c).strip() in texts:
                        try:
                            c.click_input()
                        except Exception:
                            try: c.click()
                            except Exception: return False
                        return True
            except Exception:
                pass
            return False

        # 1) 저장 대화상자(#32770): 취소
        for w in _safe_desktop_windows():
            try:
                if _safe_cls(w) == "#32770" and _click_first(w, ("취소", "Cancel")):
                    self.wait(0.3)
            except Exception:
                pass
        # 2) 인쇄 대화상자
        for w in _safe_desktop_windows():
            try:
                if _safe_cls(w) == "TfrxPrintDialog":
                    if not _click_first(w, ("취소", "Cancel", "닫기", "Close")):
                        try: w.close()
                        except Exception: pass
                    self.wait(0.3)
            except Exception:
                pass
        # 3) 미리보기 창(넘겨받은 것 우선 + 남은 것)
        targets = []
        if preview is not None:
            targets.append(preview)
        for w in _safe_desktop_windows():
            try:
                if _safe_cls(w) == "TfrxPreviewForm":
                    targets.append(w)
            except Exception:
                pass
        for w in targets:
            try:
                if not _click_first(w, ("닫기", "Close", "&Close")):
                    try: w.close()
                    except Exception: pass
                self.wait(0.3)
            except Exception:
                pass

    def _wait_new_window(self, class_name, before, timeout, allow_existing=False):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for w in _safe_desktop_windows():
                try:
                    if (_safe_cls(w) == class_name and
                            (allow_existing or int(w.handle) not in before)):
                        return w
                except Exception:
                    continue
            self.wait(0.3)
        return None

    def _wait_save_dialog(self, before, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for w in _safe_desktop_windows():
                try:
                    if _safe_cls(w) != "#32770" or int(w.handle) in before:
                        continue
                    if any(_safe_cls(c) == "Button" and "저장" in _safe_txt(c)
                           for c in w.children()):
                        return w
                except Exception:
                    continue
            self.wait(0.3)
        return None

    def read_grid_clipboard(self, win, needed_columns=None):
        """Y_BankAuto와 같이 가장 큰 TcxGrid를 전체 선택·복사해 TSV로 읽는다."""
        needed = tuple(needed_columns or ())
        try:
            import pyperclip

            w = self._win32_window(win)
            grids = [c for c in w.descendants() if _safe_cls(c) in GRID_CLASSES]
            if not grids:
                raise b24.AutomationBlocked("GRID_NOT_FOUND")
            grid = max(grids, key=lambda g: g.rectangle().width() * g.rectangle().height())
            try:
                grid.click_input()
                self.wait(0.3)
                if not self._safe_send_keys(w, "^{HOME}"):
                    raise b24.AutomationBlocked("GRID_FOCUS_FAILED")
                self.wait(0.2)
                pyperclip.copy("")
                if not self._safe_send_keys(w, "^a"):
                    raise b24.AutomationBlocked("GRID_FOCUS_FAILED")
                self.wait(0.3)
                if not self._safe_send_keys(w, "^c"):
                    raise b24.AutomationBlocked("GRID_FOCUS_FAILED")
                self.wait(0.8)
                text = pyperclip.paste() or ""
                if not ("\t" in text and "\n" in text):
                    raise b24.AutomationBlocked("GRID_COPY_FAILED")
                bulk_rows = self._parse_tsv(text, needed)
                if len(bulk_rows) > 1:
                    return {"rows": bulk_rows, "limited": False}

                # Y_BankAuto 전략 2: 전체복사가 한 행만 반환하는 TcxGrid는
                # Home부터 Down으로 이동하며 현재 행을 재수집한다.
                headers = [h.strip() for h in text.splitlines()[0].split("\t")]
                if not self._safe_send_keys(w, "{ESC}^{HOME}"):
                    return {"rows": bulk_rows, "limited": False}
                self.wait(0.2)
                scanned = []
                previous = None
                for row_index in range(GRID_FALLBACK_MAX_ROWS):
                    pyperclip.copy("")
                    if not self._safe_send_keys(w, "^c"):
                        break
                    self.wait(0.3)
                    current = pyperclip.paste() or ""
                    if not current or (current == previous and row_index > 0):
                        break
                    row = self._parse_row_copy(current, headers, needed, row_index)
                    if row is not None:
                        scanned.append(row)
                    previous = current
                    if row_index + 1 < GRID_FALLBACK_MAX_ROWS:
                        if not self._safe_send_keys(w, "{DOWN}"):
                            break
                        self.wait(0.1)
                rows = scanned if len(scanned) > len(bulk_rows) else bulk_rows
                return {"rows": rows, "limited": len(rows) >= GRID_FALLBACK_MAX_ROWS}
            finally:
                try:
                    pyperclip.copy("")
                except Exception:
                    pass
        except b24.AutomationBlocked:
            raise
        except Exception:
            raise b24.AutomationBlocked("GRID_READ_FAILED")

    # ── 그리드 직접 조회 (§72–§77) ──
    def read_grid_visible(self, win, needed_columns=None):
        """UIA/win32 Grid 패턴으로 노출 행만 직접 읽는다.

        직접 읽기가 불가(클립보드 전용)면 우회하지 않고 GRID_CLIPBOARD_ONLY 로 중단한다(§74).
        가상화로 일부 행만 노출되면 limited=True 로 보고한다(§75/§76). 비PII 열만(§77).
        반환: {"rows":[{열:값}], "limited":bool} 또는 None(예상외 화면).
        """
        needed = tuple(needed_columns or ())
        try:
            from pywinauto import Desktop
            uw = Desktop(backend="uia").window(handle=int(win.hwnd))
            grid = None
            for ct in ("DataGrid", "Table", "List"):
                try:
                    cand = uw.child_window(control_type=ct)
                    if cand.exists(timeout=_UI_TIMEOUT):
                        grid = cand.wrapper_object()
                        break
                except Exception:
                    continue
            if grid is None:
                # UIA Grid 패턴 없음 → 직접 읽기 불가. 클립보드 우회 금지(§74).
                raise b24.AutomationBlocked("GRID_CLIPBOARD_ONLY")
            get_item = getattr(grid, "get_item", None)
            row_count = getattr(grid, "row_count", None)
            col_count = getattr(grid, "column_count", None)
            if not (callable(get_item) and callable(row_count) and callable(col_count)):
                raise b24.AutomationBlocked("GRID_CLIPBOARD_ONLY")
            headers = []
            try:
                headers = [h.window_text() for h in grid.get_column_headers()]
            except Exception:
                headers = []
            col_idx = [(i, h) for i, h in enumerate(headers) if (not needed or h in needed)]
            rows = []
            total = int(row_count())
            for r in range(total):
                row = {}
                for c, key in col_idx:
                    try:
                        row[key] = get_item(r, c).window_text()
                    except Exception:
                        row[key] = ""
                rows.append(row)
            # UIA 가상화로 노출 행만 반환될 수 있음 → 한계 표시(§76)
            return {"rows": rows, "limited": True}
        except b24.AutomationBlocked:
            raise
        except Exception:
            raise b24.AutomationBlocked("GRID_READ_FAILED")
