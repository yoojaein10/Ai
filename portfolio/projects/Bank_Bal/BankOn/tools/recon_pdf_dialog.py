"""PDF등록 → '파일선택' 이 띄우는 창 정찰 — 읽기 전용(덤프·스크린샷 후 취소, 등록 없음).
실행: Start-Process python -ArgumentList '"...\\tools\\recon_pdf_dialog.py" <from> <to> <doc>' -Verb RunAs -WindowStyle Hidden -Wait
"""
from __future__ import annotations

import io
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "src"))
DATE_FROM, DATE_TO, DOC = sys.argv[1], sys.argv[2], sys.argv[3]
ts = time.strftime("%Y%m%d_%H%M%S")
log = open(ROOT / "reports" / f"recon_pdfdlg_{ts}.log", "w", encoding="utf-8", errors="replace")


class Tee(io.TextIOBase):
    def write(self, s):
        for st in (sys.__stdout__, log):
            st.write(s)
            st.flush()
        return len(s)


sys.stdout = sys.stderr = Tee()

from pywinauto.findwindows import find_elements   # noqa: E402
from pywinauto.keyboard import send_keys           # noqa: E402
from bankon.config import load_config              # noqa: E402
from bankon.ui import driver, navigate             # noqa: E402


def windows_of(pid: int) -> dict:
    out = {}
    for e in find_elements(backend="win32", top_level_only=True, visible_only=True):
        if e.handle and int(e.process_id or 0) == pid:
            out[int(e.handle)] = (e.class_name or "", (e.name or "").strip())
    return out


def wait_new(pid: int, before: dict, timeout: float = 15.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        diff = {h: v for h, v in windows_of(pid).items() if h not in before}
        if diff:
            time.sleep(0.8)
            return {h: v for h, v in windows_of(pid).items() if h not in before}
        time.sleep(0.3)
    return {}


def dump(handle: int, limit: int = 120) -> None:
    w = driver.window(handle)
    r = w.rectangle()
    print(f"[recon] 창 rect={r} title='{w.window_text()}'")
    n = 0
    for c in w.descendants():
        try:
            cls = c.element_info.class_name or ""
            txt = (c.window_text() or "").strip()
            rc_ = c.rectangle()
        except Exception:
            continue
        if cls in ("ScrollBar",) or (not txt and cls in ("Static", "TPanel", "msctls_progress32")):
            continue
        print(f"  @{rc_.top - r.top:4},{rc_.left - r.left:4} {cls:32} '{txt[:70]}'")
        n += 1
        if n >= limit:
            print("  ...(생략)")
            break


rc = 1
session = None
pdf_win = None
dlg_handles: list[int] = []
try:
    cfg = load_config(None)
    session = navigate.open_app(cfg.loader_cmd, cfg.bankon_user, cfg.bankon_password)
    navigate.select_tab(session, "작성")

    def requery():
        navigate.query_documents(session, start=DATE_FROM, end=DATE_TO, work_type="담보")
        navigate.close_forms(session)

    requery()
    print("[recon] 행:", navigate.ensure_row(session, DOC, requery=requery))
    form = navigate.open_write_form(session, home=False)
    driver.window(form.handle).set_focus()
    time.sleep(0.5)
    before = windows_of(session.pid)
    driver.click(driver.by_text(form.handle, "PDF등록", "TcxButton"))
    diff = wait_new(session.pid, before)
    pdf_h = next((h for h, (cls, _) in diff.items() if cls == "TBnkTop24pdf"), None)
    print("[recon] PDF 창:", pdf_h, diff)
    if pdf_h is None:
        raise RuntimeError("PDF 첨부 창이 안 열림")
    pdf_win = pdf_h
    # 두 번째 탭 '평가전례 첨부용' 도 살펴본다(클릭만, 등록 없음)
    for c in driver.descendants(pdf_h):
        try:
            if c.element_info.class_name == "TcxTabSheet":
                print("  탭:", c.window_text())
        except Exception:
            pass
    sel = driver.by_text(pdf_h, "파일선택", "TcxButton")
    print("[recon] 파일선택 버튼:", sel is not None)
    before2 = windows_of(session.pid)
    driver.click(sel)
    diff2 = wait_new(session.pid, before2)
    print(f"[recon] 파일선택 후 새 창: {diff2}")
    for h, (cls, name) in diff2.items():
        dlg_handles.append(h)
        try:
            dw = driver.window(h)
            dw.set_focus()
            time.sleep(0.6)
            p = ROOT / "reports" / f"recon_pdfdlg_{ts}_{cls}.png"
            dw.capture_as_image().save(str(p))
            print(f"[recon] 스냅샷 {p.name}")
            dump(h)
        except Exception as error:  # noqa: BLE001
            print(f"[recon] 덤프 실패 {h}: {error!r}")
    rc = 0
except Exception as error:  # noqa: BLE001
    traceback.print_exc()
    print(f"[recon] 실패 {error!r}")
finally:
    try:
        for h in dlg_handles:
            try:
                cancel = driver.by_text(h, "취소") or driver.by_text(h, "Cancel")
                if cancel is not None:
                    print("[recon] 대화상자 취소:", cancel.window_text())
                    driver.click_message(cancel)
                else:
                    driver.window(h).set_focus()
                    send_keys("{ESC}")
                time.sleep(0.8)
            except Exception as error:  # noqa: BLE001
                print(f"[recon] 취소 실패 {h}: {error!r}")
        if pdf_win:
            close = driver.by_text(pdf_win, "닫 기", "TcxButton")
            if close is not None:
                driver.click(close)
                time.sleep(0.8)
            navigate.decline_save_prompt(session, wait=2.0)
        navigate.close_context_menu()
        navigate.close_forms(session)
        print(f"[recon] 정리: 창={windows_of(session.pid)}")
    except Exception as error:  # noqa: BLE001
        print(f"[recon] 정리 실패 {error!r}")
    log.close()

sys.exit(rc)
