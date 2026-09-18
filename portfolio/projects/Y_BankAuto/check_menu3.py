import sys, time
sys.path.insert(0, r'D:\AI\Claude\Y_BankAuto')
from extract_shinhan import (safe_cls, safe_txt, force_foreground,
    scan_main_grid, parse_scan_results, filter_shinhan_dambo,
    navigate_and_verify, _get_main_grid)
from pywinauto import Desktop
from pywinauto.keyboard import send_keys
import pyautogui, pyperclip

MAIN_CLS = 'TfrmMain'
main_win = next((w for w in Desktop(backend='win32').windows()
                 if safe_cls(w)==MAIN_CLS and 'BANK24' in safe_txt(w)), None)
force_foreground(main_win.handle, '메인창')
time.sleep(0.5)

items = scan_main_grid(main_win)
rows  = parse_scan_results(items)
shin  = filter_shinhan_dambo(rows)
print(f'신한은행 담보: {len(shin)}건')
target = shin[0]
print(f'대상: {target.get("의뢰번호")} / {target.get("감정서번호")}')
navigate_and_verify(main_win, target)
time.sleep(0.5)

force_foreground(main_win.handle, '메인창')
time.sleep(0.3)

print('APPS → 2초 대기 → 스크린샷')
pyautogui.press('apps')
time.sleep(2.0)   # 메뉴 열릴 때까지 충분히 대기
pyautogui.screenshot(r'D:\AI\Claude\Y_BankAuto\menu_open.png')
print('저장: menu_open.png')

# C 키 눌러서 의뢰서 출력창 열기 시도
print('C 키 전송 (의뢰서 출력)')
pyautogui.press('c')
time.sleep(3.0)
pyautogui.screenshot(r'D:\AI\Claude\Y_BankAuto\ireuiseo_window.png')
print('저장: ireuiseo_window.png')

# 열린 창 목록
from pywinauto import Application
print('=== 새 창 목록 ===')
for w in Desktop(backend='win32').windows():
    cls = safe_cls(w)
    ttl = safe_txt(w)
    if w.handle == main_win.handle: continue
    if cls in ('TPUtilWindow','Shell_TrayWnd','Progman','WorkerW',
               'MSCTFIME UI','IME','GDI+ Hook Window Class',
               'Xaml_WindowedPopupClass','TApplication','Notepad',
               'LOGI_RAWINPUT_CLASS','XamlExplorerHostIslandWindow',
               'SystemTray_Main','TopLevelWindowForOverflowXamlIsland'): continue
    print(f'cls={cls!r}  title={ttl!r}')

print('완료')
