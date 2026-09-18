"""기업은행 발송완료 건 대조 러너 — 관리자 권한 python(UIPI). **읽기 전용**(입력·저장·발송 없음).

발송완료 탭 조건 조회 → 감정서번호마다 행 찾기(행 순회, '찾 기' 안 씀) → 작성(A) 폼 열기 → autofill_ibk 드라이런
(--no-touch: 콤보·행 추가도 안 건드림) 으로 "화면값 vs 우리 매핑값" 표 → 스크린샷 → '닫 기'.
발송완료 폼은 사람이 완성한 값이 다 들어 있으므로 표의 '일치' = 맞음, '✍'(채움/덮어씀/선택) = 우리 값이 화면과 다름, '미발견' = 칸 못 찾음.

    Start-Process python -ArgumentList '"...\\tools\\run_ibk_compare.py" <from> <to> <doc1,doc2,...> [탭]' -Verb RunAs -WindowStyle Hidden -Wait
출력: reports/ibkcmp_<ts>.log / _<doc>.png
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

DATE_FROM, DATE_TO = sys.argv[1], sys.argv[2]
DOCS = [d.strip() for d in sys.argv[3].split(",") if d.strip()]
TAB = sys.argv[4] if len(sys.argv) > 4 else "발송완료"
EXTRA = sys.argv[5:] or ["--no-touch"]
SURVEY = "--survey" in EXTRA          # 작성(A) 대신 현장조사서(E) 폼을 열어 survey_ibk 드라이런 대조
EXTRA = [e for e in EXTRA if e != "--survey"]

ts = time.strftime("%Y%m%d_%H%M%S")
log_path = ROOT / "reports" / f"ibkcmp_{ts}.log"
log_path.parent.mkdir(exist_ok=True)


class Tee(io.TextIOBase):
    def __init__(self, *streams):
        self.streams = streams

    def write(self, s):
        for st in self.streams:
            st.write(s)
            st.flush()
        return len(s)


log = open(log_path, "w", encoding="utf-8", errors="replace")
sys.stdout = Tee(log)
sys.stderr = Tee(log)

print(f"[runner] start {ts}, 탭={TAB}, 기간={DATE_FROM}~{DATE_TO}, 대상={DOCS}, 옵션={EXTRA}")
from bankon.config import load_config  # noqa: E402
from bankon.ui import driver, navigate  # noqa: E402
import autofill_ibk  # noqa: E402
import autofill_survey  # noqa: E402

rc = 1
try:
    cfg = load_config(None)
    session = navigate.open_app(cfg.loader_cmd, cfg.bankon_user, cfg.bankon_password)
    if not navigate.select_tab(session, TAB):
        raise navigate.NavigationError(f"{TAB} 탭 선택 실패")
    navigate.query_documents(session, start=DATE_FROM, end=DATE_TO, work_type="담보")
    navigate.close_forms(session)
    rc = 0
    for doc_id in DOCS:
        print(f"\n================ 기업 {doc_id} ================")
        try:
            navigate.close_forms(session)
            found = False
            for attempt in range(3):
                if navigate.find_row_by_doc(session, doc_id):
                    found = True
                    break
                print(f"[runner] {doc_id} 행 못 찾음 — 재조회 {attempt + 1}/3")
                navigate.query_documents(session, start=DATE_FROM, end=DATE_TO, work_type="담보")
                navigate.close_forms(session)
            if not found:
                raise navigate.NavigationError(f"{doc_id} 행 탐색 실패(기간·탭 확인)")
            if SURVEY:
                form_ref = navigate.open_survey_form(session)
                print(f"[runner] 폼: {form_ref.class_name} — {form_ref.title}")
                if not form_ref.class_name.startswith("TBNKKIB"):
                    raise navigate.NavigationError(f"기업 현장조사서 폼이 아님: {form_ref.class_name}")
                try:
                    r = autofill_survey.main([doc_id])          # 드라이런(--live 없음)
                except SystemExit as stop:
                    print(f"[runner] autofill_survey 중단: {stop}")
                    r = 1
                print(f"[runner] autofill_survey exit = {r}")
            else:
                form_ref = navigate.open_write_form(session, home=False)
                print(f"[runner] 폼: {form_ref.class_name} — {form_ref.title}")
                if form_ref.class_name != autofill_ibk.FORM_CLASS:
                    raise navigate.NavigationError(f"기업 폼이 아님: {form_ref.class_name}")
                try:
                    r = autofill_ibk.main([doc_id, *EXTRA])
                except SystemExit as stop:
                    print(f"[runner] autofill_ibk 중단: {stop}")
                    r = 1
                print(f"[runner] autofill_ibk exit = {r}")
            rc = rc or r
            try:
                w = driver.window(form_ref.handle)
                w.set_focus()
                time.sleep(0.5)
                snap = ROOT / "reports" / f"ibkcmp_{ts}_{doc_id}.png"
                w.capture_as_image().save(str(snap))
                print(f"[runner] 스냅샷: {snap.name}")
            except Exception as error:  # noqa: BLE001
                print(f"[runner] 스냅샷 실패: {error!r}")
        except Exception as error:  # noqa: BLE001
            traceback.print_exc()
            print(f"[runner] {doc_id} 실패: {error!r}")
            rc = 1
        finally:
            navigate.close_context_menu()
            if SURVEY:
                navigate.close_survey_forms(session)
            navigate.close_forms(session)
            print(f"[runner] 폼 닫기(저장 없음). 남은 폼={len(navigate.open_forms(session))}")
except Exception as error:  # noqa: BLE001
    traceback.print_exc()
    print(f"[runner] exception: {error!r}")
finally:
    log.close()

sys.exit(rc)
