import sys, time
sys.path.insert(0, r'D:\AI\Claude\Y_BankAuto')
from extract_shinhan import (safe_cls, safe_txt, force_foreground,
    apply_filter, scan_main_grid, parse_scan_results, filter_shinhan_dambo,
    navigate_and_verify, _get_main_grid)
from pywinauto import Desktop
from pywinauto.keyboard import send_keys
import pyautogui, pyperclip
from pathlib import Path

MAIN_CLS = 'TfrmMain'
main_win = next((w for w in Desktop(backend='win32').windows()
                 if safe_cls(w)==MAIN_CLS and 'BANK24' in safe_txt(w)), None)
if not main_win:
    print('메인창 없음'); sys.exit(1)

force_foreground(main_win.handle, '메인창')
time.sleep(0.5)

# 이미 데이터가 있으면 재조회 스킵, 없으면 조회
grid = _get_main_grid(main_win)
grid.click_input(); time.sleep(0.2)
send_keys('^{HOME}'); time.sleep(0.2)
send_keys('{DOWN}'); time.sleep(0.2)
pyperclip.copy('')
send_keys('^c'); time.sleep(0.4)
val = pyperclip.paste()

if '신한은행' not in val and '은  행' in val:
    print('데이터 없음 — 조회 실행')
    apply_filter(main_win)
    time.sleep(3)

items = scan_main_grid(main_win)
rows  = parse_scan_results(items)
shin  = filter_shinhan_dambo(rows)
print(f'신한은행 담보: {len(shin)}건')
if not shin:
    print('데이터 없음'); sys.exit(0)

target = shin[0]
print(f'대상: {target.get("의뢰번호")} / {target.get("감정서번호")}')
navigate_and_verify(main_win, target)
time.sleep(0.3)
force_foreground(main_win.handle, '메인창')
time.sleep(0.3)

# 1) APPS 키 → 스크린샷
print('APPS 키 전송...')
pyautogui.press('apps')
time.sleep(1.2)
ss_path = r'D:\AI\Claude\Y_BankAuto\menu_screenshot.png'
pyautogui.screenshot(ss_path)
print(f'스크린샷 저장: {ss_path}')

# 2) 메뉴 아이템 키보드로 읽기 시도
# win32 api로 foreground 메뉴 핸들 조회
import ctypes
user32 = ctypes.windll.user32
hmenu = user32.GetMenu(main_win.handle)
print(f'GetMenu: {hmenu}')

# popup menu handle
hpopup = user32.GetSystemMenu(main_win.handle, False)
print(f'SystemMenu: {hpopup}')

time.sleep(0.5)
pyautogui.press('escape')
print('완료')
