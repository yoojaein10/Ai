"""오늘(2026-09-11) 큐에 찍힌 6건 Bank24 실화면 대조 — **읽기 전용**(입력·저장·발송 없음). 관리자 python 필요(UIPI).
run_cmp_nh_20260907.py 를 다은행판으로: 감정서번호마다 작성 탭(의뢰일 기준 기간) → 없으면 발송완료 탭 → 없으면 미접수 탭(행만 읽음)
→ 작성(A) 폼 열기 → 은행별 autofill 드라이런("화면값 vs 우리 매핑값" 표) → 스냅샷 → 닫기(저장 없음).
출력: reports/cmp_6docs_<ts>.log / _<doc>.png
"""
import sys, time, traceback, pathlib, os, datetime as dt
ROOT = pathlib.Path(r"D:\AI\Claude\Bank_Bal\BankOn")
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "tools"))
os.chdir(ROOT)

# (doc, bank, APW RequestDate, 큐 결과)
DOCS = [
    ("01-2609-3-2829", "국민", dt.date(2026, 9, 9),  "실패(로그인창 타임아웃)"),
    ("01-2608-3-2672", "농협", dt.date(2026, 8, 24), "완료"),
    ("01-2608-3-2739", "농협", dt.date(2026, 8, 31), "완료(물건 5개 중 슬롯1만)"),
    ("01-2609-3-2831", "신한", dt.date(2026, 9, 9),  "완료(+현장조사서)"),
    ("01-2609-3-2820", "농협", dt.date(2026, 9, 8),  "완료"),
    ("01-2609-3-2760", "하나", dt.date(2026, 9, 1),  "실패(행 못 찾음)"),
]

ts = time.strftime("%Y%m%d_%H%M%S")
log = open(ROOT / "reports" / f"cmp_6docs_{ts}.log", "w", encoding="utf-8", errors="replace", buffering=1)
sys.stdout = log; sys.stderr = log
print(f"[runner] start {ts} 대상={[d[0] for d in DOCS]}")

rc = 1
try:
    from bankon.config import load_config
    from bankon.ui import driver, navigate
    import run_queue_worker as W
    import autofill_nh, autofill_shinhan, autofill_kb, autofill_hnb

    MODS = {"농협": (autofill_nh, []), "신한": (autofill_shinhan, []),
            "국민": (autofill_kb, ["--no-touch"]), "하나": (autofill_hnb, ["--no-touch"])}

    cfg = load_config(None)
    session = navigate.open_app(cfg.loader_cmd, cfg.bankon_user, cfg.bankon_password)
    print(f"[runner] BANK24 {session.main.title!r} pid={session.pid}")
    rc = 0

    def locate(doc_id, req):
        d0, d1 = W.query_window(req)
        for tab in ("작성", "발송완료", "미접수"):
            navigate.close_forms(session)
            if not navigate.select_tab(session, tab):
                print(f"[runner] {tab} 탭 선택 실패")
                continue
            navigate.query_documents(session, start=d0, end=d1, work_type="담보")
            navigate.close_forms(session)
            if navigate.find_row_by_doc(session, doc_id):
                return tab
            if tab != "미접수":
                print(f"[runner] {tab} 탭 기간({d0}~{d1}) 조회엔 없음 → '찾 기'(전 기간) 재확인")
                navigate.find_document(session, doc_id, settle=6.0)
                if navigate.find_row_by_doc(session, doc_id, max_rows=30):
                    return tab
        return None

    for doc_id, bank, req, queue_result in DOCS:
        print(f"\n================ {bank} {doc_id} (큐: {queue_result}) ================")
        try:
            tab = locate(doc_id, req)
            if tab is None:
                print(f"[runner] ★{doc_id}: 작성·발송완료·미접수 어느 탭에도 없음")
                continue
            row = navigate.focused_row_text(session)[:400].replace("\t", " | ")
            print(f"[runner] 탭={tab} 행: {row}")
            if tab == "미접수":
                print(f"[runner] ★미접수 상태 — 폼 열지 않음(접수 전)")
                continue
            form_ref = navigate.open_write_form(session, home=False)
            print(f"[runner] 폼: {form_ref.class_name} — {form_ref.title}")
            mod, extra = MODS[bank]
            if form_ref.class_name != mod.FORM_CLASS:
                raise navigate.NavigationError(f"{bank} 폼이 아님: {form_ref.class_name}")
            try:
                r = mod.main([doc_id] + extra)      # 드라이런(--live 없음)
            except SystemExit as stop:
                print(f"[runner] autofill 중단: {stop}")
                r = 1
            print(f"[runner] autofill_{bank} exit = {r}")
            try:
                w = driver.window(form_ref.handle); w.set_focus(); time.sleep(0.5)
                snap = ROOT / "reports" / f"cmp_6docs_{ts}_{doc_id}.png"
                w.capture_as_image().save(str(snap))
                print(f"[runner] 스냅샷: {snap.name}")
            except Exception as error:  # noqa: BLE001
                print(f"[runner] 스냅샷 실패: {error!r}")
        except Exception as error:  # noqa: BLE001
            traceback.print_exc()
            print(f"[runner] {doc_id} 실패: {error!r}")
            rc = 1
        finally:
            try:
                navigate.close_context_menu()
                navigate.close_forms(session)
                print(f"[runner] 폼 닫기(저장 없음). 남은 폼={len(navigate.open_forms(session))}")
            except Exception as error:  # noqa: BLE001
                print(f"[runner] close 실패 {error!r}")
except Exception as error:  # noqa: BLE001
    traceback.print_exc()
    print(f"[runner] exception: {error!r}")
finally:
    print(f"[runner] end rc={rc}")
    log.close()
sys.exit(rc)
