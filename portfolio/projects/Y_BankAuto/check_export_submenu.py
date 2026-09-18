"""FastReport 우클릭 → 저장(X) 서브메뉴 확인"""
import sys, time
sys.path.insert(0, r'D:\AI\Claude\Y_BankAuto')
from extract_shinhan import safe_cls, safe_txt
from pywinauto import Desktop, Application
import pyautogui

# 미리보기 창 찾기
preview_win = next((w for w in Desktop(backend='win32').windows()
                    if safe_cls(w) == 'TfrxPreviewForm'), None)
if not preview_win:
    print('미리보기 없음'); sys.exit(1)

print(f'미리보기: {safe_txt(preview_win)!r}')
r = preview_win.rectangle()

# 미리보기 문서 중앙 우클릭
cx = r.left + (r.right - r.left) // 2
cy = r.top + 400
pyautogui.rightClick(cx, cy)
time.sleep(1.0)

# 저장(X) 항목 위치 클릭 (메뉴 3번째 항목)
# 메뉴 캡처
pyautogui.screenshot(r'D:\AI\Claude\Y_BankAuto\ctx_menu2.png')

# 저장(X) 항목 클릭 — 메뉴 위치 찾기
import ctypes
user32 = ctypes.windll.user32
hwnd_menu = None
for w in Desktop(backend='win32').windows():
    if '#32768' in safe_cls(w):
        hwnd_menu = w.handle
        wr = w.rectangle()
        print(f'메뉴창: rect={wr}')
        # 저장 항목은 메뉴 상단에서 3번째 (인쇄, 열기, 저장)
        # 각 항목 높이 약 25px, 시작 y + 25*2 = 3번째
        save_y = wr.top + 25*2 + 12   # 3번째 항목 중앙
        save_x = wr.left + wr.width() // 2
        print(f'저장 항목 예상 위치: ({save_x}, {save_y})')
        pyautogui.moveTo(save_x, save_y, duration=0.2)
        time.sleep(0.8)
        pyautogui.screenshot(r'D:\AI\Claude\Y_BankAuto\save_hover.png')
        print('save_hover.png 저장')
        pyautogui.click(save_x, save_y)
        time.sleep(1.0)
        break

# 서브메뉴 스크린샷
pyautogui.screenshot(r'D:\AI\Claude\Y_BankAuto\save_submenu.png')
print('save_submenu.png 저장')

# 서브메뉴 항목 읽기
print('=== 새로 열린 창/메뉴 ===')
for w in Desktop(backend='win32').windows():
    cls = safe_cls(w)
    ttl = safe_txt(w)
    if '#32768' in cls:
        wr = w.rectangle()
        print(f'메뉴: rect={wr}')
        # 서브메뉴 항목 확인
        try:
            count = user32.GetMenuItemCount(w.handle)
            print(f'  항목 수(Win32): {count}')
        except: pass
        # UIA로 항목 읽기
        try:
            app = Application(backend='uia').connect(handle=w.handle)
            for c in app.top_window().descendants():
                t = safe_txt(c).strip()
                if t and len(t) > 1:
                    print(f'  UIA: {t!r}')
        except Exception as e:
            print(f'  UIA 오류: {e}')

pyautogui.press('escape')
pyautogui.press('escape')
print('완료')
