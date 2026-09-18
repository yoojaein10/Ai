import sys, time
sys.path.insert(0, r'D:\AI\Claude\Y_BankAuto')
from extract_shinhan import (safe_cls, safe_txt, force_foreground,
    apply_filter, scan_main_grid, parse_scan_results, filter_shinhan_dambo,
    navigate_and_verify, _get_main_grid)
from pywinauto import Desktop, Application
from pywinauto.keyboard import send_keys
import pyautogui, pyperclip

MAIN_CLS = 'TfrmMain'
main_win = next((w for w in Desktop(backend='win32').windows()
                 if safe_cls(w)==MAIN_CLS and 'BANK24' in safe_txt(w)), None)
if not main_win:
    print('메인창 없음'); sys.exit(1)

force_foreground(main_win.handle, '메인창')
time.sleep(0.5)

print('조회 중...')
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
time.sleep(0.2)
pyautogui.press('apps')
time.sleep(2.0)

print('=== 열린 창 목록 ===')
skip = {'TfrmMain','TApplication','TPUtilWindow','Shell_TrayWnd',
        'Progman','WorkerW','MSCTFIME UI','IME',
        'GDI+ Hook Window Class','Xaml_WindowedPopupClass','Notepad'}
for w in Desktop(backend='win32').windows():
    cls = safe_cls(w)
    ttl = safe_txt(w)
    if w.handle == main_win.handle: continue
    if cls in skip: continue
    if not ttl and cls in skip: continue
    print(f'창: cls={cls!r} title={ttl!r}')
    try:
        app = Application(backend='win32').connect(handle=w.handle)
        for c in app.top_window().descendants():
            t = safe_txt(c).strip()
            if t and len(t) >= 2:
                print(f'  win32 [{safe_cls(c)}]: {t!r}')
    except Exception as e:
        print(f'  win32 오류: {e}')
    try:
        app2 = Application(backend='uia').connect(handle=w.handle)
        for c in app2.top_window().descendants():
            t = safe_txt(c).strip()
            if t and len(t) >= 2:
                print(f'  UIA [{safe_cls(c)}]: {t!r}')
    except Exception as e:
        print(f'  UIA 오류: {e}')

pyautogui.press('escape')
print('완료')
