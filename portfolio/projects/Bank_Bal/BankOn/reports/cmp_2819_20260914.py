"""2819 신한 — 담당자 완성본 실화면 **읽기 전용** 대조 + 행별 전 칸 덤프(입력·저장·발송 없음). 관리자 python."""
import sys, time, traceback, pathlib, os, datetime as dt
ROOT = pathlib.Path(r"D:\AI\Claude\Bank_Bal\BankOn")
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "tools"))
os.chdir(ROOT)
DOC, REQ = "01-2609-3-2819", dt.date(2026, 9, 8)
ts = time.strftime("%Y%m%d_%H%M%S")
log = open(ROOT / "reports" / f"cmp_2819_{ts}.log", "w", encoding="utf-8", errors="replace", buffering=1)
sys.stdout = log; sys.stderr = log
rc = 1
try:
    from bankon.config import load_config
    from bankon.ui import driver, navigate
    from bankon import cli
    import run_queue_worker as W
    import autofill_shinhan
    cfg = load_config(None)
    session = navigate.open_app(cfg.loader_cmd, cfg.bankon_user, cfg.bankon_password)
    print(f"[runner] BANK24 {session.main.title!r}")
    d0, d1 = W.query_window(REQ)
    tab_found = None
    for tab in ("작성", "발송완료"):
        navigate.close_forms(session)
        if not navigate.select_tab(session, tab):
            print(f"[runner] {tab} 탭 선택 실패"); continue
        navigate.query_documents(session, start=d0, end=d1, work_type="담보")
        navigate.close_forms(session)
        if navigate.find_row_by_doc(session, DOC):
            tab_found = tab; break
        navigate.find_document(session, DOC, settle=6.0)
        if navigate.find_row_by_doc(session, DOC, max_rows=30):
            tab_found = tab; break
    if tab_found is None:
        raise navigate.NavigationError("작성·발송완료 탭에 없음")
    print("[runner] 탭=", tab_found, "행:", navigate.focused_row_text(session)[:300].replace("\t", " | "))
    form = navigate.open_write_form(session, home=False)
    print(f"[runner] 폼: {form.class_name} — {form.title}")
    print("\n======== A) 드라이런 대조(우리 매핑값 vs 화면) ========")
    try:
        r = autofill_shinhan.main([DOC, "--all-objects"])
    except SystemExit as stop:
        r = stop.code
    print(f"[runner] autofill dry exit={r}")
    print("\n======== B) 행별 전 칸 덤프 ========")
    n = navigate.count_object_rows(form)
    for i in range(n):
        navigate.select_object_row(form, i); time.sleep(0.4)
        print(f"\n----- 행 {i+1}/{n} -----")
        cli._dump(form)
        w = driver.window(form.handle); w.set_focus(); time.sleep(0.3)
        w.capture_as_image().save(str(ROOT / "reports" / f"cmp_2819_{ts}_row{i+1}.png"))
    rc = 0
except Exception as e:  # noqa: BLE001
    traceback.print_exc(); print(f"[runner] exception: {e!r}")
finally:
    try:
        navigate.close_context_menu(); navigate.close_forms(session)
        print(f"[runner] 폼 닫기(저장 없음). 남은 폼={len(navigate.open_forms(session))}")
    except Exception as e:  # noqa: BLE001
        print(f"[runner] close 실패 {e!r}")
    print(f"[runner] end rc={rc}"); log.close()
sys.exit(rc)
