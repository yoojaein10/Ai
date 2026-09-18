import sys, time
sys.path.insert(0, r'D:\AI\Claude\Y_BankAuto')
from extract_shinhan import safe_cls, safe_txt, safe_rect
from pywinauto import Desktop, Application
import pyautogui

# 혹시 열린 다이얼로그 닫기
for w in Desktop(backend='win32').windows():
    ttl = safe_txt(w)
    cls = safe_cls(w)
    if '열기' in ttl or '저장' in ttl or 'Open' in ttl:
        print(f'열린 다이얼로그 닫기: {ttl!r}')
        pyautogui.press('escape')
        time.sleep(0.5)
        break

preview_win = next((w for w in Desktop(backend='win32').windows()
                    if safe_cls(w) == 'TfrxPreviewForm'), None)
if not preview_win:
    print('미리보기 없음'); sys.exit(1)

# 저장 버튼 클릭 (x=62, toolbar y≈38)
print('저장 버튼 클릭 (x=62)...')
pyautogui.click(62, 38)
time.sleep(2.0)

pyautogui.screenshot(r'D:\AI\Claude\Y_BankAuto\after_save_btn.png')
print('저장: after_save_btn.png')

# 열린 다이얼로그 확인
print('\n=== 새 창/다이얼로그 ===')
for w in Desktop(backend='win32').windows():
    cls = safe_cls(w)
    ttl = safe_txt(w)
    skip = {'TfrxPreviewForm','TfrmMain','TApplication','TPUtilWindow',
            'Shell_TrayWnd','Progman','WorkerW','MSCTFIME UI','IME',
            'GDI+ Hook Window Class','Xaml_WindowedPopupClass',
            'LOGI_RAWINPUT_CLASS','XamlExplorerHostIslandWindow',
            'SystemTray_Main','TopLevelWindowForOverflowXamlIsland',
            'ForegroundStaging','ThumbnailDeviceHelperWnd','Notepad',
            'tooltips_class32','Auto-Suggest Dropdown'}
    if cls in skip: continue
    if not ttl and cls in {'EVA_Window','ATL:00007FF9D0B7A050'}: continue
    print(f'cls={cls!r}  title={ttl!r}')
    try:
        app = Application(backend='win32').connect(handle=w.handle)
        for c in app.top_window().descendants():
            t = safe_txt(c).strip()
            if t and len(t) > 1:
                print(f'  [{safe_cls(c)}] {t!r}')
    except: pass

pyautogui.press('escape')
print('완료')
