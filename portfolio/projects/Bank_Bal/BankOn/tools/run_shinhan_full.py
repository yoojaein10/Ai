"""★실서버 쓰기★ 신한 한 건 통합 러너(관리자 권한, 콘솔 숨김 필수).

    작성(A) 열기 → 입력(텍스트·콤보·물건 행) → 저 장 → PDF등록(전례 PDF 자동 탐색) → 폼 닫기
    → 포커스 행 확인(필요할 때만 재순회) → 현장조사서(E) 열기 → 입력 → 저 장 → 닫기
    → (--verify 일 때만) 두 폼 다시 열어 드라이런 대조 + PDF 창 재개봉 스크린샷.   발송(B/G)은 하지 않는다.

    Start-Process python -ArgumentList '"...\\tools\\run_shinhan_full.py" <from> <to> <doc> [옵션]' -Verb RunAs -WindowStyle Hidden -Wait
    --dry        입력·저장·PDF 없이 계획만(안전)        --no-pdf    PDF등록 건너뜀
    --verify     저장 뒤 두 폼을 다시 열어 재대조(기본 생략)
    --pdf <경로> 전례 탐색 대신 이 파일               --overwrite 이미 있는 값도 덮어씀
    --skip-write 작성 폼 단계 건너뜀                   --skip-survey 현장조사서 단계 건너뜀
    --tab <탭>   시험용(발송완료 탭에서 --dry 대조). 기본 작성
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
ROOT = _paths.APP_ROOT                       # exe 면 exe 폴더(reports/·work/), 소스면 저장소 루트
_paths.ensure_dirs()
os.chdir(ROOT)

ARGS = sys.argv[1:]
DATE_FROM, DATE_TO, DOC = ARGS[0], ARGS[1], ARGS[2]
OPTS = ARGS[3:]
DRY = "--dry" in OPTS
VERIFY = "--verify" in OPTS   # 저장 뒤 다시 열어 대조(기본 생략)
NO_PDF = "--no-pdf" in OPTS
SKIP_WRITE = "--skip-write" in OPTS
SKIP_SURVEY = "--skip-survey" in OPTS
OVERWRITE = ["--overwrite"] if "--overwrite" in OPTS else []
FORCE = "--force" in OPTS      # 사람이 작성한 폼이어도 진행(시연·재작성 — 덮어쓸 수 있음)
PDF_ARG = OPTS[OPTS.index("--pdf") + 1] if "--pdf" in OPTS else None
TAB_ARG = OPTS[OPTS.index("--tab") + 1] if "--tab" in OPTS else "작성"   # 시험용: --tab 발송완료 (드라이런 대조)

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
import autofill_shinhan                      # noqa: E402
import autofill_survey                       # noqa: E402


def snap(handle: int, tag: str) -> str:
    w = driver.window(handle)
    w.set_focus()
    time.sleep(0.6)
    path = ROOT / "reports" / f"full_{ts}_{tag}.png"
    w.capture_as_image().save(str(path))
    return path.name


def step(title: str) -> None:
    print(f"\n======== {title} ========")


summary: dict[str, str] = {}
import human_guard                           # noqa: E402  (사람 작성·이미 발송완료 → exit 3 '제외')

rc = 1
session = None
upload_pending = False   # 업로드 미완 PDF 창이 남아 있으면 finally 정리에서 닫지 않는다
try:
    mode = "DRY(입력·저장·PDF 없음)" if DRY else "★LIVE+저장" + ("" if NO_PDF else "+PDF등록")
    print(f"[runner] start {ts} 대상={DOC} 기간={DATE_FROM}~{DATE_TO} 모드={mode} 옵션={OPTS}")

    # PDF 경로는 화면을 건드리기 전에 먼저 확정한다. 자동 탐색에서 못 찾으면 그 PDF 등록만 건너뛰고(★로그 'PDF 건너뜀'),
    # 입력·저장은 그대로 진행해 '완료'로 남긴다 — 사람이 확인해 수동 등록(사용자 결정 2026-09-03).
    # --pdf/--survey-pdf 로 지정한 파일이 없거나 파일이 깨진(1000B 미만) 경우는 여전히 시작 전 중단(fail-closed).
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
        # 은행 확인이 가드보다 먼저다 — 엉뚱한 은행 폼이 열렸는데 가드가 먼저 돌면
        # '사람 작성 → 제외'(재시도 없음)로 조용히 끝난다(오제외 실증 2026-09-15 타 은행 러너).
        if not form.class_name.startswith("TBNKSHG"):
            raise RuntimeError(f"신한 폼이 아닙니다: {form.class_name} (은행 판별 오류?)")
        human_guard.assert_not_written(form, "신한", summary, force=FORCE)   # 사람이 작성한 폼이면 Excluded(exit 3)
        r1 = autofill_shinhan.main([DOC, "--all-objects"] + ([] if DRY else ["--live"]) + OVERWRITE)
        print(f"[runner] autofill_shinhan exit={r1} · 스냅샷 {snap(form.handle, 'write_filled')}")
        summary["write_fill"] = f"exit={r1}"
        if not DRY:
            if r1 != 0:   # 거부 칸은 비운 채(콤보는 원래 값으로 되돌린 채) 저장하고 계속 — 담당자가 한 번 더 본다(사용자 결정 2026-09-03)
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
                navigate.ensure_pdf_uploaded(result)   # 업로드 미완이면 닫지 않고 실패(PdfUploadPending)
                print(f"[runner] PDF 창 닫기: {navigate.close_pdf_windows(session)}")
                summary["pdf_attach"] = f"{result['elapsed']}s prompts={result['prompts']}"
        navigate.close_forms(session, timeout=40.0)
        remaining = len(navigate.open_forms(session))
        print(f"[runner] 작성 폼 닫힘. 남은 폼={remaining}")
        if remaining:
            raise RuntimeError(f"작성 폼이 닫히지 않았습니다(남은 폼={remaining}) — 현장조사서 단계로 넘어가지 않음")

    # ── 2) 포커스 확인 → 필요할 때만 재순회 ───────────────────────
    step("2) 포커스 행 확인")
    how = navigate.ensure_row(session, DOC, requery=requery)
    print(f"[runner] 행 위치: {how}")
    summary["refocus"] = how

    # ── 3) 현장조사서 ────────────────────────────────────────────
    if not SKIP_SURVEY:
        step("3) 현장조사서(E) — 입력" + ("" if DRY else " → 저장"))
        survey = navigate.open_survey_form(session)
        print(f"[runner] 폼: {survey.class_name} — {survey.title}")
        r2 = autofill_survey.main([DOC] + ([] if DRY else ["--live"]) + OVERWRITE)
        print(f"[runner] autofill_survey exit={r2} · 스냅샷 {snap(survey.handle, 'survey_filled')}")
        summary["survey_fill"] = f"exit={r2}"
        if not DRY:
            if r2 != 0:
                print("[runner] ★현장조사서 입력 거부 있음 — 거부 칸은 비운 채 저장하고 진행(담당자 확인 필요)")
                summary["survey_rejected"] = "있음(빈칸 저장)"
            pressed = navigate.save_form(session, survey, tag="survey")
            print(f"[runner] 저장 확인창: {pressed}")
            summary["survey_save"] = str(pressed)
        navigate.close_survey_forms(session)
        print(f"[runner] 현장조사서 닫힘. 남은={len(navigate.survey_forms(session))}")

    # ── 4) 검증(선택: --verify) ─────────────────────────────────
    if not DRY and not VERIFY:
        print("[runner] 4) 검증 단계 생략(--verify 로 켬)")
    if not DRY and VERIFY:
        step("4) 검증 — 다시 열어 대조")
        decline = lambda s, **k: navigate.decline_save_prompt(s, wait=k.get("wait", 1.0))  # noqa: E731
        if not SKIP_WRITE:
            print("[runner] 행 위치:", navigate.ensure_row(session, DOC, requery=requery))
            form = navigate.open_write_form(session, home=False)
            v1 = autofill_shinhan.main([DOC, "--all-objects"])
            print(f"[runner] 작성 폼 재대조 exit={v1} · 스냅샷 {snap(form.handle, 'write_verify')}")
            summary["write_verify"] = f"exit={v1}"
            if pdf_path:
                pdf_win = navigate.open_pdf_window(session, form)
                time.sleep(2.0)
                kinds = {}
                for c in driver.descendants(pdf_win.handle):
                    try:
                        kinds[c.element_info.class_name] = kinds.get(c.element_info.class_name, 0) + 1
                    except Exception:
                        pass
                has_viewer = any("AVL" in k or "ATL" in k for k in kinds)
                print(f"[runner] PDF 재개봉: 뷰어={'있음' if has_viewer else '없음'} · 스냅샷 {snap(pdf_win.handle, 'pdf_verify')}")
                summary["pdf_verify"] = "뷰어 있음" if has_viewer else "뷰어 없음(확인 필요)"
                navigate.close_pdf_windows(session, on_prompt=decline)
            navigate.close_forms(session)
        if not SKIP_SURVEY:
            print("[runner] 행 위치:", navigate.ensure_row(session, DOC, requery=requery))
            survey = navigate.open_survey_form(session)
            v2 = autofill_survey.main([DOC])
            print(f"[runner] 현장조사서 재대조 exit={v2} · 스냅샷 {snap(survey.handle, 'survey_verify')}")
            summary["survey_verify"] = f"exit={v2}"
            navigate.close_survey_forms(session)
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
            # 업로드가 도는 창에 '닫 기'를 누르면 폼이 바쁜 상태로 굳는다 — 그대로 두고 사람이 확인.
            # 다음 재시도의 requery() 정리 시점엔 업로드가 끝나 있어 정상적으로 닫힌다.
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
