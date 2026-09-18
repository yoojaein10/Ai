"""
미접수 탭 이동 테스트
- Bank24 실행 → 로그인 → 메인창 → 미접수 탭 클릭
"""
import sys, os, time
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

os.environ["BANK24_ID"] = "dbwodls00"
os.environ["BANK24_PW"] = 'REDACTED_CONFIGURE_LOCALLY'

# extract_shinhan 인프라 재사용
sys.path.insert(0, r"D:\AI\Claude\Y_BankAuto")
from extract_shinhan import (
    kill_existing, launch_and_login, wait_main,
    prompt_credentials, _get_main_grid,
    safe_cls, safe_txt, safe_rect,
    _timed_descendants, _all_descendants,
    Desktop, Application, send_keys,
    force_foreground, log
)
import pyautogui

def test_mijeopsu():
    # ── 로그인 ──────────────────────────────────────────────────
    uid = os.environ["BANK24_ID"]
    pwd = os.environ["BANK24_PW"]
    print(f"[TEST] ID: {uid}")

    kill_existing()
    launch_and_login(uid, pwd)
    main_win = wait_main()
    if not main_win:
        print("[ERROR] 메인창 없음"); return

    print(f"[TEST] 메인창 연결 OK: {safe_txt(main_win)!r}")
    time.sleep(1)

    # ── TdxBarControl 목록 ───────────────────────────────────────
    print("\n[TEST] TdxBarControl 스캔")
    bars = []
    try:
        for c in main_win.descendants():
            if safe_cls(c) == "TdxBarControl":
                l, t, r, b = safe_rect(c)
                bars.append((t, l, r, b, c))
    except Exception as e:
        print(f"  오류: {e}")

    bars.sort(key=lambda x: (x[0], x[1]))
    print(f"  TdxBarControl {len(bars)}개")
    for i, (t, l, r, b, c) in enumerate(bars):
        print(f"  [{i}] rect=({l},{t},{r},{b}) w={r-l} h={b-t}")

    # ── UIA로 미접수 탐색 ────────────────────────────────────────
    print("\n[TEST] UIA '미접수' 탐색")
    uia_found = None
    try:
        app_uia = Application(backend="uia").connect(handle=main_win.handle)
        uia_win = app_uia.top_window()
        for c in uia_win.descendants():
            try:
                nm = c.window_text() or ""
                if "미접수" in nm:
                    r = c.rectangle()
                    print(f"  UIA: name={nm!r} class={safe_cls(c)!r} rect=({r.left},{r.top},{r.right},{r.bottom})")
                    uia_found = c
            except: pass
        if not uia_found:
            print("  UIA: 미접수 없음")
    except Exception as e:
        print(f"  UIA 오류: {e}")

    # ── win32 descendants 미접수 탐색 ────────────────────────────
    print("\n[TEST] win32 '미접수' 탐색")
    w32_found = None
    try:
        for c in main_win.descendants():
            txt = safe_txt(c)
            if "미접수" in txt:
                l, t, r, b = safe_rect(c)
                print(f"  w32: text={txt!r} class={safe_cls(c)!r} rect=({l},{t},{r},{b})")
                w32_found = c
    except Exception as e:
        print(f"  w32 오류: {e}")
    if not w32_found:
        print("  win32: 미접수 없음")

    # ── 첫 번째(가장 위) TdxBarControl children 덤프 ─────────────
    if bars:
        t0, l0, r0, b0, bar0 = bars[0]
        print(f"\n[TEST] bars[0] children (rect={l0},{t0},{r0},{b0})")
        try:
            children = bar0.children()
            print(f"  children 수: {len(children)}")
            for i, ch in enumerate(children[:30]):
                cl, ct, cr, cb = safe_rect(ch)
                print(f"  [{i}] class={safe_cls(ch)!r} text={safe_txt(ch)!r} rect=({cl},{ct},{cr},{cb})")
        except Exception as e:
            print(f"  children 오류: {e}")

    # ── UIA 클릭 시도 ─────────────────────────────────────────────
    if uia_found:
        print("\n[TEST] UIA 미접수 클릭 시도")
        try:
            uia_found.click_input()
            time.sleep(1.5)
            print(f"  클릭 후 메인창 title: {safe_txt(main_win)!r}")
            print("  [OK] UIA 클릭 성공")
        except Exception as e:
            print(f"  UIA 클릭 실패: {e}")

    print("\n[TEST] 완료")

if __name__ == "__main__":
    test_mijeopsu()
