# -*- coding: utf-8 -*-
"""Bank24 실행·로그인 흐름 — Y_BankAuto(extract_shinhan.py)의 실제 순서/ fallback 이식본.

Y_BankAuto 의 `launch_and_login` / `wait_main` / restart=False 재사용 분기와 **동일한
창 탐색·후보 선택·입력 순서·직접입력 3단계 fallback·로그인창 선택 4단계 fallback·
좌표/클립보드 최후 fallback·메인 창 대기·전면화** 를 재현한다.

보안 강화(참고 코드와의 차이):
- 실제 자격증명/PII 를 하드코딩하지 않는다. 로그인 시점에 INI[login] 을 다시 읽는다.
- 원문 예외/창 제목/팝업 내용/컨트롤 값/HWND/ID/PW 를 로그에 남기지 않는다.
  진단은 boolean·개수·고정 안전코드만 기록한다(§109-x).
- 좌표/클립보드 최후 fallback 은 참고 코드와 동일하게 제공하되, 사용 시 평문 PW 노출
  위험(클립보드 히스토리 포함)을 안전코드로 보고한다(§107).
- OS/GUI 를 만지는 모든 원시 동작(창 열거·Popen·user32·pyautogui·pyperclip·시계)은
  주입 가능한 LoginEnv 로 분리한다. 실제 Bank24 는 이 모듈이 자동 시작하지 않으며,
  통합 테스트는 별도 승인 후 수행한다.

수정 범위는 Bank24 실행·로그인으로 제한한다(§132). 탁상 이동·조회·DB 는 이 모듈에서
호출하지 않으며, 로그인 성공 확인 전에는 다음 단계(탁상 이동)를 호출하지 않는다(§134).
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

# ── 상수(코드 고정, §4~§13) ────────────────────────────────────────────────────
APP_PATH = r"C:\KADC\X11\Bank24.exe"       # §4
MAIN_CLS = "TfrmMain"                        # §5

KNOWN_LOGIN_CLS = ("TDXLoginDialog", "TfrmLogin", "TfrmLoginDlg", "TLoginForm")  # §10
SKIP_CLS = (                                                                     # §11
    "Chrome_WidgetWin_1", "Chrome_WidgetWin_0",
    "MozillaWindowClass", "IEFrame", "CabinetWClass",
    "Shell_TrayWnd", "Progman", "WorkerW",
)
# 전체 Edit 클래스(§12) — _count_login_edit_candidates / 시도1 / 시도2-A 에서 사용(§14)
_LOGIN_EDIT_CLS = (
    "Edit",
    "TEdit",
    "TMaskEdit",
    "TcxTextEdit",
    "TcxCustomInnerTextEdit",
    "TcxCustomDropDownInnerEdit",
    "TcxCustomMaskEdit",
    "TcxCustomEdit",
)
# _find_login_win 내부 후보 Edit 검사에만 쓰는 제한된 네 클래스(§13)
_FIND_LOGIN_EDIT_CLS = ("Edit", "TEdit", "TMaskEdit", "TcxCustomDropDownInnerEdit")

OK_BUTTON_CLS = ("TButton", "Button")        # §74
OK_BUTTON_TEXT = "확인"                       # §75
OK_BUTTON_TEXTS = ("확인", "확인 및 실행", "로그인", "Login", "OK")

_BANK24_TITLE_HINTS = ("BANK24", "KADC_LOADER", "금융기관", "BANK ONLINE", "X11")  # §115
_TITLE_MATCH_KEYWORDS = ("BANK ONLINE", "금융기관온라인", "X11")                   # §36/§86
_LOGIN_WIN_EXCLUDE_CLS = ("TApplication", "TProgressDlg")                          # §36/§85

_DESCENDANTS_TIMEOUT = 3.0                    # §14-1 (daemon join 상한)

# Win32 메시지
_WM_SETTEXT = 0x000C
_EM_SETSEL = 0x00B1
_EM_REPLACESEL = 0x00C2
_BM_CLICK = 0x00F5
_SW_RESTORE = 9
_HWND_TOPMOST = -1
_HWND_NOTOPMOST = -2
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_SHOWWINDOW = 0x0040


# ── 안전 로그 코드(§109-3, §127) — 원문/PII/HWND/값 미포함 ──────────────────────
class Step:
    LAUNCH = "STEP_BANK24_LAUNCH"            # Bank24 실행
    LOGIN_WINDOW = "STEP_LOGIN_WINDOW"       # 로그인창 확인
    CREDENTIAL = "STEP_CREDENTIAL_INPUT"     # 자격증명 입력
    FALLBACK = "STEP_FALLBACK_USED"          # fallback 사용
    MAIN_WINDOW = "STEP_MAIN_WINDOW"         # 메인 창 확인
    LOGIN_DONE = "STEP_LOGIN_DONE"           # 로그인 완료


# 실패/진단 안전코드
BANK24_LAUNCH_FAILED = "BANK24_LAUNCH_FAILED"      # §30
LOGIN_SUBMIT_FAILED = "LOGIN_SUBMIT_FAILED"        # §112
LOGIN_NOT_CONFIRMED = "LOGIN_NOT_CONFIRMED"        # §126
FALLBACK_WINDOW_NOT_FOUND = "FALLBACK_WINDOW_NOT_FOUND"  # §83-3
COORD_CLIPBOARD_PW_EXPOSURE = "COORD_CLIPBOARD_PW_EXPOSURE_RISK"  # §107

# failure_reason 안전코드(§109-4)
_R_DIRECT_INPUT = "DIRECT_INPUT_FAILED"
_R_ID_VERIFY = "ID_VERIFY_FAILED"
_R_OK_BUTTON = "OK_BUTTON_FAILED"
_R_EDITS_LT2 = "EDIT_CANDIDATES_LT2"
_R_ATTEMPT1_EXC = "ATTEMPT1_EXCEPTION"
_R_FALLBACK_WIN = FALLBACK_WINDOW_NOT_FOUND
_R_2A_INPUT = "ATTEMPT2A_DIRECT_INPUT_FAILED"
_R_2A_ID_VERIFY = "ATTEMPT2A_ID_VERIFY_FAILED"
_R_2A_OK = "ATTEMPT2A_OK_FAILED"
_R_2A_EXC = "ATTEMPT2A_EXCEPTION"
_R_2B_NO_EDIT = "COORD_FALLBACK_NO_EDIT"
_R_2B_EXC = "COORD_FALLBACK_EXCEPTION"
_R_CRED_MISSING = "LOGIN_CREDENTIALS_MISSING"
_R_LOGIN_WIN_MISSING = "LOGIN_WINDOW_NOT_FOUND"


# ── 예외 ────────────────────────────────────────────────────────────────────────
class Bank24LaunchFailed(RuntimeError):
    """Bank24 실행 실패(§30). 원문 예외를 담지 않는다."""


class LoginSubmitFailed(RuntimeError):
    """로그인 전송 실패(§111). diag(안전 진단)만 담는다."""

    def __init__(self, diag: "LoginDiagnostics"):
        super().__init__(LOGIN_SUBMIT_FAILED)
        self.diag = diag


# ── 진단 상태(§109-1) — HWND/제목/컨트롤 값/ID/PW 미포함(§109-2) ─────────────────
@dataclass
class LoginDiagnostics:
    login_win_found: bool = False
    new_wins_count: int = 0
    fallback_used: bool = False
    edit_candidates_count: int = 0
    failure_reason: str = ""
    attached_existing_login: bool = False   # 이미 떠 있는 로그인창에 붙었는지(Popen 없이)
    top_level_count: int = 0                 # 로그인 시점 top-level 창 개수(안전 진단, -1=열거 예외)


@dataclass
class LoginResult:
    status: str                     # "done" | "stopped" | "error" | "submit_failed" | "launch_failed"
    reused_main: bool = False
    diag: LoginDiagnostics = field(default_factory=LoginDiagnostics)
    main_win: object = None         # 확인된 메인 창(다음 단계 핸드오프용). PII/원문 미포함.


# ── 주입 가능한 환경(실 기본값은 pywinauto/win32/pyautogui/pyperclip) ────────────
class _RealWinAPI:  # pragma: no cover - 실제 환경 전용
    """user32/kernel32 얇은 래퍼. 값·HWND 를 로그로 남기지 않는다."""

    def show_window(self, hwnd, cmd):
        import ctypes
        return ctypes.windll.user32.ShowWindow(int(hwnd), cmd)

    def set_foreground(self, hwnd):
        import ctypes
        return ctypes.windll.user32.SetForegroundWindow(int(hwnd))

    def bring_window_to_top(self, hwnd):
        import ctypes
        return ctypes.windll.user32.BringWindowToTop(int(hwnd))

    def set_active_window(self, hwnd):
        import ctypes
        return ctypes.windll.user32.SetActiveWindow(int(hwnd))

    def set_window_pos(self, hwnd, insert_after, flags):
        import ctypes
        return ctypes.windll.user32.SetWindowPos(
            int(hwnd), int(insert_after), 0, 0, 0, 0, int(flags))

    def get_foreground(self):
        import ctypes
        return int(ctypes.windll.user32.GetForegroundWindow())

    def get_current_thread_id(self):
        import ctypes
        return int(ctypes.windll.kernel32.GetCurrentThreadId())

    def get_window_thread(self, hwnd):
        import ctypes
        return int(ctypes.windll.user32.GetWindowThreadProcessId(int(hwnd), None))

    def attach_thread_input(self, a, b, attach):
        import ctypes
        return ctypes.windll.user32.AttachThreadInput(int(a), int(b), bool(attach))

    def send_message(self, hwnd, msg, wparam, lparam):
        import ctypes
        return ctypes.windll.user32.SendMessageW(int(hwnd), msg, wparam, lparam)

    def send_message_text(self, hwnd, msg, wparam, text):
        import ctypes
        return ctypes.windll.user32.SendMessageW(
            int(hwnd), msg, wparam, ctypes.c_wchar_p(text))


class LoginEnv:
    """Bank24 실행·로그인에 필요한 원시 동작 모음. 테스트는 이 인터페이스를 fake 로 주입.

    실제 기본값은 pywinauto win32 백엔드/Popen/user32/pyautogui/pyperclip 을 사용하며,
    이 모듈이 실제 Bank24 를 자동 시작하지 않는다(호출부 승인 후에만 launch 수행).
    """

    def __init__(self, *, stop, credential_provider, log=None):
        self.stop = stop                              # .is_stopped() 제공
        self.credential_provider = credential_provider  # callable()->cred|None
        self._log = log
        self.winapi = _RealWinAPI()

    # 로그: 고정 안전코드만(§109-3). 원문/PII 인자 금지.
    def log(self, code: str):
        if self._log is not None:
            try:
                self._log(str(code))
            except Exception:
                pass

    # 시계
    def time(self) -> float:  # pragma: no cover - 실제 환경 전용
        import time
        return time.time()

    def sleep(self, seconds: float):  # pragma: no cover
        import time
        time.sleep(seconds)

    # 창 열거 — Desktop(backend="win32").windows()(§7)
    def windows(self) -> list:  # pragma: no cover
        from pywinauto import Desktop
        return list(Desktop(backend="win32").windows())

    # 실행 — subprocess.Popen(APP_PATH)(§8). 기존 프로세스 종료 안 함(§9).
    def popen(self, path: str):  # pragma: no cover
        import subprocess
        subprocess.Popen(path)

    # 좌표/클립보드 최후 fallback 원시 동작
    def pyautogui(self):  # pragma: no cover
        import pyautogui
        pyautogui.FAILSAFE = True
        return pyautogui

    def clipboard_copy(self, text: str):  # pragma: no cover
        import pyperclip
        pyperclip.copy(text)


# ── 안전 접근 헬퍼(참고 코드의 safe_cls/safe_txt/safe_rect 동등) ─────────────────
def _safe_cls(w) -> str:
    try:
        return w.class_name()
    except Exception:
        return "?"


def _safe_txt(w) -> str:
    try:
        return w.window_text() or ""
    except Exception:
        return ""


def _safe_rect(w):
    try:
        r = w.rectangle()
        return r.left, r.top, r.right, r.bottom
    except Exception:
        return 0, 0, 0, 0


def _handle(w):
    return w.handle


def _enum_err_diag(e) -> str:
    """창 열거 예외를 안전 진단 토큰으로 요약(원문 메시지/PII/HWND 없음).

    형식: ENUMERR_<예외클래스>[_<누락모듈>][_<라이브러리파일>:<행>].
    ImportError.name(누락 모듈명)과 최심부 프레임의 파일 basename+행만 담는다 —
    전부 라이브러리 식별자/고정 토큰이라 사용자 데이터가 아니다. 추가로 전체 traceback 을
    %TEMP%\\Y_TSBankAuto_enumdiag.txt 에 best-effort 기록(로컬 진단 전용, GUI 로그엔 안 남김).
    """
    parts = ["ENUMERR", type(e).__name__]
    name = getattr(e, "name", None)
    if name:
        parts.append(str(name))
    try:
        import os
        import traceback
        tb = traceback.extract_tb(e.__traceback__)
        if tb:
            last = tb[-1]
            parts.append(os.path.basename(str(last.filename)) + ":" + str(last.lineno))
        import tempfile
        path = os.path.join(tempfile.gettempdir(), "Y_TSBankAuto_enumdiag.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("".join(traceback.format_exception(type(e), e, e.__traceback__)))
    except Exception:
        pass
    # 안전코드는 [A-Za-z0-9_.:] 만 남기도록 정리(공백/기타 문자 → _)
    token = "_".join(parts)
    return "".join(ch if (ch.isalnum() or ch in "_.:") else "_" for ch in token)


# ── §27 실행 전 top-level HWND 집합 스냅샷 ───────────────────────────────────────
def _snapshot_hwnd_set(env: LoginEnv) -> set:
    s = set()
    try:
        for w in env.windows():
            try:
                s.add(w.handle)
            except Exception:
                pass
    except Exception:
        pass
    return s


# ── §14-1~§14-5 daemon thread 로 제한된 descendants 탐색 ─────────────────────────
def _timed_descendants(win, cls_filter, timeout=_DESCENDANTS_TIMEOUT) -> list:
    """win.descendants() 중 cls_filter 클래스만 수집. 최대 timeout 초만 join.

    - daemon thread 에서 수행(§14-2). timeout 시 현재까지 수집된 결과만 사용(§14-3).
    - 예외/타임아웃 원문을 GUI 에 출력하지 않는다(§14-4). 안전 상태 코드도 남기지 않는다
      (이 함수는 상위 호출자가 개수만 기록).
    """
    result: list = []
    if isinstance(cls_filter, str):
        cls_filter = (cls_filter,)

    def _do():
        try:
            for c in win.descendants():          # 부분 수집 가능하도록 순차 append(§14-3)
                try:
                    if _safe_cls(c) in cls_filter:
                        result.append(c)
                except Exception:
                    pass
        except Exception:
            pass

    t = threading.Thread(target=_do, daemon=True)
    t.start()
    t.join(timeout=timeout)
    # t.is_alive() 여도 원문/경고를 GUI 로 내보내지 않는다(§14-4).
    return result


# ── §14-1 visible+enabled Edit 후보 수 ───────────────────────────────────────────
def _count_login_edit_candidates(win) -> int:
    try:
        descs = _timed_descendants(win, _LOGIN_EDIT_CLS, timeout=_DESCENDANTS_TIMEOUT)
        count = 0
        for c in descs:
            try:
                if c.is_visible() and c.is_enabled():
                    count += 1
            except Exception:
                pass
        return count
    except Exception:
        return 0


# ── §39~§46 _find_login_win ─────────────────────────────────────────────────────
def _find_login_win(env: LoginEnv, before: set):
    """before 제외 → SKIP 제외 → KNOWN 직접매칭 즉시반환 → 클래스/제목 힌트 후보 →
    제한된 네 Edit 클래스로 Edit 2개 이상인 첫 창 → 없으면 첫 후보 → None."""
    try:
        all_wins = env.windows()
    except Exception:
        return None

    candidates = []
    for w in all_wins:
        try:
            if w.handle in before:              # §39
                continue
            cls = _safe_cls(w)
            if cls in SKIP_CLS:                  # §40
                continue
            ttl = _safe_txt(w)
            if cls in KNOWN_LOGIN_CLS:           # §41 즉시 반환
                return w
            if any(k in cls for k in ("TBnk", "TDX", "TForm", "TfrLogin")):  # §42
                candidates.append(w)
            elif any(k in ttl for k in ("BANK", "Bank", "bank", "로그인", "Login")):  # §43
                candidates.append(w)
        except Exception:
            pass

    # §44 — 제한된 네 Edit 클래스, visible/enabled 필터 없이 순수 descendants 개수(§13/§44)
    #        일반 w.descendants() 사용(§14-5: _timed_descendants 로 바꾸지 않는다).
    for w in candidates:
        try:
            eds = [c for c in w.descendants() if _safe_cls(c) in _FIND_LOGIN_EDIT_CLS]
            if len(eds) >= 2:
                return w
        except Exception:
            pass

    if candidates:                              # §45
        return candidates[0]
    return None                                 # §46


# ── §84~§87 _select_login_fallback_window ────────────────────────────────────────
def _select_login_fallback_window(new_wins):
    """1) TDXLoginDialog → 2) Edit 2+ 중 최다 → 3) 제목 매칭 → 4) 최소 면적."""
    if not new_wins:
        return None
    # §84
    for w in new_wins:
        try:
            if _safe_cls(w) == "TDXLoginDialog":
                return w
        except Exception:
            pass
    # §85
    best_win, best_count = None, 0
    for w in new_wins:
        try:
            if _safe_cls(w) in _LOGIN_WIN_EXCLUDE_CLS:
                continue
            n = _count_login_edit_candidates(w)
            if n >= 2 and n > best_count:
                best_win, best_count = w, n
        except Exception:
            pass
    if best_win is not None:
        return best_win
    # §86
    for w in new_wins:
        try:
            if _safe_cls(w) in _LOGIN_WIN_EXCLUDE_CLS:
                continue
            ttl = _safe_txt(w)
            if any(k in ttl for k in _TITLE_MATCH_KEYWORDS):
                return w
        except Exception:
            pass
    # §87
    cands = [w for w in new_wins if _safe_cls(w) not in _LOGIN_WIN_EXCLUDE_CLS]
    if not cands:
        return None
    return min(cands, key=lambda ww: (_safe_rect(ww)[2] - _safe_rect(ww)[0])
               * (_safe_rect(ww)[3] - _safe_rect(ww)[1]))


# ── §47~§54 force_foreground ─────────────────────────────────────────────────────
def force_foreground(env: LoginEnv, hwnd, label: str) -> bool:
    """SW_RESTORE→SetForegroundWindow, 실패 시 AttachThreadInput fallback. HWND 원문 미로그(§54)."""
    api = env.winapi
    def _topmost_pulse() -> bool:
        try:
            flags = _SWP_NOMOVE | _SWP_NOSIZE | _SWP_SHOWWINDOW
            if hasattr(api, "set_window_pos"):
                api.set_window_pos(hwnd, _HWND_TOPMOST, flags)
                env.sleep(0.05)
                api.set_window_pos(hwnd, _HWND_NOTOPMOST, flags)
            if hasattr(api, "bring_window_to_top"):
                api.bring_window_to_top(hwnd)
            if hasattr(api, "set_active_window"):
                api.set_active_window(hwnd)
            api.set_foreground(hwnd)
            env.sleep(0.2)
            return api.get_foreground() == hwnd
        except Exception:
            return False

    try:
        api.show_window(hwnd, _SW_RESTORE)
        env.sleep(0.15)                          # §47
        if hasattr(api, "bring_window_to_top"):
            api.bring_window_to_top(hwnd)
        api.set_foreground(hwnd)
        env.sleep(0.2)                           # §48
        if api.get_foreground() == hwnd:         # §49
            return True
    except Exception:
        pass

    # §50~§52 AttachThreadInput fallback (예외와 무관하게 finally 에서 detach — §52 안전강화)
    cur_tid = fg_tid = tgt_tid = None
    attached = False
    try:
        fg = api.get_foreground()
        cur_tid = api.get_current_thread_id()
        fg_tid = api.get_window_thread(fg)
        tgt_tid = api.get_window_thread(hwnd)
        api.attach_thread_input(cur_tid, fg_tid, True)
        api.attach_thread_input(cur_tid, tgt_tid, True)
        attached = True
        api.show_window(hwnd, _SW_RESTORE)
        if hasattr(api, "bring_window_to_top"):
            api.bring_window_to_top(hwnd)
        api.set_foreground(hwnd)
        env.sleep(0.2)                           # §51
        if api.get_foreground() == hwnd:
            return True
    except Exception:
        pass
    finally:
        if attached:
            try:
                api.attach_thread_input(cur_tid, fg_tid, False)
            except Exception:
                pass
            try:
                api.attach_thread_input(cur_tid, tgt_tid, False)
            except Exception:
                pass
    return _topmost_pulse()


def _keep_bank24_foreground(env: LoginEnv, wins=None) -> bool:
    """Automation-time focus guard. Bring Bank24 login/main candidates forward."""
    try:
        if wins is None:
            wins = env.windows()
    except Exception:
        return False
    preferred = []
    fallback = []
    for w in wins or []:
        try:
            cls = _safe_cls(w)
            title = _safe_txt(w).strip()
            if cls == "TDXLoginDialog":
                preferred.append(w)
            elif cls == MAIN_CLS and (_is_bank24_title(title) or title in ("ProgressDlg", "")):
                fallback.append(w)
        except Exception:
            pass
    for w in preferred + fallback:
        try:
            if force_foreground(env, _handle(w), "Bank24포커스유지"):
                return True
        except Exception:
            pass
    return False


# ── §64~§65 직접입력 3단계 fallback ─────────────────────────────────────────────
def _set_edit_text_direct(env: LoginEnv, ctrl, value: str, label: str) -> bool:
    """set_edit_text → WM_SETTEXT → EM_SETSEL+EM_REPLACESEL. 예외 없으면 성공(§65).

    - 비표시/비활성 컨트롤이면 즉시 False, 다음 fallback 없음(§65-2).
    - visible/enabled 조회 자체가 예외면 상태 확인 건너뛰고 fallback 계속(§65-3).
    - 각 단계 예외는 다음 단계로 진행, 원문 예외 미로그(§65-4). 값은 절대 로그 안 함.
    """
    try:
        try:
            if not ctrl.is_visible() or not ctrl.is_enabled():
                return False                     # §65-2
        except Exception:
            pass                                 # §65-3
        hwnd = _handle(ctrl)
        # 1순위 set_edit_text
        try:
            ctrl.set_edit_text(value)
            return True
        except Exception:
            pass
        # 2순위 WM_SETTEXT
        try:
            env.winapi.send_message_text(hwnd, _WM_SETTEXT, 0, value)
            return True
        except Exception:
            pass
        # 3순위 EM_SETSEL + EM_REPLACESEL
        try:
            env.winapi.send_message(hwnd, _EM_SETSEL, 0, -1)
            env.winapi.send_message_text(hwnd, _EM_REPLACESEL, 1, value)
            return True
        except Exception:
            pass
        return False
    except Exception:
        return False


# ── §66 검증용 read-back(값을 로그로 남기지 않음) ────────────────────────────────
def _read_edit_text_safe(ctrl) -> str:
    try:
        return ctrl.window_text() or ""
    except Exception:
        pass
    try:
        txts = ctrl.texts()
        return txts[0] if txts else ""
    except Exception:
        pass
    return ""


# ── §73~§78 확인 버튼: BM_CLICK 우선, 실패 시 click() ────────────────────────────
def _click_login_ok_button(env: LoginEnv, login_win) -> bool:
    try:
        force_foreground(env, _handle(login_win), "로그인확인")
    except Exception:
        pass
    btn = None
    try:
        for c in login_win.descendants():
            try:
                text = _safe_txt(c).strip()
                if _safe_cls(c) in OK_BUTTON_CLS and (
                    text in OK_BUTTON_TEXTS
                    or any(t and t in text for t in OK_BUTTON_TEXTS)
                ):
                    btn = c
                    break
            except Exception:
                pass
    except Exception:
        pass
    if btn is None:
        try:
            pg = env.pyautogui()
            pg.press("enter")
            env.sleep(0.3)
            return True
        except Exception:
            return False
    # 1순위 BM_CLICK (§76)
    try:
        env.winapi.send_message(_handle(btn), _BM_CLICK, 0, 0)
        return True
    except Exception:
        pass
    # 2순위 button.click (§77) — click_input/좌표 클릭은 쓰지 않는다(§78)
    try:
        btn.click()
        return True
    except Exception:
        return False


def _verify_and_submit(env, id_ctrl, pw_ctrl, uid, pwd, login_win, diag,
                       reason_input, reason_id, reason_ok) -> bool:
    """직접입력 후 read-back 검증 → 확인 버튼. 성공 시 True.

    §67~§69, §69-1~§69-4 를 시도1/시도2-A 에 동일 적용.
    """
    env.log(Step.CREDENTIAL)
    id_ok = _set_edit_text_direct(env, id_ctrl, uid, "ID")
    pw_ok = _set_edit_text_direct(env, pw_ctrl, pwd, "PW")  # §63: ID 성공여부 확인 전 PW 도 시도
    # 안전 진단: 직접입력 성공 여부(불리언만, 값 없음).
    env.log("LOGIN_DETAIL_INPUT_IDOK%d_PWOK%d" % (int(id_ok), int(pw_ok)))
    if not id_ok or not pw_ok:
        diag.failure_reason = reason_input
        env.log("LOGIN_DETAIL_" + reason_input)
        return False
    id_val = _read_edit_text_safe(id_ctrl)
    pw_val = _read_edit_text_safe(pw_ctrl)
    id_match = (id_val == uid)                    # §67
    id_not_pwd = (id_val != pwd)                  # §67
    # §68/§69/§69-1: PW 길이만 진단(OK/FAIL/UNKNOWN). 값은 남기지 않는다.
    if pw_val:
        _pw_status = "OK" if len(pw_val) == len(pwd) else "FAIL"
    else:
        _pw_status = "UNKNOWN"                     # §69
    # 안전 진단: read-back 검증 결과(불리언/상태만, ID·PW 원문 없음).
    env.log("LOGIN_DETAIL_VERIFY_IDMATCH%d_IDEMPTY%d_PW%s" % (
        int(id_match), int(id_val == ""), _pw_status))
    # §69-2/§69-3: 확인 진행은 id_match 와 id_not_pwd 두 조건만으로 결정(PW 길이 무관)
    if not id_match or not id_not_pwd:
        diag.failure_reason = reason_id
        env.log("LOGIN_DETAIL_" + reason_id)
        return False
    if _click_login_ok_button(env, login_win):
        return True
    diag.failure_reason = reason_ok
    env.log("LOGIN_DETAIL_" + reason_ok)
    return False


# ── §55~§72 시도 1: 직접 입력 ────────────────────────────────────────────────────
def _attempt1_direct(env, login_win, uid, pwd, diag) -> bool:
    """login_win 이 있을 때만 실행(§55). force_foreground 후 입력(§56/§57)."""
    _fg = force_foreground(env, _handle(login_win), "로그인창")   # 실패해도 계속(§57)
    env.log("LOGIN_DETAIL_FG1_%d" % int(bool(_fg)))              # 안전 진단: 전면화 성공 여부
    try:
        edits = []
        for c in login_win.descendants():
            if _safe_cls(c) in _LOGIN_EDIT_CLS:               # 전체 Edit 클래스(§58)
                try:
                    if c.is_visible() and c.is_enabled():
                        edits.append(c)
                except Exception:
                    pass
        edits.sort(key=lambda c: (_safe_rect(c)[1], _safe_rect(c)[0]))  # (top,left) §59
        diag.edit_candidates_count = len(edits)
        # 안전 진단: 찾은 Edit 개수 + 클래스명(라이브러리 식별자, PII 아님).
        env.log("LOGIN_DETAIL_EDITS1_%d" % len(edits))
        _cls = "|".join(_safe_cls(c) for c in edits[:4])
        if _cls:
            env.log("LOGIN_DETAIL_EDITCLS1_" + _cls)
        if len(edits) < 2:                                    # §61
            diag.failure_reason = _R_EDITS_LT2
            env.log("LOGIN_DETAIL_" + _R_EDITS_LT2)
            return False
        id_ctrl, pw_ctrl = edits[0], edits[1]                 # §60
        return _verify_and_submit(env, id_ctrl, pw_ctrl, uid, pwd, login_win, diag,
                                  _R_DIRECT_INPUT, _R_ID_VERIFY, _R_OK_BUTTON)
    except Exception:
        diag.failure_reason = _R_ATTEMPT1_EXC                 # 원문 예외 미로그
        return False


# ── §88~§95 시도 2-A: fallback 창 Edit 탐색 입력 ─────────────────────────────────
def _attempt2a_edit(env, dlg, uid, pwd, diag) -> bool:
    try:
        try:
            dlg.set_focus()
        except Exception:
            pass
        env.sleep(0.3)                                        # §88
        login_edits = []
        for c in dlg.descendants():
            if _safe_cls(c) in _LOGIN_EDIT_CLS:               # 전체 Edit 클래스(§89)
                try:
                    if c.is_visible() and c.is_enabled():
                        r = c.rectangle()
                        login_edits.append((r.top, r.left, c))
                except Exception:
                    pass
        login_edits.sort(key=lambda x: (x[0], x[1]))          # (top,left) §90
        diag.edit_candidates_count = len(login_edits)
        # 안전 진단: fallback 창에서 찾은 Edit 개수 + 클래스명.
        env.log("LOGIN_DETAIL_EDITS2A_%d" % len(login_edits))
        _cls = "|".join(_safe_cls(t[2]) for t in login_edits[:4])
        if _cls:
            env.log("LOGIN_DETAIL_EDITCLS2A_" + _cls)
        if len(login_edits) < 2:                              # §83-4/§91
            diag.failure_reason = _R_EDITS_LT2
            env.log("LOGIN_DETAIL_" + _R_EDITS_LT2)
            return False
        id_ctrl = login_edits[0][2]
        pw_ctrl = login_edits[1][2]
        return _verify_and_submit(env, id_ctrl, pw_ctrl, uid, pwd, dlg, diag,
                                  _R_2A_INPUT, _R_2A_ID_VERIFY, _R_2A_OK)
    except Exception:
        diag.failure_reason = _R_2A_EXC
        return False


# ── §96~§108 시도 2-B: 좌표·클립보드 최후 fallback ──────────────────────────────
def _attempt2b_coord(env, dlg, uid, pwd, diag) -> bool:
    """login_ok 아니고 Edit 후보>=1 일 때만(§96). 평문 PW 노출 위험 보고(§107)."""
    if _count_login_edit_candidates(dlg) < 1:                 # §96/§97
        diag.failure_reason = _R_2B_NO_EDIT
        return False
    env.log(COORD_CLIPBOARD_PW_EXPOSURE)                      # §107 — 사용 전 위험 보고
    pg = None
    ok = False
    try:
        pg = env.pyautogui()
        try:
            dlg.set_focus()
        except Exception:
            pass
        env.sleep(0.3)                                        # §98
        l, t, r, b = _safe_rect(dlg)
        w_w, w_h = r - l, b - t
        id_x = l + w_w // 2                                   # §99
        id_y = t + w_h // 3
        pw_x = id_x
        pw_y = id_y + 25
        pg.click(id_x, id_y)
        env.sleep(0.3)                                        # §100
        pg.hotkey("ctrl", "a")
        pg.typewrite(uid, interval=0.07)                      # §101
        env.clipboard_copy(pwd)                               # §102
        pg.click(pw_x, pw_y)
        env.sleep(0.3)                                        # §103
        pg.hotkey("ctrl", "a")
        pg.hotkey("ctrl", "v")
        env.sleep(0.3)                                        # §104
        pg.press("enter")                                     # §105
        ok = True
        return True
    except Exception:
        diag.failure_reason = _R_2B_EXC                       # 원문 예외 미로그
        return False
    finally:
        try:
            env.clipboard_copy("")                            # §106 성공·실패 무관 클립보드 소거
        except Exception:
            pass
        if not ok and not diag.failure_reason:
            diag.failure_reason = _R_2B_EXC


# ── §27~§112 launch_and_login ────────────────────────────────────────────────────
def launch_and_login(env: LoginEnv) -> LoginDiagnostics:
    """Bank24 실행 + 로그인 전송. 성공 시 diag 반환, 실패 시 LoginSubmitFailed(diag) 발생.

    자격증명은 로그인 시점에 provider() 로 다시 읽는다(§16~§18). 시도 종료 후 지역
    ID/PW 참조를 삭제하고 cred 를 wipe 한다(§20/§21). Python str 완전 소거는 보장하지
    않는다(§22).
    """
    diag = LoginDiagnostics()
    before = _snapshot_hwnd_set(env)               # §27

    env.log(Step.LAUNCH)
    try:
        env.popen(APP_PATH)                        # §8/§28 (기존 프로세스 종료 안 함 §9)
    except Exception:
        env.log(BANK24_LAUNCH_FAILED)              # §29/§30 원문 미로그
        raise Bank24LaunchFailed(BANK24_LAUNCH_FAILED)

    login_win, new_wins = _poll_login_window(env, before, diag)   # §31~§38
    return _perform_login(env, login_win, new_wins, diag)


def login_existing_window(env: LoginEnv, login_win) -> LoginDiagnostics:
    """이미 떠 있는 로그인창에 **Popen 없이** 붙어 로그인(attach). 실 프로세스를 새로
    시작하지 않으며 기존 프로세스도 종료하지 않는다(§9). 성공 시 diag, 실패 시
    LoginSubmitFailed(diag)."""
    diag = LoginDiagnostics()
    diag.attached_existing_login = True
    # fallback 후보로 현재 top-level 창(SKIP 제외)을 제공. 새로 뜬 창이 아니므로 poll 없음.
    try:
        new_wins = [w for w in env.windows() if _safe_cls(w) not in SKIP_CLS]
    except Exception:
        new_wins = []
    return _perform_login(env, login_win, new_wins, diag)


def _perform_login(env: LoginEnv, login_win, new_wins, diag) -> LoginDiagnostics:
    """login_win / new_wins 가 확보된 상태에서 자격증명 입력·확인 전송(launch/attach 공용).

    자격증명은 로그인 시점에 provider() 로 다시 읽는다(§16~§18). 시도 종료 후 지역
    ID/PW 참조를 삭제하고 cred 를 wipe 한다(§20/§21).
    """
    diag.login_win_found = (login_win is not None)
    diag.new_wins_count = len(new_wins)
    try:                                           # 안전 진단: 로그인 시점 top-level 개수
        diag.top_level_count = len(env.windows())
    except Exception as _e:
        diag.top_level_count = -1
        # 창 열거 예외를 안전 진단 토큰(클래스+누락모듈+파일:행)으로 기록(원문/PII 없음, §109).
        env.log("LOGIN_DETAIL_" + _enum_err_diag(_e))

    cred = None
    uid = pwd = None
    login_ok = False
    fallback_used = False
    try:
        provider = env.credential_provider
        cred = provider() if callable(provider) else provider
        if cred is None:                           # §17/§48 fail-closed
            diag.failure_reason = _R_CRED_MISSING
        else:
            uid = cred.username
            pwd = cred.use_password()

            # 시도 1: 직접 입력(§55)
            if login_win is not None and uid is not None:
                env.log(Step.LOGIN_WINDOW)
                if _attempt1_direct(env, login_win, uid, pwd, diag):
                    login_ok = True

            # fallback 전: 기존 visible+enabled TDXLoginDialog 를 new_wins 앞에 보강(§80/§81)
            if not login_ok:
                new_wins = _prepend_existing_login_dialogs(env, new_wins)
                diag.new_wins_count = len(new_wins)

            # 시도 2: fallback (§82/§83) — new_wins 있을 때만
            if not login_ok and new_wins and uid is not None:
                fallback_used = True               # §83-1
                diag.fallback_used = True
                env.log(Step.FALLBACK)
                dlg = _select_login_fallback_window(new_wins)
                if dlg is None:
                    diag.failure_reason = _R_FALLBACK_WIN   # §83-3
                else:
                    if _attempt2a_edit(env, dlg, uid, pwd, diag):   # 2-A
                        login_ok = True
                    if not login_ok:                                # 2-B
                        if _attempt2b_coord(env, dlg, uid, pwd, diag):
                            login_ok = True
            elif not login_ok and not new_wins:
                # §83/§83-2: TDX 보강만 되고 여전히 비면 fallback 없이 실패로 진행
                if not diag.failure_reason:
                    diag.failure_reason = _R_LOGIN_WIN_MISSING
    finally:
        # §20/§21 지역 자격증명 참조 삭제 + cred wipe (성공·실패·중지 무관)
        try:
            if cred is not None:
                cred.wipe()
        except Exception:
            pass
        del cred
        del uid
        del pwd

    if not login_ok:                               # §109~§112
        if not diag.failure_reason:
            diag.failure_reason = _R_LOGIN_WIN_MISSING
        if diag.failure_reason:
            env.log(f"LOGIN_DETAIL_{diag.failure_reason}")
        # 안전 진단(개수만): top-level 창 개수·새 창 개수·attach 여부. 제목/HWND/값 없음(§109-2).
        env.log(f"LOGIN_DETAIL_WINCOUNT_{diag.top_level_count}")
        env.log(f"LOGIN_DETAIL_NEWWINS_{diag.new_wins_count}")
        if diag.attached_existing_login:
            env.log("LOGIN_DETAIL_ATTACHED_EXISTING")
        env.log(LOGIN_SUBMIT_FAILED)               # §112 안전코드만
        raise LoginSubmitFailed(diag)              # §111
    return diag


def _poll_login_window(env, before, diag):
    """§32~§38: 최대 30초, 0.5초 간격 폴링. TDXLoginDialog 최우선, title+Edit 매칭."""
    login_win = None
    new_wins = []
    seen_new = set()
    enum_err_logged = False                        # 열거 예외 클래스는 1회만 로깅
    t_start = env.time()

    while env.time() - t_start < 30:
        if env.stop.is_stopped():                  # §37 중지 확인
            break
        try:
            wins = env.windows()
        except Exception as _e:
            wins = None                            # §38-2 이 회차만 건너뜀
            if not enum_err_logged:                # 원인 확진용: 안전 진단 토큰(원문/PII 없음)
                enum_err_logged = True
                env.log("LOGIN_DETAIL_" + _enum_err_diag(_e))
        if wins is not None:
            _keep_bank24_foreground(env, wins)
            for w in wins:
                try:
                    hwnd = w.handle
                    cls = _safe_cls(w)
                    ttl = _safe_txt(w)
                except Exception:
                    continue                       # §38-1 해당 창만 건너뜀

                # §33 TDXLoginDialog: before 여부 무관 최우선
                if cls == "TDXLoginDialog":
                    try:
                        if w.is_visible() and w.is_enabled():
                            login_win = w
                            break
                    except Exception:
                        pass

                try:
                    if hwnd in before:             # §34
                        continue
                    if cls in SKIP_CLS:            # §34
                        continue
                    if hwnd not in seen_new:       # §35 중복 없이 추가
                        seen_new.add(hwnd)
                        new_wins.append(w)
                    # §36 title+Edit 매칭
                    if cls not in _LOGIN_WIN_EXCLUDE_CLS and any(
                            k in ttl for k in _TITLE_MATCH_KEYWORDS):
                        if _count_login_edit_candidates(w) >= 2:
                            login_win = w
                            break
                except Exception:
                    continue                       # §38-1/§38-3
        if login_win is not None:
            break
        env.sleep(0.5)                             # §38-4 전체 30초 상한 유지

    if login_win is None:                          # §38 fallback
        login_win = _find_login_win(env, before)
    return login_win, new_wins


def _prepend_existing_login_dialogs(env, new_wins):
    """§80/§81: 현재 열린 visible+enabled TDXLoginDialog 를 new_wins 앞에 보강."""
    try:
        existing = set()
        for w in new_wins:
            try:
                existing.add(w.handle)
            except Exception:
                pass
        prepend = []
        for w in env.windows():
            try:
                if _safe_cls(w) == "TDXLoginDialog" and w.is_visible() and w.is_enabled():
                    if w.handle not in existing:
                        prepend.append(w)
            except Exception:
                pass
        if prepend:
            return prepend + new_wins
    except Exception:
        pass
    return new_wins


# ── §113~§126 wait_main ──────────────────────────────────────────────────────────
def _is_bank24_title(title: str) -> bool:
    t = (title or "").upper()                      # §116
    return any(h in t for h in _BANK24_TITLE_HINTS)


def wait_main(env: LoginEnv):
    """최대 90초, 1초 간격. TfrmMain 만 후보(§114). 정상 제목이면 전면화 후 반환.
    로딩/빈 제목 TfrmMain 은 loading candidate 로 보관, 타임아웃 시 마지막 candidate 반환."""
    LOADING_TITLES = {"ProgressDlg", ""}
    deadline = env.time() + 90                      # §113
    candidate = None
    last_login_warn = 0.0                           # §113-2
    seen_popup = set()

    while env.time() < deadline:
        try:
            wins = env.windows()                    # §113-1 매 회차 새로 열거
        except Exception:
            wins = None
        if wins is not None:
            _keep_bank24_foreground(env, wins)
            for w in wins:
                cls = _safe_cls(w)
                title = _safe_txt(w).strip()

                if cls == "TDXLoginDialog":         # §120/§121 잔존 경고(10초 간격, 원문 미로그)
                    now = env.time()
                    if now - last_login_warn >= 10.0:
                        last_login_warn = now
                        env.log("MAIN_LOGIN_DIALOG_STILL_OPEN")

                if cls == "#32770" or any(k in title for k in (
                        "오류", "확인", "알림", "인증", "비밀번호", "로그인", "서버")):
                    try:
                        h = w.handle
                    except Exception:
                        h = None
                    if h is not None and h not in seen_popup:   # §121 동일 HWND 1회
                        seen_popup.add(h)
                        env.log("MAIN_POPUP_DETECTED")          # §122/§123 원문 미로그

                if cls != MAIN_CLS:                 # §114
                    continue
                if not _is_bank24_title(title) and title not in LOADING_TITLES:
                    continue
                if title in LOADING_TITLES:         # §117 loading candidate 갱신(§113-4)
                    candidate = w
                    continue
                # §118/§119 정상 제목 TfrmMain — 전면화 결과와 무관하게 반환
                env.log(Step.MAIN_WINDOW)
                force_foreground(env, _handle(w), "메인창")     # §113-3
                return w
        env.sleep(1)

    # §124~§126 타임아웃
    if candidate is not None:
        force_foreground(env, _handle(candidate), "메인창(타임아웃)")  # §124/§125
        return candidate
    env.log(LOGIN_NOT_CONFIRMED)                    # §126
    return None


# ── §23~§26, §112-x 전체 실행·로그인 흐름 + 공통 후처리 ─────────────────────────
def _find_existing_main(env: LoginEnv):
    """§23/§24: 기존 프로세스를 종료하지 않고 Desktop 스캔으로 기존 메인 창을 찾는다.
    cls==MAIN_CLS 이고 제목에 힌트가 raw substring(upper 변환 없이) 포함되면 재사용 대상."""
    try:
        for w in env.windows():
            try:
                if _safe_cls(w) == MAIN_CLS and any(
                        h in _safe_txt(w) for h in _BANK24_TITLE_HINTS):
                    return w
            except Exception:
                pass                                # §25-3 예외는 후보 없음으로 처리
    except Exception:
        pass
    return None


def _find_existing_login_window(env: LoginEnv):
    """이미 떠 있는(실행 중) Bank24 로그인창을 종료하지 않고 감지한다.

    Bank24(KADC X11)는 사실상 단일 인스턴스라, 이미 로그인 화면이 떠 있으면 재실행
    (Popen)해도 새 창이 생기지 않는다 → launch 경로가 LOGIN_WINDOW_NOT_FOUND 로 실패.
    이를 피하려고 실행 중 로그인창이 있으면 그 창에 attach 한다(Popen 없음).

    오탐(=미실행인데 무관한 창을 로그인창으로 인식) 방지를 위해 보수적으로 판정한다:
      1) visible+enabled KNOWN_LOGIN_CLS(TDXLoginDialog 등) 창, 또는
      2) 제목이 Bank24 로그인 키워드와 매칭되면서 visible+enabled Edit 후보가 2개 이상인 창.
    둘 다 없으면 None(→ 정상적으로 launch_and_login 진행)."""
    try:
        wins = env.windows()
    except Exception:
        return None
    # 1) KNOWN_LOGIN_CLS 직접 매칭(visible+enabled)
    for w in wins:
        try:
            if _safe_cls(w) in KNOWN_LOGIN_CLS and w.is_visible() and w.is_enabled():
                return w
        except Exception:
            pass
    # 2) 제목 매칭 + visible/enabled Edit 후보 2개 이상
    for w in wins:
        try:
            cls = _safe_cls(w)
            if cls in SKIP_CLS or cls in _LOGIN_WIN_EXCLUDE_CLS:
                continue
            if any(k in _safe_txt(w) for k in _TITLE_MATCH_KEYWORDS):
                if _count_login_edit_candidates(w) >= 2:
                    return w
        except Exception:
            pass
    return None


def run_bank24_login(env: LoginEnv, *, proceed=None) -> LoginResult:
    """Bank24 실행·로그인 전체 흐름.

    §23~§26: 기존 메인 창이 있으면 재사용(전면화+1초, Popen/credential 미호출). 없지만
    이미 로그인창이 떠 있으면 그 창에 attach 해 로그인(Popen 없음). 둘 다 없으면
    launch_and_login(Popen+폴링). §112-x 공통 후처리: 중지 → wait_main → 2초 → done.
    proceed: 로그인 완료(done) 시에만 호출되는 다음 단계(탁상 이동) 트리거(§134). 기본 None.
    """
    diag = LoginDiagnostics()
    reused_main = False

    existing = _find_existing_main(env)             # §23/§24
    if existing is not None:
        # §25: 재사용 — Popen/credential provider 호출하지 않는다.
        env.log(Step.MAIN_WINDOW)
        force_foreground(env, _handle(existing), "기존 메인창")   # §25-1
        env.sleep(1)                                # §25-1 정확히 1초
        reused_main = True
    else:
        # 이미 실행 중인 로그인창이 있으면 재실행하지 않고 attach(Popen 없음). Bank24 는
        # 단일 인스턴스라 재실행 시 새 창이 안 떠 launch 경로가 실패하기 때문(§9 유지).
        existing_login = _find_existing_login_window(env)
        try:
            if existing_login is not None:
                env.log(Step.LOGIN_WINDOW)
                diag = login_existing_window(env, existing_login)
            else:                                   # §26 기존 창 없을 때만 실행+로그인
                diag = launch_and_login(env)
        except Bank24LaunchFailed:
            return LoginResult("launch_failed", False, diag)
        except LoginSubmitFailed as e:
            return LoginResult("submit_failed", False, e.diag)   # §112

    # §112-1/§112-2: 로그인 전송 성공 직후 중지 확인 → 있으면 wait_main 미호출
    if env.stop.is_stopped():
        return LoginResult("stopped", reused_main, diag)

    # §112-3/§25-2: 재사용 여부와 무관하게 공통 wait_main 실행
    main_win = wait_main(env)
    if main_win is None:                            # §112-4
        return LoginResult("error", reused_main, diag)

    # §112-5/§135-6: 정확히 2초 안정화 대기
    env.sleep(2)
    # §112-6/§135-8: 2초 동안(또는 직후) 중지면 다음 단계(탁상 이동) 미호출
    if env.stop.is_stopped():
        return LoginResult("stopped", reused_main, diag, main_win=main_win)

    env.log(Step.LOGIN_DONE)                        # §127 로그인 완료
    if callable(proceed):                           # §134 로그인 성공 확인 후에만 탁상 이동
        proceed(main_win)
    return LoginResult("done", reused_main, diag, main_win=main_win)
