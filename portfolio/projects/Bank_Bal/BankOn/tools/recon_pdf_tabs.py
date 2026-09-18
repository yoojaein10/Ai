"""국민 작성 폼 PDF등록 창(TBnkTop24pdf) 탭 정찰 — 파일 업로드 없음. 탭 컨트롤 덤프 + 탭마다 클릭·스냅 뒤 '닫 기'.
실행: Start-Process python -ArgumentList '"...\\tools\\recon_pdf_tabs.py" <from> <to> <doc> [탭]' -Verb RunAs -WindowStyle Minimized -Wait
"""
from __future__ import annotations
import io, os, sys, time, traceback
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT / "src"))
DATE_FROM, DATE_TO, DOC = sys.argv[1], sys.argv[2], sys.argv[3]
TAB = sys.argv[4] if len(sys.argv) > 4 else "발송완료"
ts = time.strftime("%Y%m%d_%H%M%S")
TAG = f"recon_pdftabs_{ts}"
log = open(ROOT / "reports" / f"{TAG}.log", "w", encoding="utf-8", errors="replace")
class Tee(io.TextIOBase):
    def write(self, s):
        for st in (sys.__stdout__, log): st.write(s); st.flush()
        return len(s)
sys.stdout = sys.stderr = Tee()
from bankon.config import load_config
from bankon.ui import driver, navigate


def snap(handle, name):
    w = driver.window(handle); w.set_focus(); time.sleep(0.6)
    w.capture_as_image().save(str(ROOT / "reports" / f"{TAG}_{name}.png")); print(f"[recon] 스냅 {name}")


def dump(handle, title):
    r = driver.window(handle).rectangle(); rows = []
    for c in driver.descendants(handle):
        try:
            cls = c.element_info.class_name or ""; txt = (c.window_text() or "").strip(); rc_ = driver._rect(c)
        except Exception: continue
        if rc_ is None: continue
        rows.append((rc_.top - r.top, rc_.left - r.left, cls, txt, rc_.right - rc_.left, rc_.bottom - rc_.top))
    rows.sort()
    print(f"[recon] ===== {title}: {len(rows)}개 (창 {r.right - r.left}x{r.bottom - r.top})")
    for t, l, cls, txt, w, h in rows:
        if h < 60 or "Tab" in cls or "Page" in cls:
            print(f"  @{t:4},{l:4} {cls:28} '{txt[:40]}' {w}x{h}")
    return rows


rc = 1; session = None
try:
    cfg = load_config(None)
    session = navigate.open_app(cfg.loader_cmd, cfg.bankon_user, cfg.bankon_password)
    if not navigate.select_tab(session, TAB):
        raise navigate.NavigationError(f"{TAB} 탭 선택 실패")
    navigate.query_documents(session, start=DATE_FROM, end=DATE_TO, work_type="담보")
    navigate.close_forms(session)
    if not navigate.find_row_by_doc(session, DOC):
        raise navigate.NavigationError(f"{DOC} 행 없음")
    form = navigate.open_write_form(session, home=False)
    print(f"[recon] 폼 {form.class_name} {form.title}")
    pdf_win = navigate.open_pdf_window(session, form)
    print(f"[recon] PDF창 {pdf_win.class_name} '{pdf_win.title}'")
    dump(pdf_win.handle, "PDF창(초기)")
    snap(pdf_win.handle, "tab0")
    # 탭 후보: 텍스트로 잡히는지
    for name in ("평가전례 첨부용", "(관련)수수료 등", "관련서류", "(원본)감정평가서"):
        c = driver.by_text(pdf_win.handle, name)
        print(f"[recon] by_text({name!r}) → {None if c is None else (c.element_info.class_name, driver._rect(c))}")
    # 픽셀 클릭(스크린샷 기준 탭 y≈37, x 중심) 뒤 스냅·덤프
    r = driver.window(pdf_win.handle).rectangle()
    for i, (name, x) in enumerate((("평가전례", 165), ("수수료", 265), ("관련서류", 345), ("원본", 60)), start=1):
        driver.window(pdf_win.handle).set_focus(); time.sleep(0.3)
        from pywinauto import mouse
        mouse.click(coords=(r.left + x, r.top + 37)); time.sleep(1.2)
        snap(pdf_win.handle, f"tab{i}_{name}")
        dump(pdf_win.handle, f"PDF창 탭 {name}")
        sel = driver.by_text(pdf_win.handle, "파일선택", "TcxButton")
        print(f"[recon] 탭 {name}: 파일선택 버튼 {None if sel is None else driver._rect(sel)}")
    rc = 0
except Exception as e:
    traceback.print_exc(); print(f"[recon] 실패 {e!r}")
finally:
    if session:
        try:
            print(f"[recon] PDF창 닫기 {navigate.close_pdf_windows(session)}")
            navigate.close_forms(session)
            print(f"[recon] 남은 폼 {len(navigate.open_forms(session))}")
        except Exception as e:
            print(f"[recon] 정리 실패 {e!r}")
    log.close()
sys.exit(rc)
