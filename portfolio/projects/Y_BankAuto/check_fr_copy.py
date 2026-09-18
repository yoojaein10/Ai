import sys, time
sys.path.insert(0, r'D:\AI\Claude\Y_BankAuto')
from extract_shinhan import (safe_cls, safe_txt, force_foreground,
    apply_filter, scan_main_grid, parse_scan_results, filter_shinhan_dambo,
    navigate_and_verify, snapshot_detail_handles, open_detail_at_current,
    _find_detail)
from pywinauto import Desktop
from pywinauto.keyboard import send_keys
import pyautogui, pyperclip

MAIN_CLS = 'TfrmMain'
main_win = next((w for w in Desktop(backend='win32').windows()
                 if safe_cls(w)==MAIN_CLS and 'BANK24' in safe_txt(w)), None)
force_foreground(main_win.handle, '메인창')
time.sleep(0.5)

apply_filter(main_win)
time.sleep(2)

items = scan_main_grid(main_win)
rows  = parse_scan_results(items)
shin  = filter_shinhan_dambo(rows)
target = shin[0]
print(f'대상: {target.get("의뢰번호")} / {target.get("감정서번호")}')
navigate_and_verify(main_win, target)
time.sleep(0.3)

existing = _find_detail()
if existing: existing.close(); time.sleep(0.8)
before = snapshot_detail_handles()
detail_win = open_detail_at_current(main_win, before)
if not detail_win: print('종합접수 없음'); sys.exit(1)
time.sleep(1)

# 의뢰서 출력 (C 키)
force_foreground(detail_win.handle, '종합접수')
time.sleep(0.3)
pyautogui.press('c')
time.sleep(3.0)

# FastReport 미리보기 창 찾기
preview_win = next((w for w in Desktop(backend='win32').windows()
                    if safe_cls(w) == 'TfrxPreviewForm'), None)
if not preview_win:
    print('미리보기 없음'); sys.exit(1)
print(f'미리보기 열림: {safe_txt(preview_win)!r}')

# TfrxPreviewWorkspace 클릭 후 Ctrl+A, Ctrl+C
preview_area_rect = None
from pywinauto import Application
app32 = Application(backend='win32').connect(handle=preview_win.handle)
for c in app32.top_window().children():
    if safe_cls(c) == 'TfrxPreviewWorkspace':
        r = c.rectangle()
        if r.width() > 500:  # 실제 뷰어 영역
            preview_area_rect = r
            print(f'뷰어 영역: {r}')
            break

if preview_area_rect:
    cx = preview_area_rect.left + preview_area_rect.width() // 2
    cy = preview_area_rect.top  + preview_area_rect.height() // 2
    pyautogui.click(cx, cy)
    time.sleep(0.5)

# 방법 1: Ctrl+A → Ctrl+C
pyperclip.copy('')
pyautogui.hotkey('ctrl', 'a')
time.sleep(0.3)
pyautogui.hotkey('ctrl', 'c')
time.sleep(0.5)
txt = pyperclip.paste()
print(f'Ctrl+A+C 결과: {txt[:200]!r}')

# 방법 2: 그냥 Ctrl+C
pyperclip.copy('')
pyautogui.hotkey('ctrl', 'c')
time.sleep(0.5)
txt2 = pyperclip.paste()
print(f'Ctrl+C 결과: {txt2[:200]!r}')

# 방법 3: 페이지 전체 텍스트 - FastReport 전용 단축키
for key in ['ctrl+t', 'ctrl+e', 'ctrl+x']:
    pyperclip.copy('')
    k1, k2 = key.split('+')
    pyautogui.hotkey(k1, k2)
    time.sleep(0.5)
    t = pyperclip.paste()
    if t:
        print(f'{key}: {t[:100]!r}')

# 미리보기 닫기
pyautogui.press('escape')
detail_win.close()
print('완료')
