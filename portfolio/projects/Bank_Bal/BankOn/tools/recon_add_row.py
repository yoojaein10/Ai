"""신한 작성 폼 '물건 행 추가' 방법 정찰 — 읽기 전용(메뉴 열고 스크린샷 후 Esc, 저장 없음).
실행: Start-Process python -ArgumentList '"...\tools\recon_add_row.py" <from> <to> <doc>' -Verb RunAs -Wait
"""
from __future__ import annotations
import io, os, re, sys, time, traceback
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT / "src"))
DATE_FROM, DATE_TO, DOC = sys.argv[1], sys.argv[2], sys.argv[3]
ts = time.strftime("%Y%m%d_%H%M%S")
log = open(ROOT / "reports" / f"recon_addrow_{ts}.log", "w", encoding="utf-8", errors="replace")
class Tee(io.TextIOBase):
    def write(self, s):
        for st in (sys.__stdout__, log): st.write(s); st.flush()
        return len(s)
sys.stdout = sys.stderr = Tee()
from pywinauto.keyboard import send_keys
from bankon.config import load_config
from bankon.ui import driver, navigate
rc = 1
try:
    cfg = load_config(None)
    session = navigate.open_app(cfg.loader_cmd, cfg.bankon_user, cfg.bankon_password)
    navigate.select_tab(session, "작성")
    navigate.query_documents(session, start=DATE_FROM, end=DATE_TO, work_type="담보")
    navigate.close_forms(session)
    if not navigate.find_row_by_doc(session, DOC):
        raise navigate.NavigationError(f"{DOC} 행 없음")
    form = navigate.open_write_form(session, home=False)
    print(f"[recon] 폼 {form.class_name} {form.title}")
    w = driver.window(form.handle); w.set_focus(); time.sleep(0.5)
    # 1) 버튼·그리드·메뉴 컨트롤 목록
    for c in driver.descendants(form.handle):
        try:
            cls = c.element_info.class_name or ""; txt = (c.window_text() or "").strip()
        except Exception: continue
        if "Button" in cls or "Grid" in cls or "Popup" in cls or "Menu" in cls or "Bar" in cls:
            r = driver._rect(c)
            print(f"  {cls:28} '{txt[:20]}' @{r.left if r else '?'},{r.top if r else '?'} "
                  f"{(r.right-r.left) if r else ''}x{(r.bottom-r.top) if r else ''}")
    # 2) 순번 그리드에 포커스 → Shift+F10 → 메뉴 스크린샷 → Esc
    grids = driver.by_class(form.handle, "TcxGridSite")
    print(f"[recon] 폼 그리드 {len(grids)}개")
    if grids:
        g = min(grids, key=lambda x: x.rectangle().left)   # 가장 왼쪽 = 순번 그리드
        g.click_input(); time.sleep(0.4)
        before = navigate._menu_handles()
        send_keys("+{F10}"); time.sleep(0.8)
        new = navigate._menu_handles() - before
        print(f"[recon] 컨텍스트 메뉴 {len(new)}개")
        from PIL import ImageGrab
        gr = g.rectangle()
        shot = ImageGrab.grab(all_screens=True)
        # 가상 데스크톱 원점 보정(다중 모니터: 음수/오프셋 좌표)
        import ctypes
        vx = ctypes.windll.user32.GetSystemMetrics(76); vy = ctypes.windll.user32.GetSystemMetrics(77)
        box = (gr.left - vx - 20, gr.top - vy - 20, gr.left - vx + 600, gr.top - vy + 600)
        shot.crop(box).save(str(ROOT / "reports" / f"recon_addrow_{ts}_menu.png"))
        print(f"[recon] 메뉴 스냅 box={box} virt=({vx},{vy}) shot={shot.size}")
        if new: send_keys("{ESC}"); time.sleep(0.3)
        # 그리드 자체 크롭 스크린샷
        g.capture_as_image().save(str(ROOT / "reports" / f"recon_addrow_{ts}_grid.png"))
    w.capture_as_image().save(str(ROOT / "reports" / f"recon_addrow_{ts}_form.png"))
    rc = 0
except Exception as e:
    traceback.print_exc(); print(f"[recon] 실패 {e!r}")
finally:
    try:
        navigate.close_context_menu(); navigate.close_forms(session)
        print(f"[recon] 폼 닫기(저장 없음). 남은 폼={len(navigate.open_forms(session))}")
    except Exception as e: print(f"[recon] 닫기 실패 {e!r}")
    log.close()
sys.exit(rc)
