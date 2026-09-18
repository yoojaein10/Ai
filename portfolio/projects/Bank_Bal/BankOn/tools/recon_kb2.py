"""국민 작성 폼 2차 정찰 — 폼 상태만 바꾸고 저장 없이 닫는다(확인창은 '아니오').
    ① 오른쪽(세부내역) 그리드 Shift+F10 → 일괄추가(디테일)(Z) → 결과 스냅·덤프
    ② 세부내역 물건종류 라디오 토지/건물/기계기구 를 BM_CLICK 으로 차례로 골라 노출되는 칸 덤프
    ③ 왼쪽(물건) 그리드 추가(마지막위치)(T) 로 행 추가되는지(행 수 전후)
실행: Start-Process python -ArgumentList '"...\\tools\\recon_kb2.py" <from> <to> <doc>' -Verb RunAs -WindowStyle Hidden -Wait
"""
from __future__ import annotations
import io, os, sys, time, traceback
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT / "src"))
DATE_FROM, DATE_TO, DOC = sys.argv[1], sys.argv[2], sys.argv[3]
ts = time.strftime("%Y%m%d_%H%M%S")
TAG = f"recon_kb2_{ts}"
log = open(ROOT / "reports" / f"{TAG}.log", "w", encoding="utf-8", errors="replace")
class Tee(io.TextIOBase):
    def write(self, s):
        for st in (sys.__stdout__, log): st.write(s); st.flush()
        return len(s)
sys.stdout = sys.stderr = Tee()
from pywinauto.keyboard import send_keys
from bankon.config import load_config
from bankon.ui import driver, navigate


def snap(handle, name):
    w = driver.window(handle); w.set_focus(); time.sleep(0.6)
    w.capture_as_image().save(str(ROOT / "reports" / f"{TAG}_{name}.png")); print(f"[recon] 스냅 {name}")


def dump(handle, title, *, only_inputs=True):
    r = driver.window(handle).rectangle(); rows = []
    for c in driver.descendants(handle):
        try:
            cls = c.element_info.class_name or ""; txt = (c.window_text() or "").strip(); rc_ = driver._rect(c)
        except Exception: continue
        if rc_ is None or "Inner" in cls or cls == "TcxControlScrollBar": continue
        is_input = cls.startswith("Tcx") and not (cls in driver.LABEL_CLASSES or "Button" in cls or "Grid" in cls or "Page" in cls or "Tab" in cls or "Panel" in cls or "SizeGrip" in cls)
        if only_inputs and not is_input and cls not in driver.LABEL_CLASSES: continue
        val = ""
        if is_input:
            try: val = driver.read(driver.editable(c))
            except Exception: val = ""
        rows.append((rc_.top - r.top, rc_.left - r.left, cls, txt, val, rc_.right - rc_.left))
    rows.sort()
    print(f"[recon] ===== {title}: {len(rows)}개")
    for t, l, cls, txt, val, wdt in rows:
        print(f"  @{t:4},{l:4} {cls:26} '{txt[:34]}' = '{val[:30]}' w{wdt}")
    return rows


def grid_menu(grid, key, name):
    grid.click_input(); time.sleep(0.4)
    before = navigate._menu_handles()
    send_keys("+{F10}"); time.sleep(0.8)
    if not (navigate._menu_handles() - before):
        print(f"[recon] {name}: 메뉴 안 열림"); return False
    send_keys(key); time.sleep(1.5)
    pressed = navigate.decline_save_prompt(session, wait=1.5)   # 혹시 확인창이 뜨면 아니오
    print(f"[recon] {name}: '{key}' 보냄, 확인창={pressed}")
    return True


def rows_of(grid):
    """그리드 Ctrl+A/Ctrl+C 텍스트 줄 수로 행 수 추정."""
    try:
        grid.set_focus(); time.sleep(0.2); send_keys("^{END}"); time.sleep(0.3)
        return driver.read_grid_text(grid) if hasattr(driver, "read_grid_text") else None
    except Exception: return None


rc = 1; session = None
try:
    cfg = load_config(None)
    session = navigate.open_app(cfg.loader_cmd, cfg.bankon_user, cfg.bankon_password)
    navigate.select_tab(session, "작성")
    def requery():
        navigate.query_documents(session, start=DATE_FROM, end=DATE_TO, work_type="담보")
        navigate.close_forms(session); navigate.close_survey_forms(session)
    requery()
    print("[recon] 행:", navigate.ensure_row(session, DOC, requery=requery))
    form = navigate.open_write_form(session, home=False)
    print(f"[recon] 폼 {form.class_name}")
    grids = sorted(driver.by_class(form.handle, "TcxGridSite"), key=lambda g: g.rectangle().left)
    left, right = grids[0], grids[1]
    seq_edit = lambda: [c for c in driver.by_class(form.handle, "TcxDBCurrencyEdit") if driver._rect(c) and driver._rect(c).left - driver.window(form.handle).rectangle().left in (749,)]  # 오른쪽 일련번호
    dump(form.handle, "초기 입력칸")

    # ② 라디오 토지/건물/기계기구
    for kind in ("토지", "건물", "기계기구"):
        btn = driver.by_text(form.handle, kind, "TcxDBRadioGroupButton")
        if btn is None:
            print(f"[recon] 라디오 {kind} 없음"); continue
        driver.click_message(btn); time.sleep(1.2)
        pressed = navigate.decline_save_prompt(session, wait=1.0)
        snap(form.handle, f"radio_{kind}")
        dump(form.handle, f"세부내역 종류={kind} (확인창={pressed})")

    # ① 오른쪽 그리드 일괄추가(디테일)(Z)
    snap(form.handle, "before_bulk")
    grid_menu(right, "z", "오른쪽그리드 일괄추가(Z)")
    time.sleep(2.0)
    navigate.decline_save_prompt(session, wait=1.0)
    snap(form.handle, "after_bulk")
    dump(form.handle, "일괄추가 후 입력칸")
    # 새 창이 떴다면 기록
    for w in driver.find_windows(pid=session.pid):
        if w.handle != form.handle and w.class_name not in (driver.MAIN_CLASS,):
            print(f"[recon] 열린 창: {w.class_name} '{w.title}'")

    # ③ 왼쪽 그리드 추가(마지막위치)(T)
    grid_menu(left, "t", "왼쪽그리드 추가(T)")
    snap(form.handle, "after_add_left")
    dump(form.handle, "왼쪽 추가 후 입력칸")
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
            print(f"[recon] 정리: 폼={len(navigate.open_forms(session))} 확인창 처리={navigate.decline_save_prompt(session, wait=2.0)}")
            print(f"[recon] 정리 후 폼={len(navigate.open_forms(session))}")
    except Exception as e: print(f"[recon] 정리 실패 {e!r}")
    print(f"[recon] exit={rc}"); log.close()
sys.exit(rc)
