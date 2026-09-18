"""★실서버 쓰기★ PDF등록 러너(관리자 권한): 행 찾기 → 작성(A) 폼 → PDF등록 → 파일선택 → 전례 PDF 경로 입력 → 열기
→ 확인창 처리(스크린샷) → 닫기 → 다시 PDF등록 열어 등록 여부 확인(스크린샷) → 닫기. 발송 없음.

    Start-Process python -ArgumentList '"...\\tools\\run_pdf_test.py" <from> <to> <doc> [--pdf <경로>]' -Verb RunAs -WindowStyle Hidden -Wait
경로를 안 주면 sources/archive.find_pdf 로 전례 공유폴더에서 찾는다.
출력: reports/pdf_<ts>.log, pdf_<ts>_*.png, prompt_pdf*.png
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
PDF_ARG = sys.argv[sys.argv.index("--pdf") + 1] if "--pdf" in sys.argv else None

ts = time.strftime("%Y%m%d_%H%M%S")
log = open(ROOT / "reports" / f"pdf_{ts}.log", "w", encoding="utf-8", errors="replace")


class Tee(io.TextIOBase):
    def write(self, s):
        for st in (sys.__stdout__, log):
            st.write(s)
            st.flush()
        return len(s)


sys.stdout = sys.stderr = Tee()

from bankon.config import load_config       # noqa: E402
from bankon.sources import archive           # noqa: E402
from bankon.ui import driver, navigate       # noqa: E402


def snap(handle: int, tag: str) -> str:
    w = driver.window(handle)
    w.set_focus()
    time.sleep(0.6)
    path = ROOT / "reports" / f"pdf_{ts}_{tag}.png"
    w.capture_as_image().save(str(path))
    return path.name


def windows() -> dict:
    return {w.handle: (w.class_name, w.title) for w in driver.find_windows(pid=session.pid)}


rc = 1
session = None
try:
    print(f"[runner] start {ts} 대상={DOC}")
    pdf_path = Path(PDF_ARG) if PDF_ARG else archive.find_pdf(DOC)
    size = pdf_path.stat().st_size
    print(f"[runner] PDF: {pdf_path} ({size / 1_048_576:.1f} MB)")
    if size < 1000:
        raise RuntimeError("PDF 크기가 너무 작습니다 — 중단")

    cfg = load_config(None)
    session = navigate.open_app(cfg.loader_cmd, cfg.bankon_user, cfg.bankon_password)
    navigate.select_tab(session, "작성")

    def requery():
        navigate.query_documents(session, start=DATE_FROM, end=DATE_TO, work_type="담보")
        navigate.close_forms(session)

    requery()
    print("[runner] 행 위치:", navigate.ensure_row(session, DOC, requery=requery))
    form = navigate.open_write_form(session, home=False)
    print(f"[runner] 폼: {form.class_name} — {form.title}")

    print("\n======== PDF등록 → 파일선택 → 열기 ========")
    result = navigate.attach_pdf(session, form, str(pdf_path))
    print(f"[runner] 확인창: {result['prompts']} · 소요 {result['elapsed']}s")
    pdf_win = result["pdf_window"]
    print(f"[runner] 창 목록: {windows()}")
    if any(w.handle == pdf_win.handle for w in navigate.pdf_windows(session)):
        print(f"[runner] 스냅샷 {snap(pdf_win.handle, 'after_open')}")
        # 첨부 후 버튼 상태
        for text in ("별도창으로 열기", "파일선택", "닫 기"):
            b = driver.by_text(pdf_win.handle, text, "TcxButton")
            print(f"[runner] 버튼 '{text}': {'있음' if b else '없음'} enabled={b.is_enabled() if b else None}")
    pressed = navigate.close_pdf_windows(session)
    print(f"[runner] PDF 창 닫기 확인창: {pressed}")
    time.sleep(1.0)
    print(f"[runner] 창 목록: {windows()}")

    print("\n======== 검증: PDF등록 다시 열기 ========")
    pdf_win2 = navigate.open_pdf_window(session, form)
    time.sleep(2.0)
    print(f"[runner] 스냅샷 {snap(pdf_win2.handle, 'verify')}")
    for text in ("별도창으로 열기", "파일선택"):
        b = driver.by_text(pdf_win2.handle, text, "TcxButton")
        print(f"[runner] 버튼 '{text}': enabled={b.is_enabled() if b else None}")
    # 창 안의 컨트롤(뷰어 등) 요약
    kinds = {}
    for c in driver.descendants(pdf_win2.handle):
        try:
            kinds[c.element_info.class_name] = kinds.get(c.element_info.class_name, 0) + 1
        except Exception:
            pass
    print(f"[runner] 검증 창 컨트롤: {kinds}")
    pressed = navigate.close_pdf_windows(session, on_prompt=lambda s, **k: navigate.decline_save_prompt(s, wait=k.get('wait', 1.0)))
    print(f"[runner] 검증 창 닫기: {pressed}")
    rc = 0
except Exception as error:  # noqa: BLE001
    traceback.print_exc()
    print(f"[runner] 실패 {error!r}")
finally:
    try:
        navigate.close_context_menu()
        # 남은 PDF 창은 닫되(등록 확인창이면 예), 작성 폼은 저장 없이 닫는다
        navigate.close_pdf_windows(session)
        navigate.close_forms(session)
        print(f"[runner] 정리: 남은 폼={len(navigate.open_forms(session))} 창={windows()}")
    except Exception as error:  # noqa: BLE001
        print(f"[runner] 정리 실패 {error!r}")
    log.close()

sys.exit(rc)
