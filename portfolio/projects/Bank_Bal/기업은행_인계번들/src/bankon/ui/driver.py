"""뱅크온라인(BANK24) 창 제어 기본기.

BANK24 는 Delphi VCL + DevExpress 라 `win32` 백엔드를 쓴다. 라벨과 입력칸이
별개 컨트롤이라 **좌표로 짝짓고**, 화면 전환은 창 클래스가 바뀌는 것으로 안다.

여기서는 "찾고·기다리고·값을 넣고 되읽는" 기본기만 둔다. 화면별 절차는
`navigate.py`, 필드 채우기는 `form.py` 가 맡는다.
"""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass

from pywinauto import Desktop
from pywinauto.findwindows import find_elements

BACKEND = "win32"
POLL_INTERVAL = 0.4
DEFAULT_TIMEOUT = 60.0

# 화면별 창 클래스(실물 확인).
LOGIN_CLASS = "TDXLoginDialog"
MAIN_CLASS = "TfrmMain"
LIST_CLASS = "TBnkTop24Main"
FORM_CLASS_PREFIX = "TBNK"      # TBNKKBB24DAMB(국민 담보), TBNKSHG24DAMB(신한 담보)


class UiTimeout(RuntimeError):
    """기다리던 창·컨트롤이 제한 시간 안에 나타나지 않았다."""


class ValueRejected(RuntimeError):
    """값을 넣었는데 되읽기가 일치하지 않는다 — 즉시 멈춘다."""


@dataclass(frozen=True)
class WindowRef:
    handle: int
    class_name: str
    title: str
    pid: int


def find_windows(class_name: str | None = None, pid: int | None = None) -> tuple[WindowRef, ...]:
    """조건에 맞는 최상위 창 목록."""
    try:
        elements = find_elements(backend=BACKEND, top_level_only=True, visible_only=True)
    except Exception:
        return ()
    found = []
    for element in elements:
        name = element.class_name or ""
        if class_name and not name.startswith(class_name):
            continue
        if pid and int(element.process_id or 0) != pid:
            continue
        if not element.handle:
            continue
        found.append(WindowRef(
            handle=int(element.handle),
            class_name=name,
            title=(element.name or "").strip(),
            pid=int(element.process_id or 0),
        ))
    return tuple(found)


def wait_for_window(
    class_name: str,
    *,
    pid: int | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    absent: bool = False,
) -> WindowRef | None:
    """창이 나타날 때까지(또는 `absent=True` 면 사라질 때까지) 기다린다."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        windows = find_windows(class_name, pid)
        if absent and not windows:
            return None
        if not absent and windows:
            return windows[0]
        time.sleep(POLL_INTERVAL)
    state = "사라지지" if absent else "나타나지"
    raise UiTimeout(f"창 {class_name!r} 가 {timeout:.0f}초 안에 {state} 않았습니다.")


def window(handle: int):
    """핸들 → pywinauto 창 래퍼."""
    return Desktop(backend=BACKEND).window(handle=handle)


def launch(loader_cmd: str, *, timeout: float = DEFAULT_TIMEOUT) -> WindowRef:
    """로더로 BANK24 를 띄우고 로그인 창을 기다린다.

    이미 떠 있으면 그대로 쓴다(중복 실행 방지).
    """
    existing = find_windows(MAIN_CLASS) or find_windows(LOGIN_CLASS)
    if existing:
        return existing[0]
    subprocess.Popen(loader_cmd, shell=True)
    return wait_for_window(LOGIN_CLASS, timeout=timeout)


def descendants(handle: int) -> list:
    try:
        return window(handle).descendants()
    except Exception:
        return []


def by_class(handle: int, class_name: str) -> list:
    """클래스가 정확히 일치하는 자손 컨트롤을 **화면 순서(위→아래, 왼→오른쪽)** 로."""
    found = []
    for control in descendants(handle):
        try:
            if control.element_info.class_name == class_name:
                found.append(control)
        except Exception:
            continue
    return sorted(found, key=_position)


def _position(control) -> tuple[int, int]:
    try:
        rect = control.rectangle()
        return (rect.top, rect.left)
    except Exception:
        return (0, 0)


def by_text(handle: int, text: str, class_name: str | None = None):
    """버튼처럼 자기 캡션이 있는 컨트롤 찾기(공백 무시)."""
    target = text.replace(" ", "")
    for control in descendants(handle):
        try:
            if class_name and control.element_info.class_name != class_name:
                continue
            if (control.window_text() or "").replace(" ", "") == target:
                return control
        except Exception:
            continue
    return None


LABEL_CLASSES = ("TcxLabel", "TLabel", "TStaticText")
MAX_LABEL_GAP = 260
MAX_LABEL_ABOVE = 30


def _rect(control):
    try:
        return control.rectangle()
    except Exception:
        return None


def find_by_label(handle: int, label: str, class_name: str | None = None):
    """라벨 텍스트로 입력 컨트롤을 찾는다.

    Delphi 폼은 라벨과 입력칸이 별개 컨트롤이라 연결 정보가 없다. 라벨은 보통
    입력칸 **왼쪽**(없으면 바로 **위**)에 놓이므로 그 관계로 짚는다. 창 위치가
    바뀌어도 동작하도록 절대좌표가 아니라 상대 배치만 쓴다.
    """
    target = label.replace(" ", "")
    controls = descendants(handle)

    anchor = None
    for control in controls:
        try:
            if control.element_info.class_name not in LABEL_CLASSES:
                continue
            if (control.window_text() or "").replace(" ", "") == target:
                anchor = control
                break
        except Exception:
            continue
    if anchor is None:
        return None

    box = _rect(anchor)
    if box is None:
        return None

    candidates = []
    for control in controls:
        try:
            name = control.element_info.class_name
        except Exception:
            continue
        if name in LABEL_CLASSES:
            continue
        if class_name and name != class_name:
            continue
        spot = _rect(control)
        if spot is None:
            continue
        # 같은 줄 + 오른쪽
        if spot.top < box.bottom and box.top < spot.bottom and 0 <= spot.left - box.right <= MAX_LABEL_GAP:
            candidates.append((0, spot.left - box.right, control))
        # 바로 아래
        elif 0 <= spot.top - box.bottom <= MAX_LABEL_ABOVE and spot.left < box.right and box.left < spot.right:
            candidates.append((1, spot.top - box.bottom, control))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][2]


def read(control) -> str:
    for attr in ("get_value", "window_text"):
        try:
            value = getattr(control, attr)()
            if value:
                return str(value).strip()
        except Exception:
            continue
    return ""


def editable(control):
    """DevExpress 편집칸의 **실제 입력창**을 찾는다.

    `TcxTextEdit` 등은 껍데기 컨테이너고, 글자가 들어가는 건 그 안의
    `TcxCustomInnerTextEdit` 이다. 바깥에 쓰면 값이 반영되지 않는다(실측).
    """
    try:
        for child in control.children():
            if "Inner" in (child.element_info.class_name or ""):
                return child
    except Exception:
        pass
    return control


def set_text(control, value: str, *, verify: bool = True) -> None:
    """편집칸을 비우고 값을 넣은 뒤 되읽어 확인한다.

    `type_keys` 는 특수문자(`!`, `+`, `^` …)를 조합키로 해석해 값을 망가뜨리므로
    쓰지 않는다(비밀번호에 `!!` 가 들어간다).
    """
    target = editable(control)
    target.set_focus()
    target.set_edit_text("")
    target.set_edit_text(value)
    if not verify:
        return
    actual = read(target)
    if actual != value:
        raise ValueRejected(f"입력값 불일치: 넣은 값 {value!r} / 읽은 값 {actual!r}")


def click(control) -> None:
    control.click_input()
