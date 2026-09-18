# -*- coding: utf-8 -*-
"""Y_TSBankAuto 탁상감정 테스트판 진입점 (지시 §14).

- multiprocessing.freeze_support() 와 진입점 보호 적용.
- 인자에 따라 GUI / 격리 PDF worker / selftest 로 분기한다.
  프로즌 EXE 에서 격리 파싱 subprocess 는 자기 자신을 --pdf-worker 로 재실행한다.
- 테스트판: 실제 SP 실행/COMMIT/DB 저장 없음.
"""
from __future__ import annotations

import sys


def _ensure_win32ui_importable() -> None:
    """pywinauto.base_wrapper 는 최상단에서 `import win32ui` 를 **가드 없이** 수행한다
    (스크린샷 capture_as_image 전용). win32ui.pyd 는 MFC 런타임(mfc140u.dll)에 의존하며,
    대상 PC 에 MFC 가 없으면 로드가 실패해 `import pywinauto` 전체가 죽어 창 열거가 불가능해진다
    (ENUMERR_ImportError_win32ui). 이 제품의 읽기전용 경로(로그인·탁상조회)는 스크린샷을
    절대 호출하지 않으므로, 실제 win32ui 로드가 실패할 때만 최소 스텁을 심어 pywinauto 를
    사용 가능하게 한다(기능 손실 없음). MFC 가 있는 PC 에서는 실제 win32ui 를 그대로 쓴다.

    반드시 pywinauto 가 처음 import 되기 전에 실행해야 하므로 진입 최상단에서 호출한다.
    """
    if "win32ui" in sys.modules:
        return
    try:
        import win32ui  # noqa: F401  (MFC 있으면 실제 모듈 사용)
    except Exception:
        import types
        sys.modules["win32ui"] = types.ModuleType("win32ui")


_ensure_win32ui_importable()


def _run_selftest() -> int:
    """제품 자가점검(EXE smoke test용). 실제 Bank24 를 실행하지 않고 fake 도 쓰지 않는다.

    - 핵심 모듈 import 가능 여부
    - decide_adapter 가 fake 로 대체하지 않고 real 또는 blocked(고정경로 존재 여부에 따라)를
      반환하는지 — decide 는 UI/프로세스를 실행하지 않는다.
    - 제품 모듈에 fake adapter 가 없는지, read_only 기본값이 True 인지
    실제 UI/네트워크/DB/Bank24 를 건드리지 않는다.
    """
    import bank24_adapter
    import bank24_automation
    import bank24_backend  # noqa: F401  (번들 포함 확인)
    import bank24_trust    # noqa: F401
    import config

    app = config.AppConfig()   # 기본값(고정 exe 경로 상수)
    decision = bank24_adapter.decide_adapter(
        app_config=app, stop=bank24_automation.EmergencyStop(),
        backend=None, credential_provider=None)
    ok = (decision.mode in ("real", "blocked")           # fake 없음(§53)
          and not hasattr(bank24_adapter, "FakeBank24Adapter")
          and app.options.read_only is True)
    print(f"decide.mode={decision.mode} reason={decision.reason}")
    print("SELFTEST_OK" if ok else "SELFTEST_FAIL")
    return 0 if ok else 1


def _force_utf8_stdout() -> None:
    """콘솔 인코딩(cp949)에서 유니코드 출력 시 크래시 방지."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main(argv: list[str]) -> int:
    _force_utf8_stdout()
    if len(argv) >= 2 and argv[1] == "--selftest":
        return _run_selftest()
    # --legacy-gui 제거(§101): 깨진 tkinter 데모를 실행하지 않는다.
    # --pdf-worker 제거(§102): 읽기 전용 제품은 PDF 다운로드/파싱을 하지 않는다.
    if len(argv) >= 2 and argv[1] in ("--legacy-gui", "--pdf-worker"):
        print(f"지원하지 않는 옵션(안전코드: OPTION_REMOVED): {argv[1]}")
        return 2
    import app_gui                      # 운영형 GUI(PyQt6, 기본 진입점)
    return app_gui.main()


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    raise SystemExit(main(sys.argv))
