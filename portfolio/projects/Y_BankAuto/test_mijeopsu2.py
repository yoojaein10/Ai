"""
미접수 탭 클릭 테스트 — bars[0] 상대좌표 방식
bars[0]: rect=(104,88,887,146) w=783 h=58
버튼 순서: 전체(0) 미배정(1) 미접수(2) 작성(3) ...
"""
import sys, os, time, ctypes
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, r"D:\AI\Claude\Y_BankAuto")
from extract_shinhan import (
    safe_cls, safe_txt, safe_rect,
    Desktop, Application, force_foreground,
)
import pyautogui

def get_main_win():
    for w in Desktop(backend="win32").windows():
        if safe_cls(w) == "TfrmMain":
            return w
    return None

def get_bars(main_win):
    bars = []
    for c in main_win.descendants():
        if safe_cls(c) == "TdxBarControl":
            l, t, r, b = safe_rect(c)
            bars.append((t, l, r, b, c))
    bars.sort(key=lambda x: (x[0], x[1]))
    return bars

# ── 연결 ─────────────────────────────────────────────────────
main_win = get_main_win()
if not main_win:
    print("[ERROR] TfrmMain 없음"); sys.exit(1)
print(f"[OK] 메인창: {safe_txt(main_win)!r}")

bars = get_bars(main_win)
print(f"[OK] TdxBarControl {len(bars)}개")
for i, (t, l, r, b, c) in enumerate(bars):
    print(f"  [{i}] rect=({l},{t},{r},{b}) w={r-l}")

# ── bars[0] 전처리 ──────────────────────────────────────────
t0, l0, r0, b0, bar0 = bars[0]
bar_w = r0 - l0
bar_h = b0 - t0
bar_cy = t0 + bar_h // 2  # 툴바 세로 중앙

# ── EnumChildWindows로 자식 창 직접 탐색 ───────────────────
print(f"\n[ctypes] EnumChildWindows on bars[0] hwnd={bar0.handle:#010x}")
child_handles = []
def enum_cb(hwnd, _):
    child_handles.append(hwnd)
    return True
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
ctypes.windll.user32.EnumChildWindows(bar0.handle, WNDENUMPROC(enum_cb), 0)
print(f"  자식 hwnd 수: {len(child_handles)}")
for hwnd in child_handles[:20]:
    cls_buf = ctypes.create_unicode_buffer(256)
    txt_buf = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetClassNameW(hwnd, cls_buf, 256)
    ctypes.windll.user32.GetWindowTextW(hwnd, txt_buf, 256)
    r = ctypes.wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r))
    print(f"  hwnd={hwnd:#010x} class={cls_buf.value!r} text={txt_buf.value!r} rect=({r.left},{r.top},{r.right},{r.bottom})")

# ── 전체 버튼 위치 계산 후 순서대로 클릭 테스트 ────────────
# 버튼 개수를 실제로 세기 어려우므로
# x 위치를 10등분해서 각각의 title 변화 관찰
print(f"\n[탐색] bars[0] 클릭 위치 순서대로 테스트")
print(f"  bar: left={l0} right={r0} width={bar_w} cy={bar_cy}")

# 전체 탭(0번) 먼저 클릭해서 기준 상태로
force_foreground(main_win.handle, "메인창")
time.sleep(0.3)

# 버튼 10개 가정, 버튼폭 = bar_w / 10
# 실제로는 11개지만 10 또는 11 시도
NUM_BTNS_ESTIMATE = 11
btn_w = bar_w / NUM_BTNS_ESTIMATE

print(f"\n  예상 버튼폭: {btn_w:.1f}px (버튼 수={NUM_BTNS_ESTIMATE} 가정)")
for idx in range(min(5, NUM_BTNS_ESTIMATE)):
    cx = int(l0 + btn_w * idx + btn_w / 2)
    cy = bar_cy
    print(f"\n  [클릭 {idx}] x={cx} y={cy}")
    pyautogui.click(cx, cy)
    time.sleep(0.8)
    title = safe_txt(main_win)
    print(f"  → 메인창 title: {title!r}")
    if idx == 2:
        print("  ← 이게 미접수 예상 위치")
