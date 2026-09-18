"""현장조사서 러너(관리자 권한): 목록 → 행 → '현장조사서 작성(E)' → autofill_survey(드라이런/--live)
→ 스크린샷 → '닫 기'(저장 없음).
실행: Start-Process python -ArgumentList '"...\tools\run_survey_test.py" <from> <to> <doc> [탭] [--live]' -Verb RunAs -Wait
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
sys.path.insert(0, str(ROOT / "tools"))

DATE_FROM, DATE_TO, DOC = sys.argv[1], sys.argv[2], sys.argv[3]
TAB = sys.argv[4] if len(sys.argv) > 4 and not sys.argv[4].startswith("--") else "작성"
EXTRA = [a for a in sys.argv[4:] if a.startswith("--")]

ts = time.strftime("%Y%m%d_%H%M%S")
log = open(ROOT / "reports" / f"survey_{ts}.log", "w", encoding="utf-8", errors="replace")


class Tee(io.TextIOBase):
    def write(self, s):
        for st in (sys.__stdout__, log):
            st.write(s)
            st.flush()
        return len(s)


sys.stdout = sys.stderr = Tee()

from bankon.config import load_config      # noqa: E402
from bankon.ui import driver, navigate      # noqa: E402
import autofill_survey                       # noqa: E402

rc = 1
session = None
try:
    print(f"[runner] start {ts} 탭={TAB} 기간={DATE_FROM}~{DATE_TO} 대상={DOC} extra={EXTRA}")
    cfg = load_config(None)
    session = navigate.open_app(cfg.loader_cmd, cfg.bankon_user, cfg.bankon_password)
    navigate.select_tab(session, TAB)
    navigate.query_documents(session, start=DATE_FROM, end=DATE_TO, work_type="담보")
    navigate.close_forms(session)
    navigate.close_survey_forms(session)
    found = False
    for attempt in range(3):
        if attempt:
            print(f"[runner] 재조회·재순회 {attempt + 1}/3")
            navigate.query_documents(session, start=DATE_FROM, end=DATE_TO, work_type="담보")
        if navigate.find_row_by_doc(session, DOC):
            found = True
            break
    if not found:
        raise navigate.NavigationError(f"{DOC} 행 없음")
    form_ref = navigate.open_survey_form(session)
    print(f"[runner] 폼: {form_ref.class_name} — {form_ref.title}")
    try:
        rc = autofill_survey.main([DOC, *EXTRA])
    except SystemExit as stop:
        print(f"[runner] 중단: {stop}")
        rc = 1
    w = driver.window(form_ref.handle)
    w.set_focus()
    time.sleep(0.5)
    snap = ROOT / "reports" / f"survey_{ts}_{form_ref.class_name}.png"
    w.capture_as_image().save(str(snap))
    print(f"[runner] 스냅샷 {snap.name}")
except Exception as error:  # noqa: BLE001
    traceback.print_exc()
    print(f"[runner] 실패 {error!r}")
finally:
    try:
        navigate.close_context_menu()
        navigate.close_survey_forms(session)
        navigate.close_forms(session)
        print(f"[runner] 닫기(저장 없음). 남은 현장조사서={len(navigate.survey_forms(session))}")
    except Exception as error:  # noqa: BLE001
        print(f"[runner] 닫기 실패 {error!r}")
    log.close()

sys.exit(rc)
