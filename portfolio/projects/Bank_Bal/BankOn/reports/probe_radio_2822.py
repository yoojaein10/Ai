"""2822 국민 폼(발송완료) — 라디오 컨트롤 캡션 덤프(읽기 전용)."""
import sys, time, traceback, pathlib, os, datetime as dt
ROOT = pathlib.Path(r"D:\AI\Claude\Bank_Bal\BankOn")
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "tools")); os.chdir(ROOT)
DOC, REQ = "01-2609-3-2822", dt.date(2026, 9, 9)
ts = time.strftime("%Y%m%d_%H%M%S")
log = open(ROOT / "reports" / f"probe_radio_{ts}.log", "w", encoding="utf-8", errors="replace", buffering=1)
sys.stdout = log; sys.stderr = log
rc = 1
try:
    from bankon.config import load_config
    from bankon.ui import driver, navigate
    import run_queue_worker as W
    cfg = load_config(None)
    session = navigate.open_app(cfg.loader_cmd, cfg.bankon_user, cfg.bankon_password)
    d0, d1 = W.query_window(REQ)
    navigate.close_forms(session); navigate.select_tab(session, "발송완료")
    navigate.query_documents(session, start=d0, end=d1, work_type="담보"); navigate.close_forms(session)
    if not navigate.find_row_by_doc(session, DOC):
        navigate.find_document(session, DOC, settle=6.0)
        if not navigate.find_row_by_doc(session, DOC, max_rows=30):
            raise navigate.NavigationError("없음")
    form = navigate.open_write_form(session, home=False)
    print(f"[runner] 폼 {form.class_name}")
    for i in (0, 1):
        navigate.kb_select_object_row(form, i)
        print(f"\n== 물건 {i+1} ==")
        for c in driver.descendants(form.handle):
            try:
                cls = c.element_info.class_name or ""
                if "Radio" not in cls and "Check" not in cls:
                    continue
                r = driver._rect(c)
                txt = c.window_text() or ""
                st = ""
                try:
                    st = f" checked={c.is_checked()}" if hasattr(c, "is_checked") else ""
                except Exception as e: st = f" chk_err={type(e).__name__}"
                try:
                    st += f" state={c.get_check_state()}"
                except Exception: pass
                try:
                    st += f" uia_toggle={c.element_info.element.GetCurrentPropertyValue(30086)}"  # ToggleState
                except Exception: pass
                print(f"  @{r.left},{r.top} {cls:28} {txt!r}{st}")
            except Exception as e:
                print("  err", repr(e))
    rc = 0
except Exception as e:  # noqa: BLE001
    traceback.print_exc(); print(f"[runner] exception: {e!r}")
finally:
    try: navigate.close_context_menu(); navigate.close_forms(session)
    except Exception: pass
    print(f"[runner] end rc={rc}"); log.close()
sys.exit(rc)
