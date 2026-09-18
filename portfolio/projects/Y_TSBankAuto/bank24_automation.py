# -*- coding: utf-8 -*-
"""Bank24 자동화 (S10).

★ 이번 작업에서는 실제 Bank24 실행/로그인/조작을 하지 않는다.
  ENABLE_REAL_AUTOMATION=False 이며, 실제 입력/클릭 함수는 호출 시 예외를 던진다.
  테스트는 FakeWindow 로만 신뢰 검증 로직을 확인한다.

원칙:
- 창 제목만으로 신뢰하지 않는다. PID/클래스/실행경로(allowlist)를 함께 확인한다.
- 입력·확인 직전 PID/HWND 재검증.
- 비밀번호를 클립보드에 넣지 않는다.
- pyautogui FAILSAFE 유지, 긴급 중지 지원.
- 전면 창이 대상에서 바뀌면 중단.
- 기존 Bank24 프로세스를 종료/전면화하지 않는다. 타 프로세스 종료 금지.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass

ENABLE_REAL_AUTOMATION = False   # 이번 작업: 실제 자동화 비활성


class AutomationBlocked(Exception):
    """실제 자동화가 비활성/검증실패 상태에서 호출됨."""


class EmergencyStop:
    """긴급 중지 플래그. set() 시 모든 단계가 중단."""

    def __init__(self):
        self._ev = threading.Event()

    def stop(self):
        self._ev.set()

    def is_stopped(self) -> bool:
        return self._ev.is_set()

    def check(self):
        if self._ev.is_set():
            raise AutomationBlocked("긴급 중지 요청됨")


@dataclass
class WindowInfo:
    """검증 대상 창 정보."""
    hwnd: int
    pid: int
    title: str
    window_class: str
    exe_path: str


@dataclass
class TrustPolicy:
    exe_path_allow: tuple[str, ...]      # 허용 실행경로(정확 일치, 소문자 비교)
    window_class_allow: tuple[str, ...]  # 허용 창 클래스


def verify_window_trust(win: WindowInfo, policy: TrustPolicy) -> tuple[bool, list[str]]:
    """창 신뢰 검증: 제목만으로 신뢰 금지. PID/클래스/실행경로 확인."""
    fails = []
    if win.pid <= 0:
        fails.append("유효하지 않은 PID")
    if win.hwnd <= 0:
        fails.append("유효하지 않은 HWND")
    norm_exe = os.path.normcase(os.path.normpath(win.exe_path or ""))
    allow = {os.path.normcase(os.path.normpath(p)) for p in policy.exe_path_allow}
    if norm_exe not in allow:
        fails.append("실행경로 allowlist 불일치")
    if policy.window_class_allow and win.window_class not in policy.window_class_allow:
        fails.append("창 클래스 allowlist 불일치")
    return (not fails), fails


def get_foreground_window_info():  # pragma: no cover - 실제 환경 전용
    """현재 전면 창 정보 조회 (pywin32). 이번 작업에서는 사용하지 않는다."""
    try:
        import win32gui
        import win32process
    except Exception as e:
        raise AutomationBlocked(f"pywin32 미설치: {e}")
    hwnd = win32gui.GetForegroundWindow()
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    title = win32gui.GetWindowText(hwnd)
    cls = win32gui.GetClassName(hwnd)
    exe = ""
    try:
        import psutil
        exe = psutil.Process(pid).exe()
    except Exception:
        exe = ""
    return WindowInfo(hwnd=hwnd, pid=pid, title=title, window_class=cls, exe_path=exe)


def send_keys_guarded(win: WindowInfo, policy: TrustPolicy, keys: str,
                      stop: EmergencyStop, *, current_foreground=None):
    """입력 직전 신뢰 재검증 후 send_keys. 실제 자동화 비활성 시 예외.

    - 전면 창이 대상과 다르면 중단.
    - 불확실한 컨트롤/좌표 입력 금지(이 함수는 named control 전제).
    """
    stop.check()
    ok, fails = verify_window_trust(win, policy)
    if not ok:
        raise AutomationBlocked("신뢰 검증 실패: " + "; ".join(fails))
    if current_foreground is not None and current_foreground.hwnd != win.hwnd:
        raise AutomationBlocked("전면 창이 대상에서 변경됨 → 중단")
    if not ENABLE_REAL_AUTOMATION:
        raise AutomationBlocked("실제 자동화 비활성(이번 작업)")
    raise AutomationBlocked("실제 send_keys 경로는 이번 작업에서 구현/실행하지 않음")


def ensure_failsafe():
    """pyautogui FAILSAFE 유지 확인."""
    try:
        import pyautogui
        pyautogui.FAILSAFE = True
        return True
    except Exception:
        return False
