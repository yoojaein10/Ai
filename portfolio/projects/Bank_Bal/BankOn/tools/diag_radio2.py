"""업무구분 라디오 클릭 방법 판정 v2 — 스크린샷 판독 방식. 관리자 권한 실행.

상태 비트를 못 읽으므로, 방법마다 **다른 라디오**를 눌러 두고 그룹 스크린샷으로
어떤 방법이 실제 선택을 바꿨는지 본다:
  A. click_input 좌측(라디오 원 위치) → '탁 상'
  B. BM_CLICK 메시지            → '동산담보'
  C. 포커스 + 스페이스 키        → '담 보'   (최종적으로 담보로 남기기 위해 마지막)
산출물: reports/diag2_<ts>_*.png + .log
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "src"))

ts = time.strftime("%Y%m%d_%H%M%S")
reports = ROOT / "reports"
reports.mkdir(exist_ok=True)
log = open(reports / f"diag2_{ts}.log", "w", encoding="utf-8", errors="replace")


def say(msg: str) -> None:
    log.write(msg + "\n")
    log.flush()


import ctypes  # noqa: E402

from pywinauto.keyboard import send_keys  # noqa: E402

from bankon.config import load_config  # noqa: E402
from bankon.ui import driver, navigate  # noqa: E402

BM_CLICK = 0x00F5


def main() -> int:
    cfg = load_config(None)
    session = navigate.open_app(cfg.loader_cmd, cfg.bankon_user, cfg.bankon_password)
    handle = session.main.handle
    say(f"메인: {session.main.title}")
    say(f"작성 탭: {navigate.select_tab(session, '작성')}")

    main_win = driver.window(handle)
    main_win.set_focus()
    time.sleep(0.7)

    group = driver.by_text(handle, "업무구분", "TcxRadioGroup")
    if group is None:
        say("업무구분 그룹을 못 찾음")
        return 1

    def snap(tag: str) -> None:
        path = reports / f"diag2_{ts}_{tag}.png"
        try:
            group.capture_as_image().save(str(path))
            say(f"스냅샷: {path.name}")
        except Exception as error:  # noqa: BLE001
            say(f"스냅샷 실패({tag}): {error!r}")

    def radio(text: str):
        control = driver.by_text(handle, text, "TcxCustomRadioGroupButton")
        if control is None:
            say(f"라디오 {text!r} 못 찾음")
        return control

    snap("0_init")

    # A. click_input — 좌측 라디오 원 위치(상대 좌표) → 탁상
    taksang = radio("탁상")
    if taksang is not None:
        try:
            main_win.set_focus()
            time.sleep(0.3)
            taksang.click_input(coords=(9, 9), absolute=False)
            say("A: 탁상 click_input(좌측) 호출")
        except Exception as error:  # noqa: BLE001
            say(f"A 예외: {error!r}")
        time.sleep(0.8)
        snap("1_after_A_click_input")

    # B. BM_CLICK 메시지 → 동산담보
    dongsan = radio("동산담보")
    if dongsan is not None:
        try:
            ctypes.windll.user32.SendMessageW(int(dongsan.handle), BM_CLICK, 0, 0)
            say("B: 동산담보 BM_CLICK 전송")
        except Exception as error:  # noqa: BLE001
            say(f"B 예외: {error!r}")
        time.sleep(0.8)
        snap("2_after_B_bmclick")

    # C. 포커스 + 스페이스 → 담보 (최종 상태를 담보로)
    dambo = radio("담보")
    if dambo is not None:
        try:
            main_win.set_focus()
            time.sleep(0.3)
            dambo.set_focus()
            time.sleep(0.3)
            send_keys("{SPACE}")
            say("C: 담보 set_focus + SPACE")
        except Exception as error:  # noqa: BLE001
            say(f"C 예외: {error!r}")
        time.sleep(0.8)
        snap("3_after_C_space")

    say("완료 — 스냅샷 4장 판독 필요")
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
