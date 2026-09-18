"""국민은행 정찰 — 읽기 전용(저장·발송 없음).
    ① 작성(A) 폼: 컨트롤 덤프·스크린샷, 그리드마다 Shift+F10 컨텍스트 메뉴 스냅(물건 일괄추가 메뉴 찾기) → Esc
    ② 현장조사서(E) 폼: 컨트롤 덤프·스크린샷·버튼 목록, PDF등록 버튼이 있으면 창만 열어 스냅 후 닫기
실행: Start-Process python -ArgumentList '"...\\tools\\recon_kb.py" <from> <to> <doc> [탭]' -Verb RunAs -WindowStyle Hidden -Wait
"""
from __future__ import annotations
import ctypes, io, os, sys, time, traceback
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT / "src"))
DATE_FROM, DATE_TO, DOC = sys.argv[1], sys.argv[2], sys.argv[3]
TAB = sys.argv[4] if len(sys.argv) > 4 else "작성"
ts = time.strftime("%Y%m%d_%H%M%S")
TAG = f"recon_kb_{ts}"
log = open(ROOT / "reports" / f"{TAG}.log", "w", encoding="utf-8", errors="replace")
class Tee(io.TextIOBase):
    def write(self, s):
        for st in (sys.__stdout__, log): st.write(s); st.flush()
        return len(s)
sys.stdout = sys.stderr = Tee()
from PIL import ImageGrab
from pywinauto.keyboard import send_keys
from bankon.config import load_config
from bankon.ui import driver, navigate

VX = ctypes.windll.user32.GetSystemMetrics(76); VY = ctypes.windll.user32.GetSystemMetrics(77)


def snap_rect(left, top, w, h, name):
    shot = ImageGrab.grab(all_screens=True)
    box = (max(0, left - VX), max(0, top - VY), left - VX + w, top - VY + h)
    shot.crop(box).save(str(ROOT / "reports" / f"{TAG}_{name}.png"))
    print(f"[recon] 스냅 {name} box={box}")


def snap_window(handle, name):
    w = driver.window(handle); w.set_focus(); time.sleep(0.6)
    w.capture_as_image().save(str(ROOT / "reports" / f"{TAG}_{name}.png"))
    print(f"[recon] 스냅 {name}")


def dump(handle, title):
    r = driver.window(handle).rectangle()
    rows = []
    for c in driver.descendants(handle):
        try:
            cls = c.element_info.class_name or ""; txt = (c.window_text() or "").strip(); rc_ = driver._rect(c)
        except Exception: continue
        if rc_ is None or "Inner" in cls or cls == "TcxControlScrollBar": continue
        val = ""
        if not (cls in driver.LABEL_CLASSES or "Button" in cls or "Panel" in cls or "Grid" in cls or "Bar" in cls or "Page" in cls or "Tab" in cls):
            try: val = driver.read(driver.editable(c))
            except Exception: val = ""
        rows.append((rc_.top - r.top, rc_.left - r.left, cls, txt, val, rc_.right - rc_.left, rc_.bottom - rc_.top))
    rows.sort()
    print(f"[recon] ===== {title}: 컨트롤 {len(rows)}개 (창 상대 top,left | class | text | value | w x h)")
    for t, l, cls, txt, val, wdt, hgt in rows:
        print(f"  @{t:4},{l:4} {cls:28} '{txt[:30]}' = '{val[:30]}' {wdt}x{hgt}")
    return rows


def menu_snap_on(control, name):
    """컨트롤에 포커스 → Shift+F10 → 메뉴 스냅 → Esc. 메뉴가 떴는지 돌려준다."""
    try:
        control.click_input(); time.sleep(0.4)
    except Exception as e:
        print(f"[recon] {name} 클릭 실패 {e!r}"); return False
    before = navigate._menu_handles()
    send_keys("+{F10}"); time.sleep(0.8)
    new = navigate._menu_handles() - before
    gr = control.rectangle()
    snap_rect(gr.left - 20, gr.top - 20, 700, 700, name)
    if new: send_keys("{ESC}"); time.sleep(0.3)
    print(f"[recon] {name}: 컨텍스트 메뉴 {'있음' if new else '없음'} ({len(new)})")
    return bool(new)


rc = 1; session = None
try:
    cfg = load_config(None)
    session = navigate.open_app(cfg.loader_cmd, cfg.bankon_user, cfg.bankon_password)
    navigate.select_tab(session, TAB)

    def requery():
        navigate.query_documents(session, start=DATE_FROM, end=DATE_TO, work_type="담보")
        navigate.close_forms(session); navigate.close_survey_forms(session)
    requery()
    print("[recon] 행:", navigate.ensure_row(session, DOC, requery=requery))
    print("[recon] 행 텍스트:", navigate.focused_row_text(session)[-400:])

    # ── ① 작성(A) 폼 ─────────────────────────────────────────
    form = navigate.open_write_form(session, home=False)
    print(f"[recon] 작성 폼 {form.class_name} '{form.title}' rect={driver.window(form.handle).rectangle()}")
    snap_window(form.handle, "write")
    dump(form.handle, "작성 폼")
    grids = driver.by_class(form.handle, "TcxGridSite")
    print(f"[recon] 작성 폼 그리드 {len(grids)}개: " + ", ".join(str(g.rectangle()) for g in grids))
    for i, g in enumerate(grids):
        menu_snap_on(g, f"write_grid{i}_menu")
    # 폼 빈 바탕(패널)에서도 우클릭 메뉴가 있는지
    panels = [c for c in driver.descendants(form.handle) if "Panel" in (c.element_info.class_name or "")]
    if panels:
        big = max(panels, key=lambda c: (lambda r: (r.right - r.left) * (r.bottom - r.top))(c.rectangle()))
        menu_snap_on(big, "write_panel_menu")
    navigate.close_forms(session)
    print(f"[recon] 작성 폼 닫힘. 확인창: {navigate.decline_save_prompt(session, wait=2.0)}")

    # ── ② 현장조사서(E) ────────────────────────────────────────
    print("[recon] 행:", navigate.ensure_row(session, DOC, requery=requery))
    before = navigate._windows_of(session)
    grid = navigate._grid(session); grid.set_focus(); time.sleep(0.4)
    m0 = navigate._menu_handles()
    send_keys("+{F10}"); time.sleep(0.8)
    if not (navigate._menu_handles() - m0):
        raise navigate.NavigationError("메인 컨텍스트 메뉴 안 열림")
    send_keys("e")
    survey = navigate._wait_new_window(session, before, timeout=30.0)
    if survey is None:
        raise navigate.NavigationError("현장조사서 창이 안 열림")
    print(f"[recon] 현장조사서 창 {survey.class_name} '{survey.title}' rect={driver.window(survey.handle).rectangle()}")
    snap_window(survey.handle, "survey")
    rows = dump(survey.handle, "현장조사서 폼")
    buttons = [(txt, l, t) for t, l, cls, txt, val, w_, h_ in rows if "Button" in cls]
    print(f"[recon] 현장조사서 버튼: {buttons}")
    pdf_btn = driver.by_text(survey.handle, "PDF등록") or driver.by_text(survey.handle, "PDF 등록")
    if pdf_btn is not None:
        before2 = navigate._windows_of(session)
        driver.click(pdf_btn)
        try:
            pdfw = navigate._wait_new_window(session, before2, timeout=15.0)
            if pdfw is None:
                raise navigate.NavigationError("PDF 창 안 뜸")
            print(f"[recon] PDF 창 {pdfw.class_name} '{pdfw.title}'")
            snap_window(pdfw.handle, "survey_pdf")
            dump(pdfw.handle, "현장조사서 PDF 창")
            navigate.close_pdf_windows(session, on_prompt=lambda s, **k: navigate.decline_save_prompt(s, wait=k.get("wait", 1.0)))
        except Exception as e:
            print(f"[recon] PDF 창 안 뜸/처리 실패 {e!r}")
    else:
        print("[recon] 현장조사서에 PDF등록 버튼 없음")
    rc = 0
except Exception as e:
    traceback.print_exc(); print(f"[recon] 실패 {e!r}")
finally:
    try:
        navigate.close_context_menu()
        if session:
            navigate.close_pdf_windows(session, on_prompt=lambda s, **k: navigate.decline_save_prompt(s, wait=k.get("wait", 1.0)))
            navigate.close_survey_forms(session)
            navigate.close_forms(session)
            print(f"[recon] 정리: 폼={len(navigate.open_forms(session))} 현장조사서={len(navigate.survey_forms(session))} PDF={len(navigate.pdf_windows(session))}")
    except Exception as e: print(f"[recon] 정리 실패 {e!r}")
    print(f"[recon] exit={rc}")
    log.close()
sys.exit(rc)
