import sys, time
sys.path.insert(0, r'D:\AI\Claude\Y_BankAuto')
from extract_shinhan import safe_cls, safe_txt, safe_rect
from pywinauto import Desktop, Application

# 미리보기 창 찾기
preview_win = None
for w in Desktop(backend='win32').windows():
    ttl = safe_txt(w)
    cls = safe_cls(w)
    if '미리보기' in ttl or 'preview' in ttl.lower() or 'Preview' in cls:
        preview_win = w
        print(f'미리보기 창: cls={cls!r}  title={ttl!r}  hwnd={w.handle:#010x}')
        break

if not preview_win:
    print('미리보기 창 못 찾음 — 모든 창 목록:')
    skip = {'TPUtilWindow','Shell_TrayWnd','Progman','WorkerW','MSCTFIME UI',
            'IME','GDI+ Hook Window Class','Xaml_WindowedPopupClass',
            'TApplication','LOGI_RAWINPUT_CLASS','XamlExplorerHostIslandWindow',
            'SystemTray_Main','TopLevelWindowForOverflowXamlIsland',
            'ForegroundStaging','ThumbnailDeviceHelperWnd'}
    for w in Desktop(backend='win32').windows():
        cls = safe_cls(w)
        ttl = safe_txt(w)
        if cls not in skip:
            print(f'  cls={cls!r}  title={ttl!r}')
    sys.exit(0)

# win32 descendants
print('\n=== win32 descendants (텍스트 있는 것) ===')
try:
    app32 = Application(backend='win32').connect(handle=preview_win.handle)
    win32 = app32.top_window()
    for c in win32.descendants():
        t = safe_txt(c).strip()
        cls = safe_cls(c)
        if t and len(t) > 2:
            print(f'  [{cls}] {t!r}')
except Exception as e:
    print(f'win32 오류: {e}')

# UIA descendants
print('\n=== UIA descendants (텍스트 있는 것) ===')
try:
    app_uia = Application(backend='uia').connect(handle=preview_win.handle)
    uia_win = app_uia.top_window()
    for c in uia_win.descendants():
        t = safe_txt(c).strip()
        cls = safe_cls(c)
        if t and len(t) > 2:
            print(f'  [{cls}] {t!r}')
except Exception as e:
    print(f'UIA 오류: {e}')

# 툴바 버튼 확인 (저장/내보내기 버튼 있는지)
print('\n=== 툴바 버튼 전체 ===')
try:
    for c in win32.descendants():
        cls = safe_cls(c)
        t = safe_txt(c).strip()
        if any(k in cls for k in ('Button','TBitBtn','TSpeedBtn','TRzBitBtn','TcxButton')):
            print(f'  [{cls}] {t!r}')
except: pass
