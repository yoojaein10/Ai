"""
bars[0] 전체 너비 20px 스캔 — 데이터 첫 행 비교로 탭 경계 찾기
"""
import sys, os, time
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, r"D:\AI\Claude\Y_BankAuto")
from extract_shinhan import (
    safe_cls, safe_txt, safe_rect,
    Desktop, Application, force_foreground,
    send_keys, _get_main_grid,
)
import pyperclip, pyautogui

def get_main_win():
    for w in Desktop(backend="win32").windows():
        if safe_cls(w) == "TfrmMain":
            return w
    return None

def read_data_row(main_win):
    """Ctrl+Home → Down → Ctrl+C → 첫 데이터행"""
    try:
        grid = _get_main_grid(main_win)
        if not grid: return "(그리드없음)"
        grid.click_input(); time.sleep(0.15)
        send_keys("^{HOME}"); time.sleep(0.1)
        send_keys("{DOWN}");  time.sleep(0.1)
        pyperclip.copy("")
        send_keys("^c"); time.sleep(0.35)
        val = pyperclip.paste() or ""
        return val[:100].replace("\t", "|")
    except Exception as e:
        return f"(오류:{e})"

# ── 연결 ─────────────────────────────────────────────────────
main_win = get_main_win()
if not main_win:
    print("[ERROR] TfrmMain 없음"); sys.exit(1)

bars = []
for c in main_win.descendants():
    if safe_cls(c) == "TdxBarControl":
        l, t, r, b = safe_rect(c)
        bars.append((t, l, r, b, c))
bars.sort()

t0, l0, r0, b0, _ = bars[0]
cy = t0 + (b0 - t0) // 2

force_foreground(main_win.handle, "메인창")
time.sleep(0.4)

# 기준 데이터행 (현재 작성 탭)
baseline = read_data_row(main_win)
print(f"기준(작성탭) 데이터행: {baseline[:80]}\n")

prev = baseline
print(f"{'x':>5}  데이터행")
print("-" * 90)

# bars[0] 전체 너비 20px 간격 스캔
for cx in range(l0 + 10, r0, 20):
    pyautogui.click(cx, cy)
    time.sleep(0.9)
    row = read_data_row(main_win)
    marker = " ◀◀◀" if row != prev else ""
    print(f"  {cx:>4}  {row[:70]}{marker}")
    prev = row

print("\n완료")
