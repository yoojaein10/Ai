"""
탭 스캔 v2 — STATUS 컬럼값 비교 + 스크린샷
TcxGrid Ctrl+C → '헤더행\n데이터행' splitlines()[1] 으로 데이터행 추출
"""
import sys, os, time
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, r"D:\AI\Claude\Y_BankAuto")
from extract_shinhan import (
    safe_cls, safe_txt, safe_rect,
    Desktop, force_foreground, send_keys, _get_main_grid,
)
import pyperclip, pyautogui
from pathlib import Path

SHOT_DIR = Path(r"C:\Bank24Extractor\output")
SHOT_DIR.mkdir(parents=True, exist_ok=True)

def get_main_win():
    for w in Desktop(backend="win32").windows():
        if safe_cls(w) == "TfrmMain":
            return w
    return None

def read_status_and_count(main_win):
    """
    그리드 Ctrl+Home → Ctrl+C → splitlines()
    반환: (header_line, data_line, status_field)
    """
    try:
        grid = _get_main_grid(main_win)
        if not grid: return ("", "", "(그리드없음)")
        grid.click_input(); time.sleep(0.2)
        send_keys("^{HOME}"); time.sleep(0.15)
        pyperclip.copy("")
        send_keys("^c"); time.sleep(0.4)
        raw = pyperclip.paste() or ""
        lines = raw.splitlines()
        hdr  = lines[0] if len(lines) > 0 else ""
        data = lines[1] if len(lines) > 1 else ""
        # 상태 컬럼: 헤더 파싱해서 위치 찾기
        hdrs = [h.strip() for h in hdr.split("\t")]
        vals = [v.strip() for v in data.split("\t")]
        status_idx = next((i for i, h in enumerate(hdrs) if "상" in h and "태" in h), -1)
        status = vals[status_idx] if 0 <= status_idx < len(vals) else f"(col{status_idx}없음)"
        return (hdr[:60], data[:80], status)
    except Exception as e:
        return ("", "", f"(오류:{e})")

# ── 연결 ────────────────────────────────────────────────────
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
bar_w = r0 - l0
cy = t0 + (b0 - t0) // 2

force_foreground(main_win.handle, "메인창")
time.sleep(0.5)

# 전체 화면 스크린샷 저장 (현재 상태)
shot0 = SHOT_DIR / "tab_before.png"
pyautogui.screenshot(str(shot0))
print(f"[스크린샷] {shot0}")

# 기준
hdr0, data0, status0 = read_status_and_count(main_win)
print(f"기준 상태: {status0!r}")
print(f"  data : {data0[:80]}")

# 20px 간격 스캔 — STATUS 변화 지점 찾기
print(f"\n{'x':>5}  {'status':^20}  변화")
print("-" * 50)

prev_status = status0
for cx in range(l0 + 10, r0, 20):
    pyautogui.click(cx, cy)
    time.sleep(1.0)
    _, data, status = read_status_and_count(main_win)
    mark = " ◀ 변경" if status != prev_status else ""
    if mark:
        print(f"  {cx:>4}  {status:<20}  {mark}  data={data[:50]}")
    else:
        print(f"  {cx:>4}  {status:<20}")
    prev_status = status

# 최종 스크린샷
shot1 = SHOT_DIR / "tab_after.png"
pyautogui.screenshot(str(shot1))
print(f"\n[최종 스크린샷] {shot1}")
print("완료")
