import sys, time
sys.path.insert(0, r'D:\AI\Claude\Y_BankAuto')
from extract_shinhan import safe_cls, safe_txt, safe_rect
from pywinauto import Desktop, Application
import pyautogui

preview_win = next((w for w in Desktop(backend='win32').windows()
                    if safe_cls(w) == 'TfrxPreviewForm'), None)
if not preview_win:
    print('미리보기 없음'); sys.exit(1)

# 창 rect
wr = preview_win.rectangle()
print(f'창: left={wr.left} top={wr.top}')

# 툴바 버튼 위치 (스크린 좌표)
# TToolBar rect=(0,23,1920,54) -> 스크린 y 약 38
toolbar_y = 38
# 버튼들 x 위치 탐색 (각 버튼 약 19px 간격, 시작 약 x=5)
btn_positions = []
for i in range(10):
    btn_positions.append(5 + i * 19)

print('버튼 위치 예상 (스크린 x):', btn_positions[:8])

# 각 버튼 위에 마우스를 올려 tooltip 확인
for i, bx in enumerate(btn_positions[:8]):
    pyautogui.moveTo(bx, toolbar_y, duration=0.1)
    time.sleep(0.4)
    # 툴팁 확인
    for w in Desktop(backend='win32').windows():
        cls = safe_cls(w)
        if 'tooltip' in cls.lower() or 'Tooltip' in cls or 'hint' in cls.lower():
            ttl = safe_txt(w).strip()
            if ttl:
                print(f'  버튼 {i+1} (x={bx}): tooltip={ttl!r}')

# 스크린샷 찍기 (현재 상태)
pyautogui.screenshot(r'D:\AI\Claude\Y_BankAuto\toolbar_hover.png')
print('저장: toolbar_hover.png')

# 3번째 버튼 클릭 (export to file 예상)
print('\n3번째 버튼 클릭 시도 (x=43)...')
pyautogui.click(43, toolbar_y)
time.sleep(1.5)
pyautogui.screenshot(r'D:\AI\Claude\Y_BankAuto\after_btn3.png')
print('저장: after_btn3.png')

# 열린 다이얼로그/메뉴 확인
print('\n=== 새 창/다이얼로그 ===')
skip = {'TfrxPreviewForm','TfrmMain','TApplication','TPUtilWindow',
        'Shell_TrayWnd','Progman','WorkerW','MSCTFIME UI','IME',
        'GDI+ Hook Window Class','Xaml_WindowedPopupClass',
        'LOGI_RAWINPUT_CLASS','XamlExplorerHostIslandWindow',
        'SystemTray_Main','TopLevelWindowForOverflowXamlIsland',
        'ForegroundStaging','ThumbnailDeviceHelperWnd','Notepad'}
for w in Desktop(backend='win32').windows():
    cls = safe_cls(w)
    ttl = safe_txt(w)
    if cls not in skip and (ttl or cls not in skip):
        print(f'  cls={cls!r}  title={ttl!r}')
        try:
            app = Application(backend='win32').connect(handle=w.handle)
            for c in app.top_window().descendants():
                t = safe_txt(c).strip()
                if t and len(t) > 1:
                    print(f'    [{safe_cls(c)}] {t!r}')
        except: pass

# ESC로 닫기
import pyautogui
pyautogui.press('escape')
