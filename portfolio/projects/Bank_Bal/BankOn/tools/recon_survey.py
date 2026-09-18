"""현장조사서 작성(E) 폼 정찰 — 읽기 전용(열어서 컨트롤 덤프·스크린샷 후 저장 없이 닫기).
실행: Start-Process python -ArgumentList '"...\tools\recon_survey.py" <from> <to> <doc>' -Verb RunAs -Wait
"""
from __future__ import annotations
import io, os, sys, time, traceback
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT / "src"))
DATE_FROM, DATE_TO, DOC = sys.argv[1], sys.argv[2], sys.argv[3]
TAB = sys.argv[4] if len(sys.argv) > 4 else "작성"
ts = time.strftime("%Y%m%d_%H%M%S")
log = open(ROOT / "reports" / f"recon_survey_{ts}.log", "w", encoding="utf-8", errors="replace")
class Tee(io.TextIOBase):
    def write(self, s):
        for st in (sys.__stdout__, log): st.write(s); st.flush()
        return len(s)
sys.stdout = sys.stderr = Tee()
from pywinauto.keyboard import send_keys
from pywinauto.findwindows import find_elements
from bankon.config import load_config
from bankon.ui import driver, navigate

def top_windows(pid):
    return {int(e.handle): (e.class_name or "", (e.name or "").strip())
            for e in find_elements(backend="win32", top_level_only=True, visible_only=True)
            if int(e.process_id or 0) == pid and e.handle}

rc = 1; session = None; new_h = None
try:
    cfg = load_config(None)
    session = navigate.open_app(cfg.loader_cmd, cfg.bankon_user, cfg.bankon_password)
    navigate.select_tab(session, TAB)
    navigate.query_documents(session, start=DATE_FROM, end=DATE_TO, work_type="담보")
    navigate.close_forms(session)
    found = False
    for attempt in range(3):
        if attempt:
            print(f"[recon] 행 못 찾음 — 재조회·재순회 {attempt + 1}/3")
            navigate.query_documents(session, start=DATE_FROM, end=DATE_TO, work_type="담보")
            navigate.close_forms(session)
        if navigate.find_row_by_doc(session, DOC):
            found = True
            break
    if not found:
        raise navigate.NavigationError(f"{DOC} 행 없음")
    before = top_windows(session.pid)
    grid = navigate._grid(session); grid.set_focus(); time.sleep(0.4)
    m0 = navigate._menu_handles()
    send_keys("+{F10}"); time.sleep(0.8)
    if not (navigate._menu_handles() - m0):
        raise navigate.NavigationError("컨텍스트 메뉴 안 열림")
    send_keys("e")                       # 현장조사서 작성(E)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        now = top_windows(session.pid)
        diff = {h: v for h, v in now.items() if h not in before}
        if diff:
            break
        time.sleep(0.4)
    print(f"[recon] 새 창: {diff}")
    if not diff:
        raise navigate.NavigationError("현장조사서 창이 안 열림")
    new_h = next(iter(diff))
    w = driver.window(new_h); w.set_focus(); time.sleep(0.8)
    r = w.rectangle(); print(f"[recon] 창 {diff[new_h]} rect={r}")
    w.capture_as_image().save(str(ROOT / "reports" / f"recon_survey_{ts}_form.png"))
    # 컨트롤 덤프
    rows = []
    for c in driver.descendants(new_h):
        try:
            cls = c.element_info.class_name or ""; txt = (c.window_text() or "").strip()
            rc_ = driver._rect(c)
        except Exception: continue
        if rc_ is None: continue
        if "Inner" in cls: continue
        val = ""
        if not (cls in driver.LABEL_CLASSES or "Button" in cls or "Panel" in cls or "Grid" in cls or "Bar" in cls or "Page" in cls or "Tab" in cls):
            try: val = driver.read(driver.editable(c))
            except Exception: val = ""
        rows.append((rc_.top - r.top, rc_.left - r.left, cls, txt, val, rc_.right - rc_.left, rc_.bottom - rc_.top))
    rows.sort()
    print(f"[recon] 컨트롤 {len(rows)}개 (창 상대좌표 top,left | class | text | value | w x h)")
    for t, l, cls, txt, val, wdt, hgt in rows:
        if cls in ("TcxControlScrollBar",): continue
        print(f"  @{t:4},{l:4} {cls:28} '{txt[:24]}' = '{val[:30]}' {wdt}x{hgt}")
    # 탭 페이지가 있으면 페이지별 스크린샷은 다음 단계에서
    rc = 0
except Exception as e:
    traceback.print_exc(); print(f"[recon] 실패 {e!r}")
finally:
    try:
        navigate.close_context_menu()
        if new_h:
            btn = driver.by_text(new_h, "닫 기") or driver.by_text(new_h, "닫기") or driver.by_text(new_h, "취 소") or driver.by_text(new_h, "취소")
            if btn is not None:
                print("[recon] 닫기 버튼:", btn.window_text()); driver.click(btn)
            else:
                print("[recon] 닫기 버튼 없음 → 창 닫기(WM_CLOSE)"); driver.window(new_h).close()
            time.sleep(1.5)
            pressed = navigate.decline_save_prompt(session, wait=3.0)
            print(f"[recon] 확인창 처리: {pressed}")
        navigate.close_forms(session)
        print(f"[recon] 남은 창: {top_windows(session.pid) if session else '?'}")
    except Exception as e: print(f"[recon] 닫기 실패 {e!r}")
    log.close()
sys.exit(rc)
