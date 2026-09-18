# -*- coding: utf-8 -*-
"""bank24_login_flow 이식 검증 (mock). 실제 Bank24/프로세스/UI 를 실행하지 않는다.

Y_BankAuto(extract_shinhan.py) 의 실제 순서/ fallback 과 동일한지 합성 창·컨트롤·
winapi·pyautogui·클립보드로 검증한다. 실제 ID/PW·서버·PII 값은 사용/출력하지 않으며
합성 토큰만 쓴다.
"""
import unittest

import bank24_login_flow as F

# 합성 자격증명(실값 아님)
SYN_ID = "SYNTH_ID_0001"
SYN_PW = "SYNTH_PW_!x9Q"


# ───────────────────────────── 합성 인프라 ─────────────────────────────
class FakeRect:
    def __init__(self, left, top, right, bottom):
        self.left, self.top, self.right, self.bottom = left, top, right, bottom


class FakeCtrl:
    """Edit/Button 등 컨트롤. 클래스/텍스트/가시성/직접입력/read-back 을 흉내낸다."""

    def __init__(self, cls, *, hwnd=0, text="", visible=True, enabled=True,
                 rect=(0, 0, 10, 10), set_edit_ok=True, raises_status=False):
        self._cls = cls
        self.handle = hwnd
        self._text = text
        self._visible = visible
        self._enabled = enabled
        self._rect = FakeRect(*rect)
        self._set_edit_ok = set_edit_ok
        self._raises_status = raises_status
        self.click_calls = 0
        self.set_focus_calls = 0

    def class_name(self):
        return self._cls

    def window_text(self):
        return self._text

    def texts(self):
        return [self._text]

    def is_visible(self):
        if self._raises_status:
            raise RuntimeError("status query fails")
        return self._visible

    def is_enabled(self):
        if self._raises_status:
            raise RuntimeError("status query fails")
        return self._enabled

    def rectangle(self):
        return self._rect

    def set_focus(self):
        self.set_focus_calls += 1

    def set_edit_text(self, value):
        if not self._set_edit_ok:
            raise RuntimeError("set_edit_text refused")
        self._text = value

    def click(self):
        self.click_calls += 1


class FakeWindow:
    def __init__(self, cls, *, hwnd, title="", visible=True, enabled=True,
                 rect=(0, 0, 300, 200), children=None, handle_raises=False,
                 descendants_block=None):
        self._cls = cls
        self._hwnd = hwnd
        self._title = title
        self._visible = visible
        self._enabled = enabled
        self._rect = FakeRect(*rect)
        self._children = list(children or [])
        self._handle_raises = handle_raises
        self._descendants_block = descendants_block  # threading.Event 또는 None
        self.set_focus_calls = 0

    @property
    def handle(self):
        if self._handle_raises:
            raise RuntimeError("handle query fails")
        return self._hwnd

    def class_name(self):
        return self._cls

    def window_text(self):
        return self._title

    def is_visible(self):
        return self._visible

    def is_enabled(self):
        return self._enabled

    def rectangle(self):
        return self._rect

    def set_focus(self):
        self.set_focus_calls += 1

    def descendants(self):
        if self._descendants_block is not None:
            # 지정된 시간까지 block → _timed_descendants 타임아웃 유도
            self._descendants_block.wait(5.0)
        return list(self._children)


class FakeStop:
    def __init__(self, stopped=False, stop_after=None):
        self._stopped = stopped
        self._n = 0
        self._stop_after = stop_after   # N회 조회 후 True

    def is_stopped(self):
        self._n += 1
        if self._stop_after is not None and self._n > self._stop_after:
            return True
        return self._stopped

    def force(self):
        self._stopped = True


class FakeClock:
    """단조 증가 시계. step 만큼 매 조회 증가."""

    def __init__(self, step=0.1):
        self._t = 0.0
        self._step = step

    def time(self):
        v = self._t
        self._t += self._step
        return v


class FakeWinAPI:
    """user32/kernel32 대체. 값/HWND 를 저장만 하고 로그하지 않는다."""

    def __init__(self, *, foreground_hwnd=0, succeed_on_first=True):
        self._fg = foreground_hwnd
        self._succeed_first = succeed_on_first
        self.calls = []
        self.text_calls = []
        self.attach_calls = []
        self._sfw_count = 0

    def show_window(self, hwnd, cmd):
        self.calls.append(("show_window", hwnd, cmd))

    def set_foreground(self, hwnd):
        self._sfw_count += 1
        self.calls.append(("set_foreground", hwnd))
        # 1차 실패 유도 옵션: 2번째(Attach 이후) 호출부터 성공
        if self._succeed_first or self._sfw_count >= 2:
            self._fg = hwnd

    def get_foreground(self):
        return self._fg

    def get_current_thread_id(self):
        return 111

    def get_window_thread(self, hwnd):
        return 200 + (hwnd or 0)

    def attach_thread_input(self, a, b, attach):
        self.attach_calls.append((a, b, bool(attach)))

    def send_message(self, hwnd, msg, wparam, lparam):
        self.calls.append(("send_message", hwnd, msg, wparam, lparam))
        return 1

    def send_message_text(self, hwnd, msg, wparam, text):
        self.text_calls.append((hwnd, msg, wparam, text))
        return 1


class FakePyAutoGui:
    def __init__(self):
        self.events = []

    def click(self, x, y):
        self.events.append(("click", x, y))

    def hotkey(self, *keys):
        self.events.append(("hotkey",) + keys)

    def typewrite(self, text, interval=0.0):
        self.events.append(("typewrite", text, interval))

    def press(self, key):
        self.events.append(("press", key))


class FakeCred:
    def __init__(self, uid=SYN_ID, pw=SYN_PW):
        self.username = uid
        self._pw = pw
        self.wiped = False

    def use_password(self):
        return self._pw

    def wipe(self):
        self.wiped = True
        self.username = ""
        self._pw = ""


class FakeEnv(F.LoginEnv):
    """LoginEnv 를 합성 창 목록/시계/winapi/pyautogui/클립보드로 대체."""

    def __init__(self, *, window_batches=None, windows_list=None, stop=None,
                 credential=None, winapi=None, clock=None, popen_raises=False):
        self.logs = []
        super().__init__(stop=stop or FakeStop(),
                         credential_provider=(lambda: credential),
                         log=self.logs.append)
        # window_batches: 각 windows() 호출마다 반환할 리스트의 목록(폴링 시뮬레이션)
        self._batches = list(window_batches) if window_batches is not None else None
        self._static = windows_list
        self._batch_i = 0
        self.windows_calls = 0
        self._clock = clock or FakeClock()
        self.winapi = winapi or FakeWinAPI()
        self._pg = FakePyAutoGui()
        self.clipboard = []
        self.popen_calls = 0
        self._popen_raises = popen_raises
        self.sleeps = []
        self.windows_raise_once = False

    def windows(self):
        self.windows_calls += 1
        if self.windows_raise_once:
            self.windows_raise_once = False
            raise RuntimeError("enum fails this round")
        if self._batches is not None:
            if self._batch_i < len(self._batches):
                b = self._batches[self._batch_i]
            else:
                b = self._batches[-1]
            self._batch_i += 1
            if isinstance(b, Exception):
                raise b
            return list(b)
        return list(self._static or [])

    def time(self):
        return self._clock.time()

    def sleep(self, seconds):
        self.sleeps.append(seconds)

    def popen(self, path):
        self.popen_calls += 1
        if self._popen_raises:
            raise OSError("launch fails")

    def pyautogui(self):
        return self._pg

    def clipboard_copy(self, text):
        self.clipboard.append(text)


def _login_dialog(hwnd=100, *, edits=2, ok=True, id_hwnd=11, pw_hwnd=12,
                  set_edit_ok=True, visible=True, enabled=True,
                  id_cls="Edit", pw_cls="Edit", extra=None):
    children = []
    # PW 는 위에서 아래로 두 번째가 되도록 top 을 더 크게
    id_ctrl = FakeCtrl(id_cls, hwnd=id_hwnd, text="", rect=(10, 10, 100, 30),
                       set_edit_ok=set_edit_ok, visible=visible, enabled=enabled)
    pw_ctrl = FakeCtrl(pw_cls, hwnd=pw_hwnd, text="", rect=(10, 40, 100, 60),
                       set_edit_ok=set_edit_ok, visible=visible, enabled=enabled)
    if edits >= 1:
        children.append(id_ctrl)
    if edits >= 2:
        children.append(pw_ctrl)
    if ok:
        children.append(FakeCtrl("TButton", hwnd=99, text="확인"))
    if extra:
        children.extend(extra)
    win = FakeWindow("TDXLoginDialog", hwnd=hwnd, title="BANK ONLINE",
                     children=children)
    win.id_ctrl = id_ctrl
    win.pw_ctrl = pw_ctrl
    return win


def _main_window(hwnd=500, title="BANK24 금융기관"):
    return FakeWindow("TfrmMain", hwnd=hwnd, title=title)


# ───────────────────────────── 테스트 ─────────────────────────────
class TestConstants(unittest.TestCase):
    def test_full_edit_classes_8(self):          # §12/§135 전체 8개
        self.assertEqual(len(F._LOGIN_EDIT_CLS), 8)

    def test_find_login_limited_edit_classes_4(self):  # §13/§135 제한 4개
        self.assertEqual(F._FIND_LOGIN_EDIT_CLS,
                         ("Edit", "TEdit", "TMaskEdit", "TcxCustomDropDownInnerEdit"))

    def test_app_path_and_main_cls(self):        # §4/§5
        self.assertEqual(F.APP_PATH, r"C:\KADC\X11\Bank24.exe")
        self.assertEqual(F.MAIN_CLS, "TfrmMain")

    def test_title_hints(self):                  # §115
        self.assertEqual(F._BANK24_TITLE_HINTS,
                         ("BANK24", "KADC_LOADER", "금융기관", "BANK ONLINE", "X11"))


class TestExistingMainReuse(unittest.TestCase):
    def test_reuse_scan_raw_substring(self):     # §23/§24 Desktop 스캔, raw 포함
        main = _main_window(title="X11 BANK ONLINE")
        env = FakeEnv(windows_list=[main], stop=FakeStop(), credential=FakeCred())
        found = F._find_existing_main(env)
        self.assertIs(found, main)

    def test_reuse_no_upper_conversion(self):    # §24 raw 비교(소문자는 매칭 안 됨)
        main = FakeWindow("TfrmMain", hwnd=1, title="bank24 loader")  # 소문자
        env = FakeEnv(windows_list=[main])
        self.assertIsNone(F._find_existing_main(env))

    def test_reuse_no_popen_no_credential(self):  # §25 Popen/credential 미호출
        main = _main_window()
        cred = FakeCred()
        env = FakeEnv(windows_list=[main], stop=FakeStop(), credential=cred)
        res = F.run_bank24_login(env)
        self.assertTrue(res.reused_main)
        self.assertEqual(env.popen_calls, 0)
        self.assertFalse(cred.wiped)             # provider 미호출 → cred 사용 안 함

    def test_reuse_foreground_then_1s(self):     # §25-1 전면화 후 1초 대기
        main = _main_window()
        env = FakeEnv(window_batches=[[main], [main]], stop=FakeStop(),
                      credential=FakeCred())
        F.run_bank24_login(env)
        self.assertIn(1, env.sleeps)             # 정확히 1초 대기 포함

    def test_reuse_still_calls_wait_main(self):  # §25-2/§135-2 공통 wait_main 호출
        main = _main_window()
        calls = {"n": 0}
        orig = F.wait_main

        def spy(env):
            calls["n"] += 1
            return orig(env)
        F.wait_main = spy
        try:
            env = FakeEnv(window_batches=[[main], [main]], stop=FakeStop(),
                          credential=FakeCred())
            res = F.run_bank24_login(env)
        finally:
            F.wait_main = orig
        self.assertEqual(calls["n"], 1)
        self.assertEqual(res.status, "done")


class TestExistingLoginAttach(unittest.TestCase):
    """이미 실행 중인 로그인창 attach(Popen 없이). Bank24 단일 인스턴스 대응."""

    def test_detect_known_login_cls(self):       # KNOWN_LOGIN_CLS visible+enabled 감지
        dlg = _login_dialog(hwnd=100)
        env = FakeEnv(windows_list=[dlg])
        self.assertIs(F._find_existing_login_window(env), dlg)

    def test_detect_invisible_tdx_not_matched(self):  # 비표시 TDX 는 감지 안 함
        dlg = FakeWindow("TDXLoginDialog", hwnd=100, title="BANK ONLINE",
                         visible=False)
        env = FakeEnv(windows_list=[dlg])
        self.assertIsNone(F._find_existing_login_window(env))

    def test_detect_title_plus_edits(self):      # 제목 매칭 + Edit>=2 감지(KNOWN 아님)
        edits = [FakeCtrl("Edit", hwnd=1, rect=(10, 10, 100, 30)),
                 FakeCtrl("Edit", hwnd=2, rect=(10, 40, 100, 60))]
        win = FakeWindow("TfrmX", hwnd=200, title="X11", children=edits)
        env = FakeEnv(windows_list=[win])
        self.assertIs(F._find_existing_login_window(env), win)

    def test_none_when_not_running(self):        # 무관한 창만 있으면 None(→ launch 진행)
        other = FakeWindow("Chrome_WidgetWin_1", hwnd=9, title="브라우저")
        env = FakeEnv(windows_list=[other])
        self.assertIsNone(F._find_existing_login_window(env))

    def test_title_without_enough_edits_none(self):  # 제목만 맞고 Edit<2 → None(오탐 방지)
        one = [FakeCtrl("Edit", hwnd=1, rect=(10, 10, 100, 30))]
        win = FakeWindow("TfrmX", hwnd=200, title="X11", children=one)
        env = FakeEnv(windows_list=[win])
        self.assertIsNone(F._find_existing_login_window(env))

    def test_attach_success_no_popen(self):      # attach 로 로그인 성공, Popen 미호출
        dlg = _login_dialog(hwnd=100)
        main = _main_window(hwnd=500)
        env = FakeEnv(window_batches=[[dlg]] * 4 + [[main]],
                      stop=FakeStop(), credential=FakeCred())
        res = F.run_bank24_login(env)
        self.assertEqual(res.status, "done")
        self.assertEqual(env.popen_calls, 0)         # 재실행 안 함
        self.assertTrue(res.diag.attached_existing_login)
        self.assertIn(F.Step.LOGIN_DONE, env.logs)

    def test_attach_does_not_kill_or_launch(self):   # 종료/실행 흔적 없음(§9)
        dlg = _login_dialog(hwnd=100)
        main = _main_window(hwnd=500)
        env = FakeEnv(window_batches=[[dlg]] * 4 + [[main]],
                      stop=FakeStop(), credential=FakeCred())
        F.run_bank24_login(env)
        self.assertEqual(env.popen_calls, 0)

    def test_existing_main_wins_over_login(self):    # 메인창 있으면 메인 재사용 우선
        main = _main_window(hwnd=500, title="BANK24 금융기관")
        dlg = _login_dialog(hwnd=100)
        env = FakeEnv(window_batches=[[main, dlg]] * 3, stop=FakeStop(),
                      credential=FakeCred())
        res = F.run_bank24_login(env)
        self.assertTrue(res.reused_main)
        self.assertEqual(env.popen_calls, 0)

    def test_attach_failure_reports_safe_diag(self):  # attach 실패 시 안전 진단(개수) 로그
        dlg = _login_dialog(hwnd=100, edits=0, ok=False)  # KNOWN 이라 감지되나 Edit 없음
        env = FakeEnv(windows_list=[dlg], stop=FakeStop(), credential=FakeCred())
        res = F.run_bank24_login(env)
        self.assertEqual(res.status, "submit_failed")
        self.assertTrue(res.diag.attached_existing_login)
        self.assertTrue(any(c.startswith("LOGIN_DETAIL_WINCOUNT_") for c in env.logs))
        self.assertIn("LOGIN_DETAIL_ATTACHED_EXISTING", env.logs)


class TestPollLoginWindow(unittest.TestCase):
    def test_tdx_priority_even_if_before(self):  # §33 TDX 는 before 무관 최우선
        dlg = _login_dialog(hwnd=100)
        before = {100}
        env = FakeEnv(windows_list=[dlg])
        win, _new = F._poll_login_window(env, before, F.LoginDiagnostics())
        self.assertIs(win, dlg)

    def test_title_edit_match(self):             # §36 title+Edit>=2
        w = _login_dialog(hwnd=101)
        w._cls = "TfrmX"                          # non-TDX, title 매칭 경로
        env = FakeEnv(windows_list=[w])
        win, _ = F._poll_login_window(env, set(), F.LoginDiagnostics())
        self.assertIs(win, w)

    def test_skip_cls_excluded_from_new(self):   # §34 SKIP_CLS 제외
        skip = FakeWindow("Shell_TrayWnd", hwnd=9, title="taskbar")
        env = FakeEnv(windows_list=[skip])
        _win, new = F._poll_login_window(env, set(), F.LoginDiagnostics())
        self.assertEqual(new, [])

    def test_per_window_exception_continues(self):  # §38-1 개별 창 예외는 건너뛰고 계속
        bad = FakeWindow("TfrmX", hwnd=1, title="x", handle_raises=True)
        good = _login_dialog(hwnd=100)
        env = FakeEnv(windows_list=[bad, good])
        win, _ = F._poll_login_window(env, set(), F.LoginDiagnostics())
        self.assertIs(win, good)

    def test_enum_exception_recovers_next_round(self):  # §38-2/§135-14 열거 예외 후 복구
        dlg = _login_dialog(hwnd=100)
        env = FakeEnv(window_batches=[RuntimeError("enum fail"), [dlg]])
        win, _ = F._poll_login_window(env, set(), F.LoginDiagnostics())
        self.assertIs(win, dlg)

    def test_fallback_find_login_win(self):      # §38 30초 미발견 → _find_login_win
        # title/edit 매칭 안 되지만 클래스 힌트 있는 창 → _find_login_win 이 후보 반환
        w = _login_dialog(hwnd=100)
        w._cls = "TDXsomething"
        w._title = "무제"
        env = FakeEnv(windows_list=[w], clock=FakeClock(step=20))  # 빠르게 30초 소진
        win, _ = F._poll_login_window(env, set(), F.LoginDiagnostics())
        self.assertIs(win, w)


class TestFindLoginWin(unittest.TestCase):
    def test_known_cls_immediate(self):          # §41 KNOWN 즉시 반환
        dlg = FakeWindow("TfrmLogin", hwnd=1, title="")
        env = FakeEnv(windows_list=[dlg])
        self.assertIs(F._find_login_win(env, set()), dlg)

    def test_limited_edit_class_count(self):     # §44 제한 4클래스, 순수 descendants
        # visible=False Edit 도 계수(§44 필터 없음)
        e1 = FakeCtrl("Edit", visible=False)
        e2 = FakeCtrl("TEdit", visible=False)
        w = FakeWindow("TBnkX", hwnd=2, title="", children=[e1, e2])
        env = FakeEnv(windows_list=[w])
        self.assertIs(F._find_login_win(env, set()), w)

    def test_excluded_edit_class_not_counted(self):  # 제한 4클래스 외(TcxTextEdit)는 §44 계수 제외
        e1 = FakeCtrl("TcxTextEdit")
        e2 = FakeCtrl("TcxTextEdit")
        w = FakeWindow("TBnkX", hwnd=2, title="", children=[e1, e2])
        env = FakeEnv(windows_list=[w])
        # Edit 2개 미만으로 간주 → 첫 후보 반환(§45)
        self.assertIs(F._find_login_win(env, set()), w)

    def test_none_when_no_candidate(self):       # §46
        w = FakeWindow("RandomCls", hwnd=3, title="nothing")
        env = FakeEnv(windows_list=[w])
        self.assertIsNone(F._find_login_win(env, set()))


class TestTimedDescendants(unittest.TestCase):
    def test_count_uses_3s_timeout(self):        # §135-3 3초 timeout 으로 daemon 제한
        seen = {}
        orig = F._timed_descendants

        def spy(win, cls_filter, timeout=F._DESCENDANTS_TIMEOUT):
            seen["timeout"] = timeout
            return orig(win, cls_filter, timeout=0.05)  # 테스트 속도용 축소
        F._timed_descendants = spy
        try:
            w = _login_dialog(hwnd=1)
            F._count_login_edit_candidates(w)
        finally:
            F._timed_descendants = orig
        self.assertEqual(seen["timeout"], 3.0)

    def test_timeout_uses_partial_results(self):  # §14-3/§135-4 타임아웃 시 부분 결과
        import threading
        ev = threading.Event()   # descendants 가 block → 타임아웃 유발
        w = FakeWindow("TDXLoginDialog", hwnd=1, title="",
                       children=[FakeCtrl("Edit")], descendants_block=ev)
        # 부분 결과(빈 리스트)라도 예외 없이 정수 반환
        n = F._timed_descendants(w, F._LOGIN_EDIT_CLS, timeout=0.05)
        ev.set()
        self.assertIsInstance(n, list)


class TestForceForeground(unittest.TestCase):
    def test_first_try_success(self):            # §47~§49
        api = FakeWinAPI(foreground_hwnd=0, succeed_on_first=True)
        env = FakeEnv(winapi=api)
        self.assertTrue(F.force_foreground(env, 42, "x"))
        self.assertNotIn(True, [c for c in api.attach_calls])  # attach 불필요

    def test_attach_fallback_and_detach(self):   # §50~§52/§135 AttachThreadInput + detach
        api = FakeWinAPI(foreground_hwnd=0, succeed_on_first=False)
        env = FakeEnv(winapi=api)
        ok = F.force_foreground(env, 42, "x")
        self.assertTrue(ok)
        # attach True 2회, detach False 2회(finally 보장)
        attaches = [a for a in api.attach_calls if a[2] is True]
        detaches = [a for a in api.attach_calls if a[2] is False]
        self.assertEqual(len(attaches), 2)
        self.assertEqual(len(detaches), 2)

    def test_failure_does_not_raise(self):       # §53 실패해도 예외 없이 False
        class DeadAPI(FakeWinAPI):
            def get_foreground(self):
                return 0   # 절대 일치 안 함
        env = FakeEnv(winapi=DeadAPI(foreground_hwnd=0, succeed_on_first=False))
        self.assertFalse(F.force_foreground(env, 42, "x"))


class TestLoginOkButton(unittest.TestCase):
    def test_ok_button_allows_extended_caption(self):
        dlg = _login_dialog(hwnd=100, ok=False, extra=[
            FakeCtrl("TButton", hwnd=99, text="\ud655\uc778 \ubc0f \uc2e4\ud589"),
        ])
        api = FakeWinAPI()
        env = FakeEnv(winapi=api)
        self.assertTrue(F._click_login_ok_button(env, dlg))
        self.assertTrue(any(c[0] == "send_message" and c[1] == 99 for c in api.calls))

    def test_ok_button_missing_falls_back_to_enter(self):
        dlg = _login_dialog(hwnd=100, ok=False)
        env = FakeEnv(winapi=FakeWinAPI())
        self.assertTrue(F._click_login_ok_button(env, dlg))
        self.assertIn(("press", "enter"), env._pg.events)


class TestDirectInput(unittest.TestCase):
    def test_3step_fallback_wm_settext(self):    # §64 set_edit_text 실패→WM_SETTEXT
        api = FakeWinAPI()
        env = FakeEnv(winapi=api)
        ctrl = FakeCtrl("Edit", hwnd=5, set_edit_ok=False)  # set_edit_text 실패
        self.assertTrue(F._set_edit_text_direct(env, ctrl, SYN_ID, "ID"))
        self.assertTrue(any(t[1] == F._WM_SETTEXT for t in api.text_calls))

    def test_inactive_control_returns_false(self):  # §65-2 비표시/비활성 → 즉시 False
        api = FakeWinAPI()
        env = FakeEnv(winapi=api)
        ctrl = FakeCtrl("Edit", hwnd=5, visible=False)
        self.assertFalse(F._set_edit_text_direct(env, ctrl, SYN_ID, "ID"))
        self.assertEqual(api.text_calls, [])     # fallback 진행 안 함

    def test_status_exception_continues(self):   # §65-3 상태조회 예외 → fallback 계속
        api = FakeWinAPI()
        env = FakeEnv(winapi=api)
        ctrl = FakeCtrl("Edit", hwnd=5, raises_status=True, set_edit_ok=True)
        self.assertTrue(F._set_edit_text_direct(env, ctrl, SYN_ID, "ID"))

    def test_pw_value_never_logged(self):        # §70 값 미로그
        api = FakeWinAPI()
        env = FakeEnv(winapi=api)
        ctrl = FakeCtrl("Edit", hwnd=5)
        F._set_edit_text_direct(env, ctrl, SYN_PW, "PW")
        self.assertNotIn(SYN_PW, "".join(env.logs))


class TestOkButton(unittest.TestCase):
    def test_bm_click_first(self):               # §76 BM_CLICK 우선
        api = FakeWinAPI()
        env = FakeEnv(winapi=api)
        win = _login_dialog(hwnd=100)
        self.assertTrue(F._click_login_ok_button(env, win))
        self.assertTrue(any(c[0] == "send_message" and c[2] == F._BM_CLICK
                            for c in api.calls))

    def test_click_fallback_when_bm_raises(self):  # §77 BM_CLICK 예외→button.click
        class BadAPI(FakeWinAPI):
            def send_message(self, *a):
                raise RuntimeError("bm_click fails")
        btn = FakeCtrl("TButton", hwnd=99, text="확인")
        win = FakeWindow("TDXLoginDialog", hwnd=100, title="", children=[btn])
        env = FakeEnv(winapi=BadAPI())
        self.assertTrue(F._click_login_ok_button(env, win))
        self.assertEqual(btn.click_calls, 1)


class TestAttempt1(unittest.TestCase):
    def test_force_foreground_then_input(self):  # §56/§62 전면화 후 ID/PW 입력
        dlg = _login_dialog(hwnd=100)
        env = FakeEnv(winapi=FakeWinAPI(succeed_on_first=True))
        diag = F.LoginDiagnostics()
        self.assertTrue(F._attempt1_direct(env, dlg, SYN_ID, SYN_PW, diag))
        self.assertEqual(dlg.id_ctrl._text, SYN_ID)
        self.assertEqual(dlg.pw_ctrl._text, SYN_PW)

    def test_top_left_sort(self):                # §59 (top,left) 정렬로 ID=위, PW=아래
        # PW 를 먼저 등록해도 top 정렬로 ID(top=10) 가 edits[0]
        dlg = _login_dialog(hwnd=100)
        dlg._children = [dlg.pw_ctrl, dlg.id_ctrl,
                         FakeCtrl("TButton", hwnd=99, text="확인")]
        env = FakeEnv(winapi=FakeWinAPI())
        diag = F.LoginDiagnostics()
        F._attempt1_direct(env, dlg, SYN_ID, SYN_PW, diag)
        self.assertEqual(dlg.id_ctrl._text, SYN_ID)  # 위쪽이 ID

    def test_id_fail_still_inputs_pw(self):      # §63 ID 성공 확인 전 PW 도 입력 시도
        calls = []
        orig = F._set_edit_text_direct

        def spy(env, ctrl, value, label):
            calls.append(label)
            return orig(env, ctrl, value, label)
        F._set_edit_text_direct = spy
        try:
            dlg = _login_dialog(hwnd=100)
            env = FakeEnv(winapi=FakeWinAPI())
            F._attempt1_direct(env, dlg, SYN_ID, SYN_PW, F.LoginDiagnostics())
        finally:
            F._set_edit_text_direct = orig
        self.assertEqual(calls, ["ID", "PW"])    # 둘 다 호출

    def test_edits_lt2_fails(self):              # §61 Edit 2개 미만 실패
        dlg = _login_dialog(hwnd=100, edits=1)
        env = FakeEnv(winapi=FakeWinAPI())
        diag = F.LoginDiagnostics()
        self.assertFalse(F._attempt1_direct(env, dlg, SYN_ID, SYN_PW, diag))
        self.assertEqual(diag.failure_reason, F._R_EDITS_LT2)

    def test_pw_readback_empty_unknown_ok_proceeds(self):  # §69/§135-10 PW 빈 read-back
        # PW read-back 이 빈 값(UNKNOWN)이어도 ID 검증 성공 시 확인 버튼 진행
        dlg = _login_dialog(hwnd=100)
        # pw_ctrl read-back 을 항상 빈 값으로
        dlg.pw_ctrl.window_text = lambda: ""
        dlg.pw_ctrl.texts = lambda: []
        env = FakeEnv(winapi=FakeWinAPI())
        diag = F.LoginDiagnostics()
        self.assertTrue(F._attempt1_direct(env, dlg, SYN_ID, SYN_PW, diag))

    def test_pw_length_mismatch_not_blocking(self):  # §69-2/§135-9 PW 길이불일치 비차단
        dlg = _login_dialog(hwnd=100)
        # PW read-back 길이를 다르게(FAIL) 만들어도 진행되어야 함
        dlg.pw_ctrl.window_text = lambda: "X"    # 길이 1 != len(SYN_PW)
        env = FakeEnv(winapi=FakeWinAPI())
        diag = F.LoginDiagnostics()
        self.assertTrue(F._attempt1_direct(env, dlg, SYN_ID, SYN_PW, diag))


class TestFallbackWindowSelect(unittest.TestCase):
    def test_stage1_tdx(self):                   # §84
        tdx = FakeWindow("TDXLoginDialog", hwnd=1, title="")
        other = FakeWindow("TfrmX", hwnd=2, title="")
        self.assertIs(F._select_login_fallback_window([other, tdx]), tdx)

    def test_stage2_most_edits(self):            # §85 Edit 최다
        w2 = FakeWindow("TfrmX", hwnd=2, title="",
                        children=[FakeCtrl("Edit"), FakeCtrl("Edit")])
        w3 = FakeWindow("TfrmY", hwnd=3, title="",
                        children=[FakeCtrl("Edit"), FakeCtrl("Edit"), FakeCtrl("Edit")])
        self.assertIs(F._select_login_fallback_window([w2, w3]), w3)

    def test_stage3_title(self):                 # §86 제목 매칭
        w = FakeWindow("TfrmX", hwnd=2, title="금융기관온라인")
        self.assertIs(F._select_login_fallback_window([w]), w)

    def test_stage4_min_area(self):              # §87 최소 면적
        big = FakeWindow("TfrmX", hwnd=2, title="", rect=(0, 0, 500, 500))
        small = FakeWindow("TfrmY", hwnd=3, title="", rect=(0, 0, 100, 100))
        self.assertIs(F._select_login_fallback_window([big, small]), small)

    def test_exclude_classes(self):              # §85~§87 TApplication/TProgressDlg 제외
        app = FakeWindow("TApplication", hwnd=2, title="금융기관온라인")
        self.assertIsNone(F._select_login_fallback_window([app]))


class TestAttempt2(unittest.TestCase):
    def test_2a_set_focus_then_input(self):      # §88 set_focus→입력
        dlg = _login_dialog(hwnd=100)
        env = FakeEnv(winapi=FakeWinAPI())
        diag = F.LoginDiagnostics()
        self.assertTrue(F._attempt2a_edit(env, dlg, SYN_ID, SYN_PW, diag))
        self.assertEqual(dlg.set_focus_calls, 1)
        self.assertIn(0.3, env.sleeps)

    def test_2a_to_2b_transition(self):          # §95 2-A 실패 → 2-B 조건 확인
        # Edit 는 있으나 set_edit_text 계속 실패 + WM 도 실패 유도 → 2-A 실패
        class NoSendAPI(FakeWinAPI):
            def send_message_text(self, *a):
                raise RuntimeError("no send")
        dlg = _login_dialog(hwnd=100, set_edit_ok=False)
        env = FakeEnv(winapi=NoSendAPI())
        diag = F.LoginDiagnostics()
        self.assertFalse(F._attempt2a_edit(env, dlg, SYN_ID, SYN_PW, diag))
        # 2-B 는 Edit 후보>=1 이면 실행됨
        self.assertGreaterEqual(F._count_login_edit_candidates(dlg), 1)

    def test_2b_no_edit_not_run(self):           # §96/§97 Edit 0개면 2-B 미실행
        dlg = FakeWindow("TDXLoginDialog", hwnd=100, title="", children=[])
        env = FakeEnv(winapi=FakeWinAPI())
        diag = F.LoginDiagnostics()
        self.assertFalse(F._attempt2b_coord(env, dlg, SYN_ID, SYN_PW, diag))
        self.assertEqual(diag.failure_reason, F._R_2B_NO_EDIT)
        self.assertEqual(env._pg.events, [])     # pyautogui 미사용

    def test_2b_coord_sequence_and_clipboard_clear(self):  # §99~§106 좌표·클립보드 finally 소거
        dlg = _login_dialog(hwnd=100)
        env = FakeEnv(winapi=FakeWinAPI())
        diag = F.LoginDiagnostics()
        self.assertTrue(F._attempt2b_coord(env, dlg, SYN_ID, SYN_PW, diag))
        # ID 좌표 클릭→typewrite→clipboard(pwd)→PW 클릭→ctrl+v→enter
        kinds = [e[0] for e in env._pg.events]
        self.assertEqual(kinds, ["click", "hotkey", "typewrite", "click",
                                 "hotkey", "hotkey", "press"])
        self.assertEqual(env.clipboard[-1], "")  # §106 finally 소거
        self.assertIn(SYN_PW, env.clipboard)     # 중간에 pwd copy 됨
        self.assertIn(F.COORD_CLIPBOARD_PW_EXPOSURE, env.logs)  # §107 위험 보고

    def test_2b_clipboard_cleared_on_exception(self):  # §106 예외 시에도 소거
        class BoomGui(FakePyAutoGui):
            def press(self, key):
                raise RuntimeError("boom")
        env = FakeEnv(winapi=FakeWinAPI())
        env._pg = BoomGui()
        dlg = _login_dialog(hwnd=100)
        diag = F.LoginDiagnostics()
        self.assertFalse(F._attempt2b_coord(env, dlg, SYN_ID, SYN_PW, diag))
        self.assertEqual(env.clipboard[-1], "")


class TestLaunchAndLogin(unittest.TestCase):
    def test_launch_failed_code(self):           # §30 실행 실패 안전코드
        env = FakeEnv(windows_list=[], stop=FakeStop(), credential=FakeCred(),
                      popen_raises=True)
        with self.assertRaises(F.Bank24LaunchFailed):
            F.launch_and_login(env)
        self.assertIn(F.BANK24_LAUNCH_FAILED, env.logs)

    def test_new_wins_empty_no_attempt2(self):   # §83 new_wins 비면 시도2 미실행
        # 로그인창도 신규창도 없음 → cred 있으나 login_win None, new_wins 비어 fallback 없음
        env = FakeEnv(window_batches=[[]], stop=FakeStop(), credential=FakeCred(),
                      clock=FakeClock(step=40))  # 30초 즉시 소진
        with self.assertRaises(F.LoginSubmitFailed) as ctx:
            F.launch_and_login(env)
        self.assertFalse(ctx.exception.diag.fallback_used)  # §83-2

    def test_submit_failed_diag_only_safe(self):  # §109-2/§135-15 진단에 HWND/제목/자격증명 없음
        env = FakeEnv(window_batches=[[]], stop=FakeStop(), credential=FakeCred(),
                      clock=FakeClock(step=40))
        try:
            F.launch_and_login(env)
        except F.LoginSubmitFailed as e:
            d = e.diag
            # 진단은 boolean/개수/코드만
            self.assertIsInstance(d.login_win_found, bool)
            self.assertIsInstance(d.new_wins_count, int)
            self.assertIsInstance(d.fallback_used, bool)
            self.assertIsInstance(d.edit_candidates_count, int)
        blob = "".join(env.logs)
        self.assertNotIn(SYN_ID, blob)
        self.assertNotIn(SYN_PW, blob)

    def test_credential_missing_fail_closed(self):  # §17/§48 cred None → fail-closed
        env = FakeEnv(windows_list=[_login_dialog(hwnd=100)], stop=FakeStop(),
                      credential=None)
        with self.assertRaises(F.LoginSubmitFailed) as ctx:
            F.launch_and_login(env)
        self.assertEqual(ctx.exception.diag.failure_reason, F._R_CRED_MISSING)

    def test_cred_wiped_after_attempt(self):     # §20/§21 시도 종료 후 cred wipe
        cred = FakeCred()
        env = FakeEnv(windows_list=[_login_dialog(hwnd=100)], stop=FakeStop(),
                      credential=cred, winapi=FakeWinAPI())
        F.launch_and_login(env)
        self.assertTrue(cred.wiped)

    def test_success_flow(self):                 # §55~§79 정상 로그인 전송 성공
        cred = FakeCred()
        env = FakeEnv(windows_list=[_login_dialog(hwnd=100)], stop=FakeStop(),
                      credential=cred, winapi=FakeWinAPI())
        diag = F.launch_and_login(env)
        self.assertTrue(diag.login_win_found)


class TestWaitMain(unittest.TestCase):
    def test_kadc_loader_main(self):             # §115/§116 KADC_LOADER 메인 창
        main = _main_window(title="KADC_LOADER")
        env = FakeEnv(windows_list=[main])
        self.assertIs(F.wait_main(env), main)

    def test_loading_candidate_then_timeout(self):  # §117/§124 90초 loading candidate 진행
        loading = _main_window(title="")         # 빈 제목 = loading candidate
        env = FakeEnv(windows_list=[loading], clock=FakeClock(step=30))  # 빠른 타임아웃
        self.assertIs(F.wait_main(env), loading)

    def test_timeout_no_candidate_none(self):    # §126 candidate 없으면 None
        junk = FakeWindow("OtherCls", hwnd=1, title="x")
        env = FakeEnv(windows_list=[junk], clock=FakeClock(step=30))
        self.assertIsNone(F.wait_main(env))
        self.assertIn(F.LOGIN_NOT_CONFIRMED, env.logs)

    def test_normal_title_foregrounds(self):     # §118/§119 정상 제목 전면화 후 반환
        api = FakeWinAPI(succeed_on_first=True)
        main = _main_window(title="BANK24")
        env = FakeEnv(windows_list=[main], winapi=api)
        self.assertIs(F.wait_main(env), main)
        self.assertTrue(any(c[0] == "set_foreground" for c in api.calls))


class TestCommonFlow(unittest.TestCase):
    def test_stop_after_login_skips_waitmain_and_tabletop(self):  # §112-1/§135-5
        proceeded = {"n": 0}
        called = {"wait": 0}
        orig = F.wait_main

        def spy(env):
            called["wait"] += 1
            return orig(env)
        F.wait_main = spy
        try:
            dlg = _login_dialog(hwnd=100)
            # 로그인 성공 후 중지되도록 stop_after: launch 중에는 안 멈추고 이후 멈춤
            stop = FakeStop(stop_after=100)       # launch 폴링 중엔 미정지
            env = FakeEnv(window_batches=[[dlg], [dlg]], stop=stop,
                          credential=FakeCred(), winapi=FakeWinAPI())
            stop._stop_after = 0                  # 이후 모든 is_stopped True
            res = F.run_bank24_login(env, proceed=lambda mw: proceeded.__setitem__("n", 1))
        finally:
            F.wait_main = orig
        self.assertEqual(res.status, "stopped")
        self.assertEqual(called["wait"], 0)      # wait_main 미호출
        self.assertEqual(proceeded["n"], 0)      # 탁상 이동 미호출

    def test_waitmain_none_error(self):          # §112-4/§135-7 wait_main None → error
        orig = F.wait_main
        F.wait_main = lambda env: None
        try:
            main = _main_window()
            env = FakeEnv(windows_list=[main], stop=FakeStop(), credential=FakeCred())
            # 기존 메인 재사용 경로로 진입(존재) → wait_main None → error
            res = F.run_bank24_login(env)
        finally:
            F.wait_main = orig
        self.assertEqual(res.status, "error")

    def test_2s_stabilize_then_done(self):       # §112-5/§135-6 2초 안정화 후 done
        main = _main_window()
        env = FakeEnv(window_batches=[[main], [main]], stop=FakeStop(),
                      credential=FakeCred())
        res = F.run_bank24_login(env)
        self.assertEqual(res.status, "done")
        self.assertIn(2, env.sleeps)             # 2초 대기
        self.assertIn(F.Step.LOGIN_DONE, env.logs)

    def test_stop_during_2s_skips_tabletop(self):  # §112-6/§135-8 2초 중 중지→탁상 미호출
        proceeded = {"n": 0}
        main = _main_window()
        stop = FakeStop(stop_after=1)            # 첫 stop 확인은 통과, 2초 후 확인은 정지
        env = FakeEnv(window_batches=[[main], [main]], stop=stop,
                      credential=FakeCred())
        res = F.run_bank24_login(env, proceed=lambda mw: proceeded.__setitem__("n", 1))
        self.assertEqual(res.status, "stopped")
        self.assertEqual(proceeded["n"], 0)

    def test_no_auto_retry(self):                # §108 자동 재시도 없음
        # 로그인 전송 실패 시 launch_and_login 은 1회만 popen 후 예외
        env = FakeEnv(window_batches=[[]], stop=FakeStop(), credential=FakeCred(),
                      clock=FakeClock(step=40))
        res = F.run_bank24_login(env)
        self.assertEqual(res.status, "submit_failed")
        self.assertEqual(env.popen_calls, 1)     # 재실행/재시도 없음


class TestNoSecretsInLogs(unittest.TestCase):
    def test_full_flow_no_pii(self):             # §135 PW·PII 비노출(전 구간)
        cred = FakeCred()
        main_after = _main_window()
        dlg = _login_dialog(hwnd=100)
        # 로그인 폴링→성공→wait_main 에서 메인 등장
        env = FakeEnv(window_batches=[[dlg], [dlg], [main_after], [main_after]],
                      stop=FakeStop(), credential=cred, winapi=FakeWinAPI())
        F.run_bank24_login(env)
        blob = "".join(env.logs)
        self.assertNotIn(SYN_ID, blob)
        self.assertNotIn(SYN_PW, blob)
        # HWND 원문(정수 문자열)도 로그에 넣지 않음 — 로그는 고정 코드만
        for line in env.logs:
            self.assertTrue(line.isupper() or line.startswith("STEP_")
                            or "_" in line)


if __name__ == "__main__":
    unittest.main()
