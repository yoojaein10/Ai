import sys, time
sys.path.insert(0, r'D:\AI\Claude\Y_BankAuto')
from extract_shinhan import safe_cls, safe_txt, safe_rect
from pywinauto import Desktop, Application
import pyautogui

# 미리보기 창 찾기
preview_win = next((w for w in Desktop(backend='win32').windows()
                    if safe_cls(w) == 'TfrxPreviewForm'), None)
if not preview_win:
    print('미리보기 창 없음'); sys.exit(1)

print(f'hwnd={preview_win.handle:#010x}')

# preview 창만 연결해서 스캔
app32 = Application(backend='win32').connect(handle=preview_win.handle)
win32 = app32.window(handle=preview_win.handle)

print('\n=== TfrxPreviewForm 직계 자식 ===')
try:
    for c in win32.children():
        cls = safe_cls(c)
        txt = safe_txt(c).strip()
        r = safe_rect(c)
        print(f'  cls={cls!r}  txt={txt!r}  rect=({r[0]},{r[1]},{r[2]},{r[3]})')
except Exception as e:
    print(f'오류: {e}')

print('\n=== 모든 descendants ===')
try:
    for c in win32.descendants():
        cls = safe_cls(c)
        txt = safe_txt(c).strip()
        r = safe_rect(c)
        print(f'  cls={cls!r}  txt={txt!r}')
except Exception as e:
    print(f'오류: {e}')

# 창 위치/크기
r = preview_win.rectangle()
print(f'\n창 rect: left={r.left} top={r.top} right={r.right} bottom={r.bottom}')
print(f'툴바 예상 y: {r.top + 30} ~ {r.top + 60}')

# 툴바 영역 스크린샷 (확대)
import pyautogui
toolbar_shot = pyautogui.screenshot(region=(r.left, r.top, r.right-r.left, 70))
toolbar_shot.save(r'D:\AI\Claude\Y_BankAuto\toolbar_zoom.png')
print('툴바 확대: toolbar_zoom.png')
