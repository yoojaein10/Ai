"""메인 그리드 컨텍스트 메뉴 APPS → C 로 의뢰서 출력 열기"""
import sys, time
sys.path.insert(0, r'D:\AI\Claude\Y_BankAuto')
from extract_shinhan import (safe_cls, safe_txt, safe_rect, safe_val,
    force_foreground, _get_main_grid, navigate_and_verify,
    scan_main_grid, parse_scan_results, filter_shinhan_dambo,
    LABEL_CLS, EDIT_CLS)
from pywinauto import Desktop, Application
from pywinauto.keyboard import send_keys
import pyautogui, pyperclip

MAIN_CLS = 'TfrmMain'
main_win = next((w for w in Desktop(backend='win32').windows()
                 if safe_cls(w)==MAIN_CLS and 'BANK24' in safe_txt(w)), None)
if not main_win:
    print('메인창 없음'); sys.exit(1)

# 기존 데이터 스캔
items = scan_main_grid(main_win)
rows  = parse_scan_results(items)
shin  = filter_shinhan_dambo(rows)
print(f'신한은행 담보: {len(shin)}건')
if not shin:
    print('데이터 없음 — apply_filter 필요'); sys.exit(1)

target = shin[0]
print(f'대상: {target.get("의뢰번호")} / {target.get("감정서번호")}')

# 메인 그리드 포커스 후 해당 행으로 이동
navigate_and_verify(main_win, target)
time.sleep(0.3)

force_foreground(main_win.handle, '메인창')
time.sleep(0.3)

# APPS 키 → 컨텍스트 메뉴 열기
print('APPS 키 전송...')
pyautogui.press('apps')
time.sleep(1.5)
pyautogui.screenshot(r'D:\AI\Claude\Y_BankAuto\ctx_menu.png')
print('ctx_menu.png 저장')

# C 키 → 의뢰서 출력
print('C 키 전송...')
pyautogui.press('c')
time.sleep(4.0)

# FastReport 미리보기 확인
preview_win = next((w for w in Desktop(backend='win32').windows()
                    if safe_cls(w) == 'TfrxPreviewForm'), None)
if not preview_win:
    print('미리보기 없음')
    pyautogui.screenshot(r'D:\AI\Claude\Y_BankAuto\after_ctx_c.png')
    print('after_ctx_c.png 저장')
    sys.exit(1)

print(f'미리보기 열림!')

# FastReport에서 텍스트 추출 시도
# TfrxPreview 영역 클릭 후 Ctrl+A, Ctrl+C
app32 = Application(backend='win32').connect(handle=preview_win.handle)
pw = app32.top_window()
for c in pw.children():
    if safe_cls(c) == 'TfrxPreview':
        r = c.rectangle()
        if r.width() > 500:
            pyautogui.click(r.left + 400, r.top + 300)
            time.sleep(0.3)
            break

pyperclip.copy('')
pyautogui.hotkey('ctrl', 'a')
time.sleep(0.3)
pyautogui.hotkey('ctrl', 'c')
time.sleep(0.5)
txt = pyperclip.paste()
print(f'클립보드: {repr(txt[:300])}')

# 우클릭 컨텍스트 메뉴 시도
if preview_win:
    r2 = pw.rectangle()
    pyautogui.rightClick(r2.left + 400, r2.top + 300)
    time.sleep(1.5)
    pyautogui.screenshot(r'D:\AI\Claude\Y_BankAuto\fr_ctx.png')
    print('fr_ctx.png 저장')

    # 메뉴 항목 읽기
    for w in Desktop(backend='win32').windows():
        if '#32768' in safe_cls(w):
            print(f'메뉴 발견: {safe_cls(w)!r}')
            try:
                import ctypes
                user32 = ctypes.windll.user32
                # GetMenuItemCount
                count = user32.GetMenuItemCount(w.handle)
                print(f'  메뉴 항목 수: {count}')
            except: pass
            try:
                a = Application(backend='win32').connect(handle=w.handle)
                for c in a.top_window().descendants():
                    t = safe_txt(c).strip()
                    if t: print(f'  {t!r}')
            except: pass
    pyautogui.press('escape')

pyautogui.press('escape')
print('완료')
