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
import unicodedata
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


class DesktopLocked(RuntimeError):
    """화면이 잠겨 있어 키보드·마우스를 넣을 수 없다."""


def require_desktop() -> None:
    """활성 데스크톱이 있는지 확인한다 — 없으면 무슨 일인지 분명히 알려 준다.

    화면이 잠기거나 원격 세션이 끊기면 `SetCursorPos`·`SendInput` 이 통째로 실패한다.
    그대로 두면 pywinauto 스택트레이스만 나와서 원인을 알기 어렵다.
    """
    try:
        import win32api
        win32api.GetCursorPos()
    except Exception as error:
        raise DesktopLocked(
            "화면이 잠겨 있거나 원격 세션이 끊겨 있습니다. "
            "잠금을 풀고(로그인 화면이면 로그인) 다시 실행하세요."
        ) from error


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

# 값을 넣을 수 있는 컨트롤만 후보로 본다. 패널·그룹박스 같은 **컨테이너를 집으면 엉뚱한
# 칸에 쓰게 된다** — 실측: 농협 `표준지소재지` 가 `TPanel`(금액이 그려진 컨테이너)을 짚어,
# `--overwrite` 였다면 금액 칸 자리에 주소를 타이핑할 뻔했다.
# `Inner*` 는 편집칸의 내부 구현이라 제외한다(`editable()` 이 알아서 내려간다).
INPUT_MARKERS = ("TextEdit", "CurrencyEdit", "DateEdit", "ComboBox", "MaskEdit",
                 "SpinEdit", "CheckBox", "RadioGroup", "Memo", "TimeEdit")


def is_input(class_name: str) -> bool:
    """이 클래스가 값을 넣을 수 있는 입력 컨트롤인가."""
    name = class_name or ""
    if "Inner" in name:
        return False
    return any(marker in name for marker in INPUT_MARKERS)


def _rect(control):
    try:
        return control.rectangle()
    except Exception:
        return None


def label_rank(box, spot):
    """라벨(box) 기준으로 입력칸(spot)이 얼마나 그 라벨의 것인가 — `(순위, 거리)` 또는 None.

    순위 0 = **같은 줄 오른쪽**(가장 흔한 배치), 1 = **바로 아래**. 작을수록 우선.

    같은 줄 판정에 **겹침**이 아니라 **라벨 세로중심이 칸 안에 들어오는지**를 쓴다.
    겹침만 보면 1px 만 스쳐도 같은 줄이 된다 — 실측 국민 `비   고`(라벨 855~871)가 바로
    위 `총세대수` 칸(836~856)과 1px 겹쳐 그 칸을 짚었고, 정작 진짜 비고 칸(873~893)은
    '바로 아래'라 우선순위에서 밀렸다. 중심 조건이면 그 오검출만 사라진다.
    """
    middle = (box.top + box.bottom) // 2
    if spot.top <= middle < spot.bottom and 0 <= spot.left - box.right <= MAX_LABEL_GAP:
        return (0, spot.left - box.right)
    if (0 <= spot.top - box.bottom <= MAX_LABEL_ABOVE
            and spot.left < box.right and box.left < spot.right):
        return (1, spot.top - box.bottom)
    return None


def find_by_label(handle: int, label: str, class_name: str | None = None):
    """라벨 텍스트로 입력 컨트롤을 찾는다.

    Delphi 폼은 라벨과 입력칸이 별개 컨트롤이라 연결 정보가 없다. 라벨은 보통
    입력칸 **왼쪽**(없으면 바로 **위**)에 놓이므로 그 관계로 짚는다. 창 위치가
    바뀌어도 동작하도록 절대좌표가 아니라 상대 배치만 쓴다.

    후보는 **입력 컨트롤로 한정**한다(`is_input`) — 패널·그룹박스를 집으면 값을 엉뚱한
    자리에 쓴다. 못 찾으면 None 을 돌려주는 편이 안전하다(호출측이 '미발견'으로 남긴다).
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
        if name in LABEL_CLASSES or not is_input(name):
            continue
        if class_name and name != class_name:
            continue
        spot = _rect(control)
        if spot is None:
            continue
        rank = label_rank(box, spot)
        if rank is not None:
            candidates.append((rank[0], rank[1], control))
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
    # 금액칸(TcxDBCurrencyEdit)은 입력값 `22021000000` 을 `22,021,000,000` 으로 되포맷해
    # 표시하므로, 되읽기 대조는 **콤마·공백을 무시**한다(포맷차는 통과, 값차는 잡는다).
    if _readback_norm(actual) != _readback_norm(value):
        raise ValueRejected(f"입력값 불일치: 넣은 값 {value!r} / 읽은 값 {actual!r}")


def _readback_norm(text: str) -> str:
    """되읽기 대조용 정규화 — 콤마·하이픈·모든 공백 제거(포맷차 무시, 내용은 보존).

    금액칸은 `22,021,000,000` 로, 계좌·전화 마스크칸은 `103-910016-91404` 로 되포맷하므로
    콤마·하이픈을 무시해야 우리가 넣은 숫자열과 표시값이 같게 대조된다.
    """
    return re.sub(r"\s+", "", (text or "").replace(",", "").replace("-", ""))


def click(control) -> None:
    control.click_input()


_COMBO_CODE = re.compile(r"\((\d+)\)\s*$")     # 콤보 표시값 뒤의 내부코드 `박용준(3056)`
DROPDOWN_WAIT = 0.45
STEP_WAIT = 0.08
JUMP_WAIT = 0.35        # 여러 칸을 한 번에 보낸 뒤 그리드가 자리잡을 때까지
STALL_LIMIT = 3


def combo_text(text: str) -> str:
    """콤보 비교용 표기 — 내부코드·공백·전각을 없앤다."""
    folded = unicodedata.normalize("NFKC", text or "")
    return _COMBO_CODE.sub("", folded).replace(" ", "").strip()


def _commit(control, target: str, value: str) -> bool:
    """지금 표시값이 목표면 Enter 로 확정하고 되읽어 확인한다."""
    if combo_text(read(control)) != target:
        return False
    control.type_keys("{ENTER}")
    time.sleep(DROPDOWN_WAIT)
    actual = read(control)
    if combo_text(actual) != target:
        raise ValueRejected(f"콤보 확정 실패: 고른 값 {value!r} / 읽은 값 {actual!r}")
    return True


def _jump(control, target: str, items) -> bool:
    """목록에서 목표의 **순번을 계산해 한 번에 이동**한다(맞으면 True).

    한 칸씩 훑으면 항목 수에 비례해 느리다(77개 = 22초). 목록을 알면 `{UP n}` 으로 맨 위에
    붙였다가 `{DOWN i}` 로 건너뛰면 두 번의 키 전송으로 끝난다.

    목록이 낡아 순서가 어긋날 수 있으므로 **이동 후 표시값을 확인**하고, 다르면 False 를
    돌려 호출측이 훑기로 물러선다. 그래서 목록이 틀려도 엉뚱한 항목이 확정되지 않는다.
    """
    index = next((i for i, item in enumerate(items) if combo_text(item) == target), None)
    if index is None:
        return False
    control.type_keys("{UP %d}" % (len(items) + 2))     # 맨 위에 붙인다(넘치면 멈춘다)
    time.sleep(JUMP_WAIT)
    if index:
        control.type_keys("{DOWN %d}" % index)
        time.sleep(JUMP_WAIT)
    return combo_text(read(control)) == target


def select_item(control, value: str, *, limit: int = 400, force: bool = False,
                items=None) -> bool:
    """콤보에서 표시값이 `value` 인 항목을 고른다. 못 찾으면 **원래 값 그대로** 두고 False.

    DevExpress 드롭다운은 항목이 그려진 픽셀이라 목록을 읽을 수 없다(확인함). 대신
    `F4` 로 열고 방향키로 옮기면 편집칸 표시값이 바뀌므로 그걸 읽어 맞는 항목을 찾는다.

      · 찾으면 **Enter** 로 확정하고 되읽어 검증한다.
      · 못 찾으면 **ESC** — ESC 는 선택을 취소하므로 원래 값이 남는다. 끝에서 확인한다.

    표시값에 내부코드가 붙어 있어(`박용준(3056)`) 비교는 코드를 뗀 뒤에 한다.

    `force=True` 면 **이미 그 값이어도** 드롭다운을 열어 끝까지 돌린다. 값이 안 바뀌는
    상태에서 열기·훑기·Enter 확정을 통째로 시험할 때 쓴다(운영 경로는 쓰지 않는다).
    """
    target = combo_text(str(value))
    if not target:
        return False
    before = read(control)
    if combo_text(before) == target and not force:
        return True                                   # 이미 그 값

    control.set_focus()
    control.type_keys("{F4}")
    time.sleep(DROPDOWN_WAIT)
    try:
        # 1) 목록을 알면 순번으로 한 번에 건너뛴다(빠른 길).
        if items and _jump(control, target, items) and _commit(control, target, value):
            return True

        # 2) 목록이 없거나 순서가 어긋나면 한 칸씩 훑는다(확실한 길).
        #    맨 위로 — {HOME} 은 편집칸 커서에 먹혀서 목록이 안 움직인다.
        top, stall = None, 0
        for _ in range(limit):
            current = read(control)
            if current != top:
                top, stall = current, 0
            else:
                stall += 1
                if stall >= STALL_LIMIT:
                    break
            control.type_keys("{UP}")
            time.sleep(STEP_WAIT)

        seen, stall = None, 0
        for _ in range(limit):
            current = read(control)
            if combo_text(current) == target:
                return _commit(control, target, value)
            if current != seen:
                seen, stall = current, 0
            else:
                stall += 1
                if stall >= STALL_LIMIT:
                    break
            control.type_keys("{DOWN}")
            time.sleep(STEP_WAIT)
    finally:
        if combo_text(read(control)) != target:       # 아직 확정 안 됐으면 취소
            try:
                control.type_keys("{ESC}")
                time.sleep(0.25)
            except Exception:
                pass

    restored = read(control)
    if restored != before:
        raise ValueRejected(f"콤보 취소 실패: {before!r} → {restored!r} 로 바뀜")
    return False
