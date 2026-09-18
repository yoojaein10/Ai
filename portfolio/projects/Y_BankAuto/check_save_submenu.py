"""APPS → C 로 의뢰서 출력 열고 저장(X) 서브메뉴 확인"""
import sys, time
sys.path.insert(0, r'D:\AI\Claude\Y_BankAuto')
from extract_shinhan import (safe_cls, safe_txt, force_foreground,
    _get_main_grid, scan_main_grid, parse_scan_results,
    filter_shinhan_dambo, navigate_and_verify)
from pywinauto import Desktop, Application
import pyautogui, ctypes

MAIN_CLS = 'TfrmMain'
main_win = next((w for w in Desktop(backend='win32').windows()
                 if safe_cls(w)==MAIN_CLS and 'BANK24' in safe_txt(w)), None)

# 데이터 확인
items = scan_main_grid(main_win)
rows  = parse_scan_results(items)
shin  = filter_shinhan_dambo(rows)
if not shin: print('데이터 없음'); sys.exit(1)

target = shin[0]
print(f'대상: {target.get("의뢰번호")}')
navigate_and_verify(main_win, target)
time.sleep(0.3)

# APPS → C 로 의뢰서 출력
force_foreground(main_win.handle, '메인창')
time.sleep(0.3)
pyautogui.press('apps')
time.sleep(1.5)
pyautogui.press('c')
time.sleep(4.0)

preview_win = next((w for w in Desktop(backend='win32').windows()
                    if safe_cls(w) == 'TfrxPreviewForm'), None)
if not preview_win:
    print('미리보기 없음'); sys.exit(1)
print('미리보기 열림')

# 미리보기 본문 우클릭
pr = preview_win.rectangle()
cx = pr.left + (pr.right - pr.left) // 2
cy = pr.top + 400
pyautogui.rightClick(cx, cy)
time.sleep(1.0)

# 메뉴 위치 찾기
user32 = ctypes.windll.user32
for w in Desktop(backend='win32').windows():
    if '#32768' in safe_cls(w):
        wr = w.rectangle()
        print(f'메뉴 rect: {wr}')
        # 항목 순서: 인쇄(V), 열기(W), 저장(X), 검색(Y), ...
        # 각 항목 높이 약 26px
        items_y = [wr.top + 26*i + 13 for i in range(8)]
        for i, iy in enumerate(items_y[:5]):
            ix = wr.left + wr.width() // 2
            pyautogui.moveTo(ix, iy, duration=0.1)
            time.sleep(0.3)
            # tooltip 확인
            for tw in Desktop(backend='win32').windows():
                if 'THintWindow' in safe_cls(tw):
                    t = safe_txt(tw).strip()
                    if t:
                        print(f'  항목 {i+1} (y={iy}): {t!r}')
        # 저장(X) = 3번째 항목
        save_y = wr.top + 26*2 + 13
        save_x = wr.left + wr.width() // 2
        print(f'\n저장(X) 클릭: ({save_x}, {save_y})')
        pyautogui.click(save_x, save_y)
        time.sleep(1.0)
        break

# 서브메뉴 스크린샷
pyautogui.screenshot(r'D:\AI\Claude\Y_BankAuto\submenu.png')
print('submenu.png 저장')

# 서브메뉴 항목 확인
print('=== 서브메뉴 창 ===')
for w in Desktop(backend='win32').windows():
    cls = safe_cls(w)
    if '#32768' in cls:
        wr = w.rectangle()
        print(f'  메뉴 rect={wr}  크기={wr.width()}x{wr.height()}')
        # UIA descendants
        try:
            a = Application(backend='uia').connect(handle=w.handle)
            for c in a.top_window().descendants():
                t = safe_txt(c).strip()
                if t and len(t) > 1:
                    print(f'    UIA: {t!r}')
        except Exception as e:
            print(f'    오류: {e}')

pyautogui.press('escape')
pyautogui.press('escape')
print('완료')
