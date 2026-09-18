"""작성 폼 'PDF등록' 버튼 정찰 — 읽기 전용(버튼 눌러 뜨는 창을 덤프·스크린샷 후 Esc/취소, 저장 없음).
실행: Start-Process python -ArgumentList '"...\\tools\\recon_pdf_button.py" <from> <to> <doc>' -Verb RunAs -WindowStyle Hidden -Wait
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
log = open(ROOT / "reports" / f"recon_pdfbtn_{ts}.log", "w", encoding="utf-8", errors="replace")


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


def all_windows(pid: int) -> dict:
    """pid 의 최상위 창 + (공통 대화상자는 다른 스레드/프로세스일 수 있어) 제목에 '열기'가 든 창도 포함."""
    out = {}
    for e in find_elements(backend="win32", top_level_only=True, visible_only=True):
        if not e.handle:
            continue
        same = int(e.process_id or 0) == pid
        name = (e.name or "").strip()
        if same or any(k in name for k in ("열기", "Open", "파일", "PDF")):
            out[int(e.handle)] = (e.class_name or "", name, int(e.process_id or 0))
    return out


def dump(handle: int, depth_limit: int = 400) -> None:
    w = driver.window(handle)
    r = w.rectangle()
    print(f"[recon] 창 rect={r}")
    n = 0
    for c in w.descendants():
        try:
            cls = c.element_info.class_name or ""
            txt = (c.window_text() or "").strip()
            rc_ = c.rectangle()
        except Exception:
            continue
        if not txt and cls in ("TPanel", "ScrollBar", "Static"):
            continue
        print(f"  @{rc_.top - r.top:4},{rc_.left - r.left:4} {cls:34} '{txt[:60]}'")
        n += 1
        if n >= depth_limit:
            print("  ...(생략)")
            break


rc = 1
session = None
form = None
new_handles: list[int] = []
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
    print(f"[recon] 폼 {form.class_name} {form.title}")
    w = driver.window(form.handle)
    w.set_focus()
    time.sleep(0.5)
    button = driver.by_text(form.handle, "PDF등록", "TcxButton")
    print("[recon] PDF등록 버튼:", button is not None, "enabled=", button.is_enabled() if button else None)
    if button is None:
        raise RuntimeError("PDF등록 버튼 없음")
    before = all_windows(session.pid)
    driver.click(button)
    deadline = time.monotonic() + 15
    diff = {}
    while time.monotonic() < deadline:
        now = all_windows(session.pid)
        diff = {h: v for h, v in now.items() if h not in before}
        if diff:
            time.sleep(1.0)
            now = all_windows(session.pid)
            diff = {h: v for h, v in now.items() if h not in before}
            break
        time.sleep(0.4)
    print(f"[recon] 새 창: {diff}")
    for h, (cls, name, pid) in diff.items():
        new_handles.append(h)
        try:
            dw = driver.window(h)
            dw.set_focus()
            time.sleep(0.5)
            p = ROOT / "reports" / f"recon_pdfbtn_{ts}_{cls}.png"
            dw.capture_as_image().save(str(p))
            print(f"[recon] 스냅샷 {p.name} ({cls} '{name}' pid={pid})")
            dump(h)
        except Exception as error:  # noqa: BLE001
            print(f"[recon] 덤프 실패 {h}: {error!r}")
    rc = 0
except Exception as error:  # noqa: BLE001
    traceback.print_exc()
    print(f"[recon] 실패 {error!r}")
finally:
    try:
        # 새로 뜬 창은 취소/ESC 로만 닫는다(아무것도 등록하지 않음)
        for h in new_handles:
            try:
                dw = driver.window(h)
                cancel = driver.by_text(h, "취소") or driver.by_text(h, "Cancel") or driver.by_text(h, "닫 기") or driver.by_text(h, "닫기")
                if cancel is not None:
                    print("[recon] 취소 버튼:", cancel.window_text())
                    driver.click_message(cancel)
                else:
                    dw.set_focus()
                    send_keys("{ESC}")
                time.sleep(0.8)
            except Exception as error:  # noqa: BLE001
                print(f"[recon] 취소 실패 {h}: {error!r}")
        navigate.close_context_menu()
        navigate.close_forms(session)
        print(f"[recon] 정리: 남은 폼={len(navigate.open_forms(session))} 창={all_windows(session.pid)}")
    except Exception as error:  # noqa: BLE001
        print(f"[recon] 정리 실패 {error!r}")
    log.close()

sys.exit(rc)
