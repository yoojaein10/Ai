"""업무구분 라디오('담 보') 선택 진단 — 관리자 권한으로 실행.

어떤 클릭 방식이 실제로 선택을 바꾸는지 확인한다:
  ① 메시지 클릭(control.click) ② set_focus 후 마우스 클릭(click_input)
선택 상태는 UIA SelectionItem.IsSelected 로 읽는다. 출력: reports/diag_radio_<ts>.log
"""
from __future__ import annotations

import io
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "src"))

ts = time.strftime("%Y%m%d_%H%M%S")
log_path = ROOT / "reports" / f"diag_radio_{ts}.log"
log_path.parent.mkdir(exist_ok=True)
log = open(log_path, "w", encoding="utf-8", errors="replace")


def say(msg: str) -> None:
    log.write(msg + "\n")
    log.flush()


from pywinauto import Desktop  # noqa: E402

from bankon.config import load_config  # noqa: E402
from bankon.ui import driver, navigate  # noqa: E402


STATE_SYSTEM_CHECKED = 0x10
BM_GETCHECK = 0x00F0


def _one_state(child: int) -> str:
    """한 라디오 버튼의 선택 상태를 여러 방법으로 읽어 요약한다."""
    parts = []
    try:
        uia = Desktop(backend="uia").window(handle=child).wrapper_object()
        try:
            state = uia.legacy_properties().get("State")
            checked = bool(int(state) & STATE_SYSTEM_CHECKED)
            parts.append(f"legacy={'✔' if checked else '－'}({int(state):#x})")
        except Exception as error:  # noqa: BLE001
            parts.append(f"legacy?{type(error).__name__}")
        try:
            parts.append(f"toggle={uia.get_toggle_state()}")
        except Exception:
            pass
    except Exception as error:  # noqa: BLE001
        parts.append(f"uia?{type(error).__name__}")
    try:
        import ctypes
        parts.append(f"bm={ctypes.windll.user32.SendMessageW(child, BM_GETCHECK, 0, 0)}")
    except Exception:
        pass
    return " ".join(parts)


def radio_states(handle: int) -> list[tuple[str, str]]:
    """업무구분·기간검색 그룹의 (캡션, 상태요약) 목록."""
    states = []
    for control in driver.descendants(handle):
        try:
            if control.element_info.class_name != "TcxCustomRadioGroupButton":
                continue
            caption = (control.window_text() or "").strip()
            states.append((caption, _one_state(int(control.handle))))
        except Exception:
            continue
    return states


def dump(handle: int, tag: str) -> None:
    say(f"--- {tag}")
    for caption, sel in radio_states(handle):
        say(f"    {caption!r}: selected={sel}")


def main() -> int:
    cfg = load_config(None)
    session = navigate.open_app(cfg.loader_cmd, cfg.bankon_user, cfg.bankon_password)
    say(f"메인: {session.main.title} handle={session.main.handle:#x}")
    ok = navigate.select_tab(session, "작성")
    say(f"작성 탭: {ok}")
    handle = session.main.handle

    dump(handle, "초기 상태")

    dambo = driver.by_text(handle, "담보", "TcxCustomRadioGroupButton")
    if dambo is None:
        say("'담보' 라디오를 못 찾음")
        return 1
    say(f"'담보' 발견 rect={dambo.rectangle()}")

    # ① 메시지 클릭 (포그라운드 불필요)
    try:
        dambo.click()
        say("① control.click() (메시지) 호출")
    except Exception as error:  # noqa: BLE001
        say(f"① control.click() 예외: {error!r}")
    time.sleep(1.0)
    dump(handle, "①메시지 클릭 후")

    states = dict(radio_states(handle))
    if "✔" in states.get("담 보", ""):
        say("결론: 메시지 클릭으로 선택됨 — click_input 불필요")
        return 0

    # ② 포그라운드 확보 후 마우스 클릭
    try:
        driver.window(handle).set_focus()
        time.sleep(0.5)
        dambo.click_input()
        say("② set_focus + click_input() 호출")
    except Exception as error:  # noqa: BLE001
        say(f"② 예외: {error!r}")
    time.sleep(1.0)
    dump(handle, "②마우스 클릭 후")

    states = dict(radio_states(handle))
    say(f"결론: 담보 selected={states.get('담 보')}")
    return 0


if __name__ == "__main__":
    try:
        rc = main()
    except Exception:  # noqa: BLE001
        import traceback
        log.write(traceback.format_exc())
        rc = 1
    finally:
        log.close()
    sys.exit(rc)
