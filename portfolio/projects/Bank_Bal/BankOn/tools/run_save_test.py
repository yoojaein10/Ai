"""★실서버 쓰기★ 통합 러너(관리자 권한): 한 건을 작성(A) 입력→저장→닫기 → [포커스 행 확인, 필요 시만 재순회]
→ 현장조사서(E) 입력→저장→닫기 → 두 폼을 다시 열어 저장된 값 대조(드라이런). 발송(B/G)은 절대 하지 않는다.

    Start-Process python -ArgumentList '"...\\tools\\run_save_test.py" <from> <to> <doc> [--dry]' -Verb RunAs -Wait
    --dry : 입력·저장 없이 드라이런 보고만(안전).  없으면 LIVE 입력 + '저 장'.
출력: reports/save_<ts>.log, save_<ts>_*.png, prompt_*.png(확인창)
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
DRY = "--dry" in sys.argv[4:]
SURVEY_ONLY = "--survey-only" in sys.argv[4:]      # 현장조사서만(작성 폼 건너뜀)
OVERWRITE = ["--overwrite"] if "--overwrite" in sys.argv[4:] else []   # 이미 있는 값도 덮어씀
TAB = "작성"

ts = time.strftime("%Y%m%d_%H%M%S")
log = open(ROOT / "reports" / f"save_{ts}.log", "w", encoding="utf-8", errors="replace")


class Tee(io.TextIOBase):
    def write(self, s):
        for st in (sys.__stdout__, log):
            st.write(s)
            st.flush()
        return len(s)


sys.stdout = sys.stderr = Tee()

from bankon.config import load_config      # noqa: E402
from bankon.ui import driver, navigate      # noqa: E402
import autofill_shinhan                      # noqa: E402
import autofill_survey                       # noqa: E402


def snap(handle: int, tag: str) -> str:
    w = driver.window(handle)
    w.set_focus()
    time.sleep(0.5)
    path = ROOT / "reports" / f"save_{ts}_{tag}.png"
    w.capture_as_image().save(str(path))
    return path.name


def step(title: str) -> None:
    print(f"\n======== {title} ========")


rc = 1
session = None
try:
    print(f"[runner] start {ts} 대상={DOC} 기간={DATE_FROM}~{DATE_TO} 모드={'DRY(입력·저장 없음)' if DRY else '★LIVE+저장'}")
    cfg = load_config(None)
    session = navigate.open_app(cfg.loader_cmd, cfg.bankon_user, cfg.bankon_password)
    navigate.select_tab(session, TAB)

    def requery():
        navigate.query_documents(session, start=DATE_FROM, end=DATE_TO, work_type="담보")
        navigate.close_forms(session)
        navigate.close_survey_forms(session)

    requery()
    how = navigate.ensure_row(session, DOC, requery=requery)
    print(f"[runner] 행 위치: {how}")

    # ── 1) 작성 폼 ───────────────────────────────────────────────
    step("1) 작성(A) 폼 — 입력" + ("" if DRY else " + 저장") + (" [건너뜀 --survey-only]" if SURVEY_ONLY else ""))
    form = None if SURVEY_ONLY else navigate.open_write_form(session, home=False)
    if form is None:
        r1 = 0
    else:
      print(f"[runner] 폼: {form.class_name} — {form.title}")
      args = [DOC, "--all-objects"] + ([] if DRY else ["--live"]) + OVERWRITE
      r1 = autofill_shinhan.main(args)
    if form is not None:
      print(f"[runner] autofill_shinhan exit={r1}")
      print(f"[runner] 스냅샷 {snap(form.handle, 'write_filled')}")
    if not DRY and form is not None:
        if r1 != 0:
            raise RuntimeError("입력 중 거부가 있어 저장하지 않습니다(fail-closed).")
        pressed = navigate.save_form(session, form, tag="write")
        print(f"[runner] 저장 확인창: {pressed}")
        time.sleep(1.0)
        still = [w for w in navigate.open_forms(session) if w.handle == form.handle]
        print(f"[runner] 저장 후 폼 열림={bool(still)}")
        if still:
            print(f"[runner] 스냅샷 {snap(form.handle, 'write_saved')}")
    navigate.close_forms(session)
    print(f"[runner] 작성 폼 닫힘. 남은 폼={len(navigate.open_forms(session))}")

    # ── 2) 포커스 확인 → 필요할 때만 재순회 ───────────────────────
    step("2) 포커스 행 확인")
    how = navigate.ensure_row(session, DOC, requery=requery)
    print(f"[runner] 행 위치: {how}")

    # ── 3) 현장조사서 ────────────────────────────────────────────
    step("3) 현장조사서(E) — 입력" + ("" if DRY else " + 저장"))
    survey = navigate.open_survey_form(session)
    print(f"[runner] 폼: {survey.class_name} — {survey.title}")
    r2 = autofill_survey.main([DOC] + ([] if DRY else ["--live"]) + OVERWRITE)
    print(f"[runner] autofill_survey exit={r2}")
    print(f"[runner] 스냅샷 {snap(survey.handle, 'survey_filled')}")
    if not DRY:
        if r2 != 0:
            raise RuntimeError("현장조사서 입력 거부 — 저장하지 않습니다.")
        pressed = navigate.save_form(session, survey, tag="survey")
        print(f"[runner] 저장 확인창: {pressed}")
        time.sleep(1.0)
        if navigate.survey_forms(session):
            print(f"[runner] 스냅샷 {snap(survey.handle, 'survey_saved')}")
    navigate.close_survey_forms(session)
    print(f"[runner] 현장조사서 닫힘. 남은={len(navigate.survey_forms(session))}")

    # ── 4) 검증: 다시 열어 드라이런 대조 ──────────────────────────
    if not DRY:
        step("4) 검증 — 다시 열어 저장된 값 대조(드라이런)")
        if not SURVEY_ONLY:
            how = navigate.ensure_row(session, DOC, requery=requery)
            print(f"[runner] 행 위치: {how}")
            form = navigate.open_write_form(session, home=False)
            v1 = autofill_shinhan.main([DOC, "--all-objects"])
            print(f"[runner] 작성 폼 재대조 exit={v1} · 스냅샷 {snap(form.handle, 'write_verify')}")
            navigate.close_forms(session)
        how = navigate.ensure_row(session, DOC, requery=requery)
        print(f"[runner] 행 위치: {how}")
        survey = navigate.open_survey_form(session)
        v2 = autofill_survey.main([DOC])
        print(f"[runner] 현장조사서 재대조 exit={v2} · 스냅샷 {snap(survey.handle, 'survey_verify')}")
        navigate.close_survey_forms(session)
    rc = 0
except Exception as error:  # noqa: BLE001
    traceback.print_exc()
    print(f"[runner] 실패 {error!r}")
finally:
    try:
        navigate.close_context_menu()
        navigate.close_survey_forms(session)
        navigate.close_forms(session)
        print(f"[runner] 정리 완료. 남은 폼={len(navigate.open_forms(session))} 현장조사서={len(navigate.survey_forms(session))}")
    except Exception as error:  # noqa: BLE001
        print(f"[runner] 정리 실패 {error!r}")
    log.close()

sys.exit(rc)
