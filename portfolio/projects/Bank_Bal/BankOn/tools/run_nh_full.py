"""★실서버 쓰기★ 농협 한 건 통합 러너(관리자 권한, 콘솔 숨김 필수). run_shinhan_full 과 같은 흐름.

    작성(A) 열기 → 입력(autofill_nh, 화면이 보고 있는 물건 슬롯) → 저 장 → PDF등록(전례 감정서 PDF) → 폼 닫기
    → 포커스 행 확인 → 현장조사서(E) 열기 → **농협은행은 입력 칸이 없다**("별도 작성 없이 PDF 파일만 등록",
      정찰 2026-09-07 TBNKNHB24Hyun '농협은행' 탭) → 현장조사서 PDF등록 → 닫기.   발송(B/G)은 하지 않는다.
    지역·품목농협(농협중앙회 탭: 교통비·물건조사비·… 비용 칸)은 아직 매핑이 없어 PDF 등록만 하고 비용 칸은 사람이 넣는다
    (큐 워커는 지역농협을 '보류'로 걸러 이 러너까지 오지 않는다).

    Start-Process python -ArgumentList '"...\\tools\\run_nh_full.py" <from> <to> <doc> [옵션]' -Verb RunAs -WindowStyle Hidden -Wait
    --dry        입력·저장·PDF 없이 계획만(안전)        --no-pdf    PDF등록 건너뜀
    --pdf <경로> 전례 탐색 대신 이 파일               --survey-pdf <경로> 현장조사서 PDF(기본: 전례 폴더 '현장조사서.pdf')
    --overwrite  이미 있는 값도 덮어씀                 --skip-write / --skip-survey  단계 건너뜀
    --seq N      우리 물건 순번 지정(다물건)            --tab <탭>  시험용(발송완료 탭에서 --dry 대조). 기본 작성
출력: reports/full_<ts>.log, full_<ts>_*.png, prompt_*.png
"""
from __future__ import annotations

import io
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
from bankon import paths as _paths          # noqa: E402
ROOT = _paths.APP_ROOT
_paths.ensure_dirs()
os.chdir(ROOT)

ARGS = sys.argv[1:]
DATE_FROM, DATE_TO, DOC = ARGS[0], ARGS[1], ARGS[2]
OPTS = ARGS[3:]
DRY = "--dry" in OPTS
NO_PDF = "--no-pdf" in OPTS
SKIP_WRITE = "--skip-write" in OPTS
SKIP_SURVEY = "--skip-survey" in OPTS
OVERWRITE = ["--overwrite"] if "--overwrite" in OPTS else []
FORCE = "--force" in OPTS      # 사람이 작성한 폼이어도 진행(시연·재작성 — 덮어쓸 수 있음)
PDF_ARG = OPTS[OPTS.index("--pdf") + 1] if "--pdf" in OPTS else None
SURVEY_PDF_ARG = OPTS[OPTS.index("--survey-pdf") + 1] if "--survey-pdf" in OPTS else None
SEQ_ARG = ["--seq", OPTS[OPTS.index("--seq") + 1]] if "--seq" in OPTS else []
TAB_ARG = OPTS[OPTS.index("--tab") + 1] if "--tab" in OPTS else "작성"

ts = time.strftime("%Y%m%d_%H%M%S")
log = open(ROOT / "reports" / f"full_{ts}.log", "w", encoding="utf-8", errors="replace")


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
import autofill_nh                           # noqa: E402

WRITE_CLASS = "TBNKNHB24DAMB"
SURVEY_CLASS = "TBNKNHB24Hyun"


def snap(handle: int, tag: str) -> str:
    w = driver.window(handle)
    w.set_focus()
    time.sleep(0.6)
    path = ROOT / "reports" / f"full_{ts}_{tag}.png"
    w.capture_as_image().save(str(path))
    return path.name


def step(title: str) -> None:
    print(f"\n======== {title} ========")


def open_survey_pdf_window(session, survey) -> driver.WindowRef:
    """현장조사서 폼의 **보이는** 'PDF등록' 버튼 → PDF 첨부 창. 농협 현장조사서는 탭 2장(농협은행/농협중앙회)에
    PDF등록 버튼이 하나씩 있어 첫 번째 매칭이 숨은 탭의 버튼일 수 있다(정찰 2026-09-07: @371,192 / @371,267)."""
    buttons = [c for c in driver.descendants(survey.handle)
               if (c.element_info.class_name or "") == "TcxButton"
               and (c.window_text() or "").replace(" ", "") == "PDF등록" and driver._visible(c)]
    if not buttons:
        raise navigate.NavigationError("현장조사서 폼에서 보이는 'PDF등록' 버튼을 찾지 못했습니다.")
    before = navigate._windows_of(session)
    driver.click(buttons[0])
    win = navigate._wait_new_window(session, before, class_name=navigate.PDF_WINDOW_CLASS)
    if win is None:
        raise navigate.NavigationError("현장조사서 PDF 첨부 창이 열리지 않았습니다.")
    time.sleep(0.8)
    return win


summary: dict[str, str] = {}
import human_guard                           # noqa: E402  (사람 작성·이미 발송완료 → exit 3 '제외')

rc = 1
session = None
upload_pending = False
try:
    mode = "DRY(입력·저장·PDF 없음)" if DRY else "★LIVE+저장" + ("" if NO_PDF else "+PDF등록")
    print(f"[runner] start {ts} 대상={DOC} 기간={DATE_FROM}~{DATE_TO} 모드={mode} 옵션={OPTS}")

    def locate(kind: str, explicit: str | None):
        path, why = archive.locate_pdf(DOC, kind, explicit)
        if path is None:
            print(f"[runner] ★PDF 건너뜀({kind}): {why}")
            summary["pdf_skipped"] = ",".join(x for x in (summary.get("pdf_skipped"), kind) if x)
            return None
        print(f"[runner] {kind} PDF: {path} ({path.stat().st_size / 1024:.0f} KB)")
        return path

    pdf_path = None if NO_PDF else locate("감정서", PDF_ARG)
    if pdf_path:
        summary["pdf"] = str(pdf_path)
    survey_pdf_path = None if (NO_PDF or SKIP_SURVEY) else locate("현장조사", SURVEY_PDF_ARG)
    if survey_pdf_path:
        summary["survey_pdf_file"] = survey_pdf_path.name

    cfg = load_config(None)
    session = navigate.open_app(cfg.loader_cmd, cfg.bankon_user, cfg.bankon_password)
    navigate.select_tab(session, TAB_ARG)

    def requery():
        navigate.query_documents(session, start=DATE_FROM, end=DATE_TO, work_type="담보")
        navigate.close_pdf_windows(session, on_prompt=lambda s, **k: navigate.decline_save_prompt(s, wait=k.get("wait", 1.0)))
        navigate.close_forms(session)
        navigate.close_survey_forms(session)

    requery()
    print("[runner] 행 위치:", human_guard.ensure_row_or_sent(session, DOC, requery=requery,
                                                            date_from=DATE_FROM, date_to=DATE_TO))

    # ── 1) 작성 폼: 입력 → 저장 → PDF등록 → 닫기 ────────────────────
    if not SKIP_WRITE:
        step("1) 작성(A) — 입력" + ("" if DRY else " → 저장" + (" → PDF등록" if pdf_path else "")))
        form = navigate.open_write_form(session, home=False)
        print(f"[runner] 폼: {form.class_name} — {form.title}")
        if form.class_name != WRITE_CLASS:                      # 은행 확인이 가드보다 먼저(오제외 방지 2026-09-15)
            raise navigate.NavigationError(f"농협 폼이 아닙니다: {form.class_name}")
        human_guard.assert_not_written(form, "농협", summary, force=FORCE)   # 사람이 작성한 폼이면 Excluded(exit 3)
        r1 = autofill_nh.main([DOC] + SEQ_ARG + ([] if DRY else ["--live"]) + OVERWRITE)
        print(f"[runner] autofill_nh exit={r1} · 스냅샷 {snap(form.handle, 'write_filled')}")
        summary["write_fill"] = f"exit={r1}"
        if r1 == autofill_nh.EXIT_UNALIGNED:
            # 채운 게 없다 — '거부(빈칸 저장)'와 다르다. 빈 폼을 저장·완료 처리하면 안 되므로 저장 없이 실패(fail-closed).
            raise RuntimeError("다물건 정합 불명확 — 입력하지 않았습니다(저장 안 함, 담당자 수동)")
        align = autofill_nh.LAST_ALIGN or {}
        if align.get("total", 1) >= 2:
            # 농협 폼은 물건 슬롯을 화면이 관리한다(일련번호 앵커). 슬롯 넘김은 아직 자동화 안 됨 → 나머지는 사람이.
            summary["multi_object"] = f"물건 {align['total']}개 중 슬롯 {align.get('screen_seq') or '?'}(우리 {align.get('resolved')})만 입력 — 나머지 수동"
            print(f"[runner] ★다물건: {summary['multi_object']}")
        if not DRY:
            if r1 != 0:
                print("[runner] ★작성 폼 입력 거부 있음 — 거부 칸은 비운 채 저장하고 진행(담당자 확인 필요)")
                summary["write_rejected"] = "있음(빈칸 저장)"
            pressed = navigate.save_form(session, form, tag="write")
            print(f"[runner] 저장 확인창: {pressed}")
            summary["write_save"] = str(pressed)
            if not any(w.handle == form.handle for w in navigate.open_forms(session)):
                raise RuntimeError("저장 후 작성 폼이 사라졌습니다 — PDF등록 전 확인 필요")
            if pdf_path:
                result = navigate.attach_pdf(session, form, str(pdf_path))
                print(f"[runner] PDF등록: 확인창={result['prompts']} 소요={result['elapsed']}s 뷰어={'표시됨' if result.get('viewer') else '미표시(업로드 미완 가능)'}")
                pdf_win = result["pdf_window"]
                if any(w.handle == pdf_win.handle for w in navigate.pdf_windows(session)):
                    print(f"[runner] 스냅샷 {snap(pdf_win.handle, 'pdf_attached')}")
                navigate.ensure_pdf_uploaded(result)
                print(f"[runner] PDF 창 닫기: {navigate.close_pdf_windows(session)}")
                summary["pdf_attach"] = f"{result['elapsed']}s prompts={result['prompts']}"
        navigate.close_forms(session, timeout=40.0)
        remaining = len(navigate.open_forms(session))
        print(f"[runner] 작성 폼 닫힘. 남은 폼={remaining}")
        if remaining:
            raise RuntimeError(f"작성 폼이 닫히지 않았습니다(남은 폼={remaining}) — 현장조사서 단계로 넘어가지 않음")

    # ── 2) 포커스 확인 ───────────────────────────────────────────
    step("2) 포커스 행 확인")
    how = navigate.ensure_row(session, DOC, requery=requery)
    print(f"[runner] 행 위치: {how}")
    summary["refocus"] = how

    # ── 3) 현장조사서: 농협은행은 PDF 등록만 ────────────────────────
    if not SKIP_SURVEY:
        step("3) 현장조사서(E) — " + ("열어서 확인만(DRY)" if DRY else "PDF등록" if survey_pdf_path else "PDF 없음(건너뜀)"))
        survey = navigate.open_survey_form(session)
        print(f"[runner] 폼: {survey.class_name} — {survey.title}")
        if survey.class_name != SURVEY_CLASS:
            raise navigate.NavigationError(f"농협 현장조사서 폼이 아닙니다: {survey.class_name}")
        tabs = [(c.window_text() or "").strip() for c in driver.descendants(survey.handle)
                if (c.element_info.class_name or "") == "TcxTabSheet"]
        print(f"[runner] 현장조사서 탭: {tabs} · 스냅샷 {snap(survey.handle, 'survey_opened')}")
        summary["survey"] = "농협은행(입력 칸 없음, PDF만)"
        if not DRY and survey_pdf_path:
            pdf_win = open_survey_pdf_window(session, survey)
            result = navigate.attach_pdf(session, survey, str(survey_pdf_path), pdf_win=pdf_win)
            print(f"[runner] 현장조사서 PDF등록({survey_pdf_path.name}): 확인창={result['prompts']} 소요={result['elapsed']}s")
            pdf_win = result["pdf_window"]
            if any(w.handle == pdf_win.handle for w in navigate.pdf_windows(session)):
                print(f"[runner] 스냅샷 {snap(pdf_win.handle, 'survey_pdf_attached')}")
            navigate.ensure_pdf_uploaded(result)
            print(f"[runner] PDF 창 닫기: {navigate.close_pdf_windows(session)}")
            summary["survey_pdf"] = f"{result['elapsed']}s prompts={result['prompts']}"
        navigate.close_survey_forms(session)
        print(f"[runner] 현장조사서 닫힘. 남은={len(navigate.survey_forms(session))}")
    rc = 0
except human_guard.Excluded as excluded:
    rc = human_guard.EXIT_EXCLUDED
    print(f"[runner] 제외 {excluded}")
    summary.setdefault("excluded", str(excluded))
except Exception as error:  # noqa: BLE001
    traceback.print_exc()
    print(f"[runner] 실패 {error!r}")
    summary["error"] = repr(error)
    upload_pending = isinstance(error, navigate.PdfUploadPending)
    try:
        if session:
            print(f"[runner] 실패 시점 메인 스냅샷 {snap(session.main.handle, 'main_on_error')}")
    except Exception:  # noqa: BLE001
        pass
finally:
    try:
        navigate.close_context_menu()
        if session and upload_pending:
            print("[runner] 업로드 미완 — PDF 창·폼을 닫지 않고 남겨둡니다(사람/재시도 확인)")
        elif session:
            navigate.close_pdf_windows(session, on_prompt=lambda s, **k: navigate.decline_save_prompt(s, wait=k.get("wait", 1.0)))
            navigate.close_survey_forms(session)
            navigate.close_forms(session)
            print(f"[runner] 정리: 남은 폼={len(navigate.open_forms(session))} 현장조사서={len(navigate.survey_forms(session))} PDF창={len(navigate.pdf_windows(session))}")
    except Exception as error:  # noqa: BLE001
        print(f"[runner] 정리 실패 {error!r}")
    print("\n[요약] " + " | ".join(f"{k}={v}" for k, v in summary.items()))
    print(f"[runner] exit={rc}")
    log.close()

sys.exit(rc)
