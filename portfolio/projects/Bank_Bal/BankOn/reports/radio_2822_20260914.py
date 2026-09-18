"""2822 국민 — 평가방법 라디오가 물건마다 눌리는지 실폼 검증(autofill_kb 드라이런, **저장 없음**). 관리자 python."""
import sys, time, traceback, pathlib, os, datetime as dt
ROOT = pathlib.Path(r"D:\AI\Claude\Bank_Bal\BankOn")
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "tools")); os.chdir(ROOT)
DOC, REQ = "01-2609-3-2822", dt.date(2026, 9, 9)
ts = time.strftime("%Y%m%d_%H%M%S")
log = open(ROOT / "reports" / f"radio_2822_{ts}.log", "w", encoding="utf-8", errors="replace", buffering=1)
sys.stdout = log; sys.stderr = log
rc = 1
try:
    from bankon.config import load_config
    from bankon.ui import driver, navigate
    import run_queue_worker as W
    import autofill_kb
    cfg = load_config(None)
    session = navigate.open_app(cfg.loader_cmd, cfg.bankon_user, cfg.bankon_password)
    print(f"[runner] BANK24 {session.main.title!r}")
    d0, d1 = W.query_window(REQ)
    found = None
    for tab in ("작성", "발송완료"):
        navigate.close_forms(session)
        if not navigate.select_tab(session, tab):
            print(f"[runner] {tab} 탭 선택 실패"); continue
        navigate.query_documents(session, start=d0, end=d1, work_type="담보")
        navigate.close_forms(session)
        if navigate.find_row_by_doc(session, DOC):
            found = tab; break
        navigate.find_document(session, DOC, settle=6.0)
        if navigate.find_row_by_doc(session, DOC, max_rows=30):
            found = tab; break
    if found is None:
        raise navigate.NavigationError("작성·발송완료 탭에 2822 없음")
    print(f"[runner] 탭={found} 행: {navigate.focused_row_text(session)[:200]!r}")
    form = navigate.open_write_form(session, home=False)
    print(f"[runner] 폼: {form.class_name} — {form.title}")
    n = navigate.kb_count_object_rows(form); print(f"[runner] 물건 {n}개")
    w = driver.window(form.handle)
    def snap(tag):
        w.set_focus(); time.sleep(0.4); w.capture_as_image().save(str(ROOT / "reports" / f"radio_2822_{ts}_{tag}.png"))
    navigate.kb_select_object_row(form, 1); snap("before_obj2")
    r = autofill_kb.main([DOC])          # 드라이런(라디오·행 추가는 건드림, 저장 없음)
    print(f"[runner] autofill_kb dry exit={r}")
    for i in range(min(n, 3)):
        navigate.kb_select_object_row(form, i); snap(f"after_obj{i+1}")
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
