"""
미접수 탭 클릭 — 그리드 첫행 비교로 탭 전환 확인
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

def grid_first_row(main_win):
    """그리드 포커스 후 Ctrl+Home → Ctrl+C → 첫 행 반환"""
    try:
        grid = _get_main_grid(main_win)
        if not grid: return "(그리드 없음)"
        grid.click_input(); time.sleep(0.2)
        send_keys("^{HOME}"); time.sleep(0.1)
        pyperclip.copy("")
        send_keys("^c"); time.sleep(0.4)
        val = pyperclip.paste() or ""
        return val[:120].replace("\t", " | ")
    except Exception as e:
        return f"(오류: {e})"

def mdi_titles(main_win):
    """MDI 자식창 제목 목록"""
    titles = []
    try:
        for c in main_win.descendants():
            cls = safe_cls(c)
            if "MDI" in cls or "TfrmMain" in cls or "Tfr" in cls:
                t = safe_txt(c)
                if t: titles.append(f"{cls}:{t!r}")
    except: pass
    return titles[:5]

# ── 연결 ─────────────────────────────────────────────────────
main_win = get_main_win()
if not main_win:
    print("[ERROR] TfrmMain 없음"); sys.exit(1)
print(f"[OK] {safe_txt(main_win)!r}")

bars = []
for c in main_win.descendants():
    if safe_cls(c) == "TdxBarControl":
        l, t, r, b = safe_rect(c)
        bars.append((t, l, r, b, c))
bars.sort()

t0, l0, r0, b0, bar0 = bars[0]
bar_w = r0 - l0
btn_w = bar_w / 11
cy = t0 + (b0 - t0) // 2

force_foreground(main_win.handle, "메인창")
time.sleep(0.5)

# 기준: 현재 그리드 첫 행
baseline = grid_first_row(main_win)
print(f"\n기준(현재 탭) 첫행: {baseline}")

# 버튼 0~5 순서대로 클릭 후 그리드 첫행 비교
print(f"\n{'idx':>3}  {'cx':>5}  첫행 미리보기")
print("-" * 80)
for idx in range(6):
    cx = int(l0 + btn_w * idx + btn_w / 2)
    pyautogui.click(cx, cy)
    time.sleep(1.2)
    row = grid_first_row(main_win)
    mark = " ◀ 변경" if row != baseline and row not in ("(그리드 없음)", ) else ""
    print(f"  {idx:>2}  x={cx:>4}  {row[:80]}{mark}")

print("\n완료")
