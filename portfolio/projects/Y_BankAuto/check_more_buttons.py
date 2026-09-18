import sys, time
sys.path.insert(0, r'D:\AI\Claude\Y_BankAuto')
from extract_shinhan import safe_cls, safe_txt
from pywinauto import Desktop
import pyautogui

# 미리보기 재오픈 여부 확인
preview_win = next((w for w in Desktop(backend='win32').windows()
                    if safe_cls(w) == 'TfrxPreviewForm'), None)
if not preview_win:
    print('미리보기 없음 — 먼저 C 키로 열어야 함'); sys.exit(1)

print('미리보기 창 확인됨')

# x=138 이후 버튼 툴팁 탐색
toolbar_y = 38
print('\n=== x=138 이후 버튼 탐색 ===')
for bx in range(140, 500, 19):
    pyautogui.moveTo(bx, toolbar_y, duration=0.05)
    time.sleep(0.3)
    for w in Desktop(backend='win32').windows():
        cls = safe_cls(w)
        if 'tooltip' in cls.lower() or 'hint' in cls.lower() or cls == 'THintWindow':
            t = safe_txt(w).strip()
            if t and t not in ('인쇄', '열기', '저장', '검색', 'Zoom In', '확대',
                               '<팀장>', '_hf', 'prop  TField.AsString: String - DB.pas (598)'):
                print(f'  x={bx}: {t!r}')
                break

# 우클릭 메뉴도 확인 (미리보기 본문 영역)
print('\n=== 미리보기 본문 우클릭 메뉴 ===')
pyautogui.rightClick(960, 500)
time.sleep(1.5)
for w in Desktop(backend='win32').windows():
    cls = safe_cls(w)
    if any(k in cls for k in ('Menu','Popup','TPopup','#32768')):
        print(f'메뉴: {cls!r}')
        from pywinauto import Application
        try:
            for c in Application(backend='win32').connect(handle=w.handle).top_window().descendants():
                t = safe_txt(c).strip()
                if t: print(f'  {t!r}')
        except: pass
pyautogui.press('escape')
print('완료')
