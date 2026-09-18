"""
종합접수 창 열기 테스트
- bank24.exe 실행 중 + 조회 결과 그리드가 보이는 상태에서 실행
- 첫 번째 행에서 컨텍스트 메뉴 → 접수(열람) 열리는지 확인
"""
import time
import pyautogui
from pywinauto import Application, Desktop
from pywinauto.keyboard import send_keys

def main():
    # 1. 메인 창 연결
    print("[1] bank24 메인 창 연결 중...")
    try:
        app = Application(backend="win32").connect(
            class_name="TfrmMain", title_re=".*BANK24.*"
        )
        main_win = app.top_window()
        print(f"    OK: {main_win.window_text()}")
    except Exception as e:
        print(f"    FAIL: {e}")
        return

    # 2. 그리드 포커스
    print("[2] 그리드 포커스...")
    grid_focused = False
    for cls in ("TcxGrid", "TDBGrid", "TStringGrid"):
        grids = [c for c in main_win.descendants() if c.class_name() == cls]
        if grids:
            grids[0].click_input()
            grid_focused = True
            print(f"    OK ({cls})")
            break

    if not grid_focused:
        print("    FAIL: 그리드 못 찾음")
        return

    time.sleep(0.3)

    # 3. 첫 행으로 이동
    print("[3] Ctrl+Home → 첫 행 이동")
    send_keys("^{HOME}")
    time.sleep(0.5)

    # 4. bank24 포그라운드로 올리고 → 첫 행 우클릭 → '0' 단축키
    print("[4] bank24 포그라운드 → 첫 행 우클릭 → '0' 단축키")
    try:
        main_win.set_focus()
        time.sleep(0.5)

        grids = [c for c in main_win.descendants() if c.class_name() == "TcxGrid"]
        r = grids[0].rectangle()
        print(f"    그리드 rect: left={r.left} top={r.top} right={r.right} bottom={r.bottom}")

        cx = (r.left + r.right) // 2
        first_row_y = r.top + 35
        print(f"    우클릭 위치: ({cx}, {first_row_y})")

        pyautogui.rightClick(cx, first_row_y)
        time.sleep(1.5)

        print("    '0' 단축키 입력")
        pyautogui.press("0")
        time.sleep(3.0)
    except Exception as e:
        print(f"    FAIL: {e}")
        return

    # 6. TBnkTop24Rcp 창 열렸는지 확인
    print("[6] 종합접수 창(TBnkTop24Rcp) 확인...")
    try:
        dapp = Application(backend="win32").connect(class_name="TBnkTop24Rcp", timeout=5)
        dwin = dapp.top_window()
        print(f"    OK! 타이틀='{dwin.window_text()}' / 클래스='{dwin.element_info.class_name}'")
        dwin.close()
        print("    창 닫기 완료")
    except Exception as e:
        print(f"    FAIL: {e}")
        print("    → 컨텍스트 메뉴가 안 열렸거나 다른 창이 열렸을 수 있음")

        # 현재 열린 창 전체 다시 확인
        print("\n    현재 열린 창 (bank24 관련):")
        for w in Desktop(backend="win32").windows():
            t = w.window_text().strip()
            c = w.element_info.class_name
            if t and ("TBnk" in c or "Tfr" in c or "접수" in t):
                print(f"      타이틀='{t}' / 클래스='{c}'")

if __name__ == "__main__":
    main()
