"""
Bank24 의뢰서 출력 → FastReport → 우편번호주소 추출 가능성 테스트
"""
import sys, time
sys.path.insert(0, r'D:\AI\Claude\Y_BankAuto')
from extract_shinhan import (safe_cls, safe_txt, force_foreground,
    kill_existing, launch_and_login, wait_main, apply_filter,
    scan_main_grid, parse_scan_results, filter_shinhan_dambo,
    navigate_and_verify, snapshot_detail_handles, open_detail_at_current,
    _find_detail)
from pywinauto import Desktop, Application
from pywinauto.keyboard import send_keys
import pyautogui, pyperclip

# Bank24 재시작
kill_existing()
time.sleep(1)
launch_and_login('dbwodls00', 'REDACTED_CONFIGURE_LOCALLY')

main_win = wait_main()
if not main_win:
    print('메인창 없음'); sys.exit(1)
time.sleep(2)

apply_filter(main_win)
time.sleep(2)

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

existing = _find_detail()
if existing: existing.close(); time.sleep(0.8)
before = snapshot_detail_handles()
detail_win = open_detail_at_current(main_win, before)
if not detail_win: print('종합접수 없음'); sys.exit(1)
time.sleep(1)

# C키로 의뢰서 출력
force_foreground(detail_win.handle, '종합접수')
time.sleep(0.3)
pyautogui.press('c')
time.sleep(3.0)

preview_win = next((w for w in Desktop(backend='win32').windows()
                    if safe_cls(w) == 'TfrxPreviewForm'), None)
if not preview_win:
    print('미리보기 없음'); sys.exit(1)

print(f'미리보기 열림: {safe_cls(preview_win)!r}')

# TfrxPreview 영역 클릭
app32 = Application(backend='win32').connect(handle=preview_win.handle)
pw = app32.top_window()
preview_area = None
for c in pw.children():
    if safe_cls(c) == 'TfrxPreview':
        r = c.rectangle()
        if r.width() > 500:
            preview_area = r
            break

if preview_area:
    cx = preview_area.left + 400
    cy = preview_area.top  + 300
    pyautogui.click(cx, cy)
    time.sleep(0.3)

# 테스트 1: Ctrl+A Ctrl+C
pyperclip.copy('')
pyautogui.hotkey('ctrl', 'a')
time.sleep(0.3)
pyautogui.hotkey('ctrl', 'c')
time.sleep(0.5)
r1 = pyperclip.paste()
print(f'[1] Ctrl+A+C: {r1[:150]!r}')

# 테스트 2: 그냥 Ctrl+C
pyperclip.copy('')
pyautogui.hotkey('ctrl', 'c')
time.sleep(0.5)
r2 = pyperclip.paste()
print(f'[2] Ctrl+C: {r2[:150]!r}')

# 테스트 3: 우클릭 컨텍스트 메뉴 (preview 본문에서 직접)
if preview_area:
    pyautogui.rightClick(preview_area.left + 400, preview_area.top + 300)
    time.sleep(1.5)
    ss = pyautogui.screenshot()
    ss.save(r'D:\AI\Claude\Y_BankAuto\fr_rightclick.png')
    print('우클릭 스크린샷: fr_rightclick.png')

    # 메뉴 항목 확인
    for w in Desktop(backend='win32').windows():
        cls = safe_cls(w)
        if '#32768' in cls or 'TPopup' in cls:
            print(f'메뉴창: {cls!r}')
            try:
                from pywinauto import Application as A
                for c in A(backend='win32').connect(handle=w.handle).top_window().descendants():
                    t = safe_txt(c).strip()
                    if t: print(f'  {t!r}')
            except: pass
    pyautogui.press('escape')

# 닫기
pyautogui.press('escape')
detail_win.close()
print('완료')
