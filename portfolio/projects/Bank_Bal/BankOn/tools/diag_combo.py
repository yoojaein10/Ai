"""콤보(TcxDBLookupComboBox 등) 자동 선택 방법 정찰 — 폼 상태만 바꾸고 저장 안 함(닫으면 사라짐).
실행: Start-Process python -ArgumentList '"...\tools\diag_combo.py" <from> <to> <doc>' -Verb RunAs -Wait
"""
from __future__ import annotations
import io, os, sys, time, traceback
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT / "src"))
DATE_FROM, DATE_TO, DOC = sys.argv[1], sys.argv[2], sys.argv[3]
ts = time.strftime("%Y%m%d_%H%M%S")
log = open(ROOT / "reports" / f"diag_combo_{ts}.log", "w", encoding="utf-8", errors="replace")
class Tee(io.TextIOBase):
    def write(self, s):
        for st in (sys.__stdout__, log): st.write(s); st.flush()
        return len(s)
sys.stdout = sys.stderr = Tee()
from pywinauto.keyboard import send_keys
from bankon.config import load_config
from bankon.ui import driver, navigate, form as F

TARGETS = [("담보세부종류", "토지"), ("담보용도", "공장용지"), ("지목", "공장용지"),
           ("용도지역구분(신)", "농림지역"), ("평가사명1@2", "김치암")]

def find(handle, label):
    name, _, nth = label.partition("@")
    return driver.find_by_label(handle, name, index=int(nth) - 1 if nth.isdigit() else 0)

def readback(ctl):
    return driver.read(driver.editable(ctl))

def snap(w, tag):
    p = ROOT / "reports" / f"diag_combo_{ts}_{tag}.png"
    w.capture_as_image().save(str(p)); return p.name

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
    w = driver.window(form.handle); w.set_focus(); time.sleep(0.5)
    navigate.select_object_row(form, 0)
    print(f"[diag] 폼 {form.class_name}")
    for label, value in TARGETS:
        ctl = find(form.handle, label)
        if ctl is None:
            print(f"[{label}] 컨트롤 못 찾음"); continue
        cls = ctl.element_info.class_name
        inner = driver.editable(ctl)
        print(f"\n[{label}] {cls} / inner={inner.element_info.class_name} 현재='{readback(ctl)}' 목표='{value}'")
        # A: 안쪽 에디트 set_edit_text
        try:
            inner.set_focus(); time.sleep(0.2)
            inner.set_edit_text(""); inner.set_edit_text(value); time.sleep(0.4)
            send_keys("{TAB}"); time.sleep(0.4)
            a = readback(ctl); print(f"  A set_edit_text+TAB → '{a}'")
            if a == value: print("  ✔ A 성공"); continue
        except Exception as e: print(f"  A 예외 {e!r}")
        # B: 포커스 + 타이핑 + Enter
        try:
            inner.set_focus(); time.sleep(0.2)
            send_keys("^a{BACKSPACE}"); time.sleep(0.2)
            send_keys(value, with_spaces=True, pause=0.05); time.sleep(0.5)
            send_keys("{ENTER}"); time.sleep(0.4); send_keys("{TAB}"); time.sleep(0.3)
            b = readback(ctl); print(f"  B 타이핑+ENTER → '{b}'")
            if b == value: print("  ✔ B 성공"); continue
        except Exception as e: print(f"  B 예외 {e!r}")
        # C: F4 드롭다운 + 타이핑 + Enter
        try:
            inner.set_focus(); time.sleep(0.2)
            send_keys("{F4}"); time.sleep(0.5)
            send_keys(value, with_spaces=True, pause=0.05); time.sleep(0.5)
            send_keys("{ENTER}"); time.sleep(0.4)
            c = readback(ctl); print(f"  C F4+타이핑+ENTER → '{c}'")
            if c == value: print("  ✔ C 성공"); continue
            send_keys("{ESC}")
        except Exception as e: print(f"  C 예외 {e!r}")
        print("  ✘ 세 방식 모두 실패")
    print(f"[diag] 스냅샷 {snap(w, 'after')}")
    rc = 0
except Exception as e:
    traceback.print_exc(); print(f"[diag] 실패 {e!r}")
finally:
    try:
        navigate.close_context_menu(); navigate.close_forms(session)
        print(f"[diag] 폼 닫기(저장 없음). 남은 폼={len(navigate.open_forms(session))}")
    except Exception as e: print(f"[diag] 닫기 실패 {e!r}")
    log.close()
sys.exit(rc)
