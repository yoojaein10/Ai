"""
종합접수 창 스크린샷 + 내부 그리드 컨트롤 덤프
"""
import time
import pyautogui
from pywinauto import Application
from pywinauto.keyboard import send_keys

# bank24 연결 + 첫 행 종합접수 열기
app = Application(backend="win32").connect(class_name="TfrmMain", title_re=".*BANK24.*")
main_win = app.top_window()
main_win.set_focus()
time.sleep(0.3)

grids = [c for c in main_win.descendants() if c.class_name() == "TcxGrid"]
r = grids[0].rectangle()
grids[0].click_input()
time.sleep(0.3)
send_keys("^{HOME}")
time.sleep(0.5)

cx = (r.left + r.right) // 2
pyautogui.rightClick(cx, r.top + 35)
time.sleep(1.0)
pyautogui.press("0")
time.sleep(2.5)

# 스크린샷
pyautogui.screenshot("detail_window.png")
print("스크린샷 저장: detail_window.png")

# 종합접수 창 내부 그리드 덤프
try:
    dapp = Application(backend="win32").connect(class_name="TBnkTop24Rcp", timeout=5)
    dwin = dapp.top_window()
    print(f"\n종합접수 창: '{dwin.window_text()}'")

    # 내부 TcxGrid 찾기
    inner_grids = [c for c in dwin.descendants() if c.class_name() == "TcxGrid"]
    print(f"내부 그리드 수: {len(inner_grids)}")

    for gi, g in enumerate(inner_grids):
        gr = g.rectangle()
        print(f"\n[그리드 {gi}] rect: {gr.left},{gr.top},{gr.right},{gr.bottom}")
        # 그리드 클릭 후 전체 복사
        g.click_input()
        time.sleep(0.3)
        send_keys("^{HOME}")
        time.sleep(0.3)
        send_keys("^+{END}")
        time.sleep(0.3)
        send_keys("^c")
        time.sleep(0.8)
        import pyperclip
        clip = pyperclip.paste()
        print(f"클립보드 내용:\n{clip[:500]}")

except Exception as e:
    print(f"오류: {e}")
