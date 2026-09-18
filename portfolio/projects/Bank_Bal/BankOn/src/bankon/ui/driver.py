"""뱅크온라인(BANK24) 창 제어 기본기.

BANK24 는 Delphi VCL + DevExpress 라 `win32` 백엔드를 쓴다. 라벨과 입력칸이
별개 컨트롤이라 **좌표로 짝짓고**, 화면 전환은 창 클래스가 바뀌는 것으로 안다.

여기서는 "찾고·기다리고·값을 넣고 되읽는" 기본기만 둔다. 화면별 절차는
`navigate.py`, 필드 채우기는 `form.py` 가 맡는다.
"""
from __future__ import annotations

import re
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

# `TfrmMain` 은 Delphi 기본 이름이라 다른 앱(ApWorks 등)과 겹친다(실측) —
# 메인 창은 반드시 제목 힌트로도 걸러야 한다.
MAIN_TITLE_HINTS = ("BANK24", "금융기관온라인")


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


def find_windows(
    class_name: str | None = None,
    pid: int | None = None,
    title_any: tuple[str, ...] | None = None,
) -> tuple[WindowRef, ...]:
    """조건에 맞는 최상위 창 목록. `title_any` 를 주면 제목에 그중 하나는 있어야 한다."""
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
        if title_any and not any(hint in (element.name or "") for hint in title_any):
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
    title_any: tuple[str, ...] | None = None,
) -> WindowRef | None:
    """창이 나타날 때까지(또는 `absent=True` 면 사라질 때까지) 기다린다."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        windows = find_windows(class_name, pid, title_any)
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
    existing = (find_windows(MAIN_CLASS, title_any=MAIN_TITLE_HINTS)
                or find_windows(LOGIN_CLASS))
    if existing:
        return existing[0]
    subprocess.Popen(loader_cmd, shell=True)
    return wait_for_window(LOGIN_CLASS, timeout=timeout)


def bring_to_front(handle: int, *, tries: int = 3) -> bool:
    """창을 확실히 맨 앞으로 — 최소화 복원 + 포그라운드 잠금 우회.

    로그인 뒤 메인 창이 GUI/콘솔 뒤로 숨는 문제(2026-08-27 실측). Windows 는 다른 프로세스가
    포그라운드를 뺏는 걸 막으므로(SetForegroundWindow 잠금) ① 포그라운드 스레드에 입력을
    붙이고(AttachThreadInput) ② ALT 키를 한 번 눌러 잠금을 풀고 ③ SetForegroundWindow /
    BringWindowToTop 를 순서대로 시도한다. 성공 여부는 GetForegroundWindow 로 확인.
    """
    import ctypes
    from ctypes import wintypes

    u32 = ctypes.windll.user32
    k32 = ctypes.windll.kernel32
    SW_RESTORE, SW_SHOW = 9, 5
    VK_MENU, KEYEVENTF_KEYUP = 0x12, 0x0002
    for _ in range(tries):
        try:
            if u32.IsIconic(handle):
                u32.ShowWindow(handle, SW_RESTORE)
            else:
                u32.ShowWindow(handle, SW_SHOW)
            fg = u32.GetForegroundWindow()
            if fg == handle:
                return True
            cur = k32.GetCurrentThreadId()
            fg_tid = u32.GetWindowThreadProcessId(fg, None) if fg else 0
            tgt_tid = u32.GetWindowThreadProcessId(handle, None)
            attached = []
            for tid in {fg_tid, tgt_tid} - {0, cur}:
                if u32.AttachThreadInput(cur, tid, True):
                    attached.append(tid)
            try:
                u32.keybd_event(VK_MENU, 0, 0, 0)
                u32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
                u32.BringWindowToTop(handle)
                u32.SetForegroundWindow(handle)
                u32.SetActiveWindow(handle)
            finally:
                for tid in attached:
                    u32.AttachThreadInput(cur, tid, False)
            time.sleep(0.3)
            if u32.GetForegroundWindow() == handle:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return u32.GetForegroundWindow() == handle


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


def _visible(control) -> bool:
    try:
        return bool(control.is_visible())
    except Exception:
        return True


def _in_region(handle: int, control, region: tuple[int, int] | None) -> bool:
    """region=(left_min, left_max): 창 왼쪽 기준 상대 x 범위. 국민 폼처럼 같은 라벨(본번지·일련번호)이
    물건 패널과 세부내역 패널에 둘 다 있을 때 패널로 가른다(2026-08-26)."""
    if region is None:
        return True
    spot = _rect(control)
    base = _rect(window(handle))
    if spot is None or base is None:
        return False
    x = spot.left - base.left
    return region[0] <= x < region[1]


def find_by_label(handle: int, label: str, class_name: str | None = None, index: int = 0,
                  region: tuple[int, int] | None = None):
    """라벨 텍스트로 입력 컨트롤을 찾는다. `index`는 같은 줄 오른쪽 후보 중 몇 번째(0부터).
    보이지 않는 컨트롤은 라벨·후보 모두에서 뺀다(국민 세부내역 패널은 종류 라디오에 따라 숨은 칸이 남아 있다).

    라벨 하나에 콤보가 둘 붙는 칸(신한 평가사명1: 왼쪽 빈 콤보 + 오른쪽 이름 콤보)은
    index=1 로 오른쪽 것을 집는다(2026-08-25 발송완료 실물로 확인).

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
                if not _visible(control) or not _in_region(handle, control, region):
                    continue
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
        if "Inner" in name:
            # 안쪽 에디트는 바깥 컨트롤과 같은 자리라 후보를 중복시켜 index 가 어긋난다(평가사명1@2 가
            # 첫 콤보의 안쪽 에디트를 집던 사고, 2026-08-25). 쓰기는 editable() 이 안쪽을 다시 찾는다.
            continue
        if class_name and name != class_name:
            continue
        if not _visible(control):
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
    if index:
        same_row = [c for c in candidates if c[0] == 0]
        return same_row[index][2] if index < len(same_row) else None
    return candidates[0][2]


def find_by_offset(handle: int, anchor_label: str, dx: int, dy: int,
                   class_name: str | None = None, tolerance: int = 8,
                   region: tuple[int, int] | None = None):
    """라벨 없는 칸: 기준 라벨의 입력칸(anchor) 좌상단에서 (dx, dy)만큼 떨어진 컨트롤.

    신한 폼 주소칸(정찰표 fields_shinhan_damb.md, 물건순번 칸 기준): 시군구코드 (0,+153) ·
    읍면동코드 (+55,+153) · 소재지 (-126,+176). 창 위치와 무관한 상대 배치.
    """
    anchor = find_by_label(handle, anchor_label, region=region)
    if anchor is None:
        return None
    base = _rect(anchor)
    if base is None:
        return None
    want_left, want_top = base.left + dx, base.top + dy
    best, best_d = None, None
    for control in descendants(handle):
        try:
            name = control.element_info.class_name or ""
        except Exception:
            continue
        if name in LABEL_CLASSES or "Inner" in name:
            continue
        if class_name and name != class_name:
            continue
        if not _visible(control):
            continue
        spot = _rect(control)
        if spot is None:
            continue
        d = abs(spot.left - want_left) + abs(spot.top - want_top)
        if d <= tolerance * 2 and (best_d is None or d < best_d):
            best, best_d = control, d
    return best


def read(control) -> str:
    for attr in ("get_value", "window_text"):
        try:
            value = getattr(control, attr)()
            if value:
                return str(value).strip()
        except Exception:
            continue
    return ""


INPUT_MARKERS = ("TextEdit", "CurrencyEdit", "DateEdit", "ComboBox", "MaskEdit",
                 "SpinEdit", "CheckBox", "RadioGroup", "Memo", "TimeEdit")


def is_input(class_name: str) -> bool:
    """이 클래스가 값을 넣을 수 있는 입력 컨트롤인가(라벨 사이 밴드 수집용, 농협 이식 2026-09-07)."""
    name = class_name or ""
    if "Inner" in name:
        return False
    return any(marker in name for marker in INPUT_MARKERS)


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
    # 마스크칸(하나·우리 계좌번호 TcxDBMaskEdit)은 입력한 숫자열 `10391001691404` 를 `103-910016-91404` 로
    # 되포맷해 표시하므로 되읽기 대조는 **하이픈·콤마·공백을 무시**한다(포맷차는 통과, 값차는 잡는다 — 인계본 실측 2722, 이식 2026-09-10).
    if actual != value and _readback_norm(actual) != _readback_norm(value):
        raise ValueRejected(f"입력값 불일치: 넣은 값 {value!r} / 읽은 값 {actual!r}")


def _readback_norm(text: str) -> str:
    """되읽기 대조용 정규화 — 콤마·하이픈·모든 공백 제거(포맷차 무시, 내용은 보존)."""
    return re.sub(r"\s+", "", (text or "").replace(",", "").replace("-", ""))


def click(control) -> None:
    control.click_input()


BM_CLICK = 0x00F5


def click_message(control) -> None:
    """BM_CLICK 메시지로 클릭 — 포그라운드 불필요.

    DevExpress 라디오(TcxCustomRadioGroupButton)는 `click_input()` 이 포커스만 옮기고
    선택을 못 바꾼다(실측 2026-08-24, diag_radio2 스크린샷 판독). BM_CLICK 은 선택까지
    바뀌는 것을 확인했다. 라디오·체크박스류는 이걸 쓴다.
    """
    import ctypes

    ctypes.windll.user32.SendMessageW(int(control.handle), BM_CLICK, 0, 0)
