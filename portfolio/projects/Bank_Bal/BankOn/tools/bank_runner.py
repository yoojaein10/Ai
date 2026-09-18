"""★실서버 쓰기★ '화면 슬롯 하나' 은행(수협·하나·우리·새마을) 통합 러너의 공통 몸통 — run_nh_full 과 같은 흐름.

    작성(A) 열기 → 입력(autofill_<bank>, 화면이 보고 있는 물건 슬롯) → 저 장 → PDF등록(전례 감정서 PDF) → 폼 닫기
    → 포커스 행 확인 → 현장조사서(E) 열기 → **PDF등록만** → 닫기.   발송(B/G)은 하지 않는다.

현장조사서: 이 4개 은행의 현장조사서 폼은 아직 **정찰하지 않았다**(입력 칸 매핑 없음). 농협은행(입력 칸 없음, PDF만)과
같은 식으로 PDF 만 등록하고, 폼에 DB 바인딩 입력 칸이 보이면 그 수를 요약(`survey`)에 남겨 담당자가 채우게 한다.
폼 클래스도 `TBNK<은행>24Hyun` 으로 **예측**한 값이라, 열린 폼이 다르면 클래스를 기록하고 현장조사서 단계는 건너뛴다(입력값 저장 없음).

    Start-Process python -ArgumentList '"...\\tools\\run_ssb_full.py" <from> <to> <doc> [옵션]' -Verb RunAs -WindowStyle Hidden -Wait
    --dry        입력·저장·PDF 없이 계획만(안전)        --no-pdf    PDF등록 건너뜀
    --pdf <경로> 전례 탐색 대신 이 파일               --survey-pdf <경로> 현장조사서 PDF(기본: 전례 폴더 '현장조사서.pdf')
    --overwrite  이미 있는 값도 덮어씀                 --skip-write / --skip-survey  단계 건너뜀
    --seq N      우리 물건 순번 지정(다물건)            --tab <탭>  시험용(발송완료 탭에서 --dry 대조). 기본 작성
출력: reports/full_<ts>.log, full_<ts>_*.png
"""
from __future__ import annotations

import io
import os
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))


@dataclass
class RunnerSpec:
    bank: str              # human_guard.INDICATORS 키(수협/하나/우리/새마을)
    write_class: str       # 작성 폼 클래스(TBNK…24DAMB)
    survey_class: str      # 현장조사서 폼 클래스 **예측**(TBNK…24Hyun)
    autofill: object       # autofill_<bank> 모듈(main · LAST_ALIGN · EXIT_UNALIGNED · EXIT_UNSUPPORTED)


class _Tee(io.TextIOBase):
    def __init__(self, log):
        self.log = log

    def write(self, s):
        for st in (sys.__stdout__, self.log):
            st.write(s)
            st.flush()
        return len(s)


def open_survey_pdf_window(driver, navigate, session, survey):
    """현장조사서 폼의 **보이는** 'PDF등록' 버튼 → PDF 첨부 창(탭이 여럿이면 숨은 탭 버튼을 피한다 — 농협 정찰 2026-09-07)."""
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


def survey_input_fields(driver, survey) -> list[str]:
    """현장조사서 폼의 DB 바인딩 입력 칸 클래스 목록(보이는 것만) — 매핑이 없는 폼에서 '사람이 채울 칸이 있다' 를 알리는 용도."""
    found = []
    for c in driver.descendants(survey.handle):
        try:
            name = c.element_info.class_name or ""
        except Exception:  # noqa: BLE001
            continue
        if name.startswith("TcxDB") and driver.is_input(name) and driver._visible(c):
            found.append(name)
    return found


def run(spec: RunnerSpec) -> int:
    from bankon import paths as _paths          # noqa: E402
    root = _paths.APP_ROOT
    _paths.ensure_dirs()
    os.chdir(root)

    args = sys.argv[1:]
    date_from, date_to, doc = args[0], args[1], args[2]
    opts = args[3:]
    dry = "--dry" in opts
    no_pdf = "--no-pdf" in opts
    skip_write = "--skip-write" in opts
    skip_survey = "--skip-survey" in opts
    overwrite = ["--overwrite"] if "--overwrite" in opts else []
    force = "--force" in opts          # 사람이 작성한 폼이어도 진행(시연·재작성 — 덮어쓸 수 있음)
    pdf_arg = opts[opts.index("--pdf") + 1] if "--pdf" in opts else None
    survey_pdf_arg = opts[opts.index("--survey-pdf") + 1] if "--survey-pdf" in opts else None
    seq_arg = ["--seq", opts[opts.index("--seq") + 1]] if "--seq" in opts else []
    tab_arg = opts[opts.index("--tab") + 1] if "--tab" in opts else "작성"

    ts = time.strftime("%Y%m%d_%H%M%S")
    log = open(root / "reports" / f"full_{ts}.log", "w", encoding="utf-8", errors="replace")
    sys.stdout = sys.stderr = _Tee(log)

    from bankon.config import load_config       # noqa: E402
    from bankon.sources import archive           # noqa: E402
    from bankon.ui import driver, navigate       # noqa: E402
    import human_guard                           # noqa: E402  (사람 작성·이미 발송완료 → exit 3 '제외')
    autofill = spec.autofill

    def snap(handle: int, tag: str) -> str:
        w = driver.window(handle)
        w.set_focus()
        time.sleep(0.6)
        path = root / "reports" / f"full_{ts}_{tag}.png"
        w.capture_as_image().save(str(path))
        return path.name

    def step(title: str) -> None:
        print(f"\n======== {title} ========")

    summary: dict[str, str] = {}
    rc = 1
    session = None
    upload_pending = False
    try:
        mode = "DRY(입력·저장·PDF 없음)" if dry else "★LIVE+저장" + ("" if no_pdf else "+PDF등록")
        print(f"[runner] start {ts} 대상={doc} 은행={spec.bank} 기간={date_from}~{date_to} 모드={mode} 옵션={opts}")

        def locate(kind: str, explicit: str | None):
            path, why = archive.locate_pdf(doc, kind, explicit)
            if path is None:
                print(f"[runner] ★PDF 건너뜀({kind}): {why}")
                summary["pdf_skipped"] = ",".join(x for x in (summary.get("pdf_skipped"), kind) if x)
                return None
            print(f"[runner] {kind} PDF: {path} ({path.stat().st_size / 1024:.0f} KB)")
            return path

        pdf_path = None if no_pdf else locate("감정서", pdf_arg)
        if pdf_path:
            summary["pdf"] = str(pdf_path)
        survey_pdf_path = None if (no_pdf or skip_survey) else locate("현장조사", survey_pdf_arg)
        if survey_pdf_path:
            summary["survey_pdf_file"] = survey_pdf_path.name

        cfg = load_config(None)
        session = navigate.open_app(cfg.loader_cmd, cfg.bankon_user, cfg.bankon_password)
        navigate.select_tab(session, tab_arg)

        def requery():
            navigate.query_documents(session, start=date_from, end=date_to, work_type="담보")
            navigate.close_pdf_windows(session, on_prompt=lambda s, **k: navigate.decline_save_prompt(s, wait=k.get("wait", 1.0)))
            navigate.close_forms(session)
            navigate.close_survey_forms(session)

        requery()
        print("[runner] 행 위치:", human_guard.ensure_row_or_sent(session, doc, requery=requery,
                                                                date_from=date_from, date_to=date_to))

        # ── 1) 작성 폼: 입력 → 저장 → PDF등록 → 닫기 ────────────────────
        if not skip_write:
            step("1) 작성(A) — 입력" + ("" if dry else " → 저장" + (" → PDF등록" if pdf_path else "")))
            form = navigate.open_write_form(session, home=False)
            print(f"[runner] 폼: {form.class_name} — {form.title}")
            if form.class_name != spec.write_class:
                raise navigate.NavigationError(f"{spec.bank} 폼이 아닙니다: {form.class_name}")
            human_guard.assert_not_written(form, spec.bank, summary, force=force)   # 사람이 작성한 폼이면 Excluded(exit 3)
            # --all-objects: 다물건이면 화면 물건 행을 늘려 전 물건을 채운다(사용자 결정 2026-09-16,
            # 2871 하나 실측 — 종전엔 슬롯 1만 채우고 나머지를 담당자가 손으로 만들어 넣었다).
            # --seq 를 직접 준 디버그 실행은 종전대로 슬롯 하나.
            all_objects = [] if seq_arg else ["--all-objects"]
            r1 = autofill.main([doc] + seq_arg + all_objects + ([] if dry else ["--live"]) + overwrite)
            print(f"[runner] autofill exit={r1} · 스냅샷 {snap(form.handle, 'write_filled')}")
            summary["write_fill"] = f"exit={r1}"
            align = autofill.LAST_ALIGN or {}
            if r1 == autofill.EXIT_UNALIGNED:
                # 채운 게 없다 — '거부(빈칸 저장)'와 다르다. 빈 폼을 저장·완료 처리하면 안 되므로 저장 없이 실패(fail-closed).
                raise RuntimeError("다물건 정합 불명확 — 입력하지 않았습니다(저장 안 함, 담당자 수동)")
            if r1 == autofill.EXIT_UNSUPPORTED:
                raise RuntimeError(f"미지원 물건 — 입력하지 않았습니다(저장 안 함, 담당자 수동): {align.get('guard')}")
            if align.get("slots"):
                # 폼은 물건 슬롯을 화면이 관리한다(일련번호 앵커). 몇 개를 채웠는지 그대로 비고에 남긴다.
                summary["multi_object"] = align["slots"]
                print(f"[runner] ★다물건: {summary['multi_object']}")
            elif align.get("total", 1) >= 2:
                summary["multi_object"] = f"물건 {align['total']}개 중 슬롯 {align.get('screen_seq') or '?'}(우리 {align.get('resolved')})만 입력 — 나머지 수동"
                print(f"[runner] ★다물건: {summary['multi_object']}")
            if not dry:
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
        how = navigate.ensure_row(session, doc, requery=requery)
        print(f"[runner] 행 위치: {how}")
        summary["refocus"] = how

        # ── 3) 현장조사서: PDF 등록만(입력 칸 미정찰) ──────────────────
        if not skip_survey:
            step("3) 현장조사서(E) — " + ("열어서 확인만(DRY)" if dry else "PDF등록" if survey_pdf_path else "PDF 없음(건너뜀)"))
            survey = navigate.open_survey_form(session)
            print(f"[runner] 폼: {survey.class_name} — {survey.title}")
            tabs = [(c.window_text() or "").strip() for c in driver.descendants(survey.handle)
                    if (c.element_info.class_name or "") == "TcxTabSheet"]
            inputs = survey_input_fields(driver, survey)
            print(f"[runner] 현장조사서 탭: {tabs} · DB 입력칸 {len(inputs)}개 · 스냅샷 {snap(survey.handle, 'survey_opened')}")
            if survey.class_name != spec.survey_class:
                # 예측한 클래스가 아니다 — 정찰이 필요하다. 입력·PDF 없이 닫고 사람에게 넘긴다(값 저장 없음).
                summary["survey"] = f"폼 클래스 예상 밖({survey.class_name}) — PDF·입력 모두 수동"
                print(f"[runner] ★현장조사서 폼이 예상({spec.survey_class})과 다름 → 건너뜀(수동)")
            else:
                summary["survey"] = (f"입력칸 {len(inputs)}개 미매핑(수동), PDF만" if inputs else "입력 칸 없음, PDF만")
                if not dry and survey_pdf_path:
                    pdf_win = open_survey_pdf_window(driver, navigate, session, survey)
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
    return rc
