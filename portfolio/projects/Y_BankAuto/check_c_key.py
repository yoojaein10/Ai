"""종합접수 창에서 C 키 의뢰서 출력 재시도"""
import sys, time
sys.path.insert(0, r'D:\AI\Claude\Y_BankAuto')
from extract_shinhan import safe_cls, safe_txt, force_foreground, _find_detail
from pywinauto import Desktop, Application
from pywinauto.keyboard import send_keys
import pyautogui, pyperclip

# 종합접수 창 찾기 (이미 열려있어야 함)
detail_win = _find_detail()
if not detail_win:
    print('종합접수 창 없음 — 먼저 종합접수를 열어야 함')
    sys.exit(1)

print(f'종합접수: {safe_txt(detail_win)!r}  hwnd={detail_win.handle:#010x}')
r = detail_win.rectangle()
print(f'창 위치: left={r.left} top={r.top} right={r.right} bottom={r.bottom}')

# 스크린샷 (C 키 전)
pyautogui.screenshot(r'D:\AI\Claude\Y_BankAuto\before_c.png')
print('before_c.png 저장')

# 여러 방법으로 C 키 시도
force_foreground(detail_win.handle, '종합접수')
time.sleep(0.8)

# 창 내부 클릭 후 C
cx = r.left + (r.right - r.left) // 2
cy = r.top + 50
pyautogui.click(cx, cy)
time.sleep(0.5)

# pyautogui.press
pyautogui.press('c')
time.sleep(4.0)

pyautogui.screenshot(r'D:\AI\Claude\Y_BankAuto\after_c.png')
print('after_c.png 저장')

# 새 창 확인
print('새 창:')
for w in Desktop(backend='win32').windows():
    cls = safe_cls(w)
    ttl = safe_txt(w)
    if w.handle != detail_win.handle:
        if 'TfrxPreviewForm' in cls or '미리보기' in ttl or '의뢰서' in ttl:
            print(f'  *** FastReport: cls={cls!r} title={ttl!r}')
        elif cls.startswith('T') and ttl:
            print(f'  cls={cls!r} title={ttl!r}')

print('완료')
