"""2672·2820 농협 폼 **전체 칸** 현재값 덤프 — 읽기 전용(입력·저장 없음). 관리자 python 필요."""
import sys, time, traceback, pathlib, os, datetime as dt
ROOT = pathlib.Path(r"D:\AI\Claude\Bank_Bal\BankOn")
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "tools"))
os.chdir(ROOT)
DOCS = [("01-2608-3-2672", dt.date(2026, 8, 24)), ("01-2609-3-2820", dt.date(2026, 9, 8))]
ts = time.strftime("%Y%m%d_%H%M%S")
log = open(ROOT / "reports" / f"dump_2docs_{ts}.log", "w", encoding="utf-8", errors="replace", buffering=1)
sys.stdout = log; sys.stderr = log
rc = 1
try:
    from bankon.config import load_config
    from bankon.ui import driver, navigate
    from bankon import cli
    import run_queue_worker as W
    cfg = load_config(None)
    session = navigate.open_app(cfg.loader_cmd, cfg.bankon_user, cfg.bankon_password)
    print(f"[runner] BANK24 {session.main.title!r}")
    rc = 0
    for doc_id, req in DOCS:
        print(f"\n================ {doc_id} ================")
        try:
            d0, d1 = W.query_window(req)
            navigate.close_forms(session)
            navigate.select_tab(session, "발송완료")
            navigate.query_documents(session, start=d0, end=d1, work_type="담보")
            navigate.close_forms(session)
            if not navigate.find_row_by_doc(session, doc_id):
                navigate.find_document(session, doc_id, settle=6.0)
                if not navigate.find_row_by_doc(session, doc_id, max_rows=30):
                    raise navigate.NavigationError("행 없음")
            print("[runner] 행:", navigate.focused_row_text(session)[:300].replace("\t", " | "))
            form = navigate.open_write_form(session, home=False)
            print(f"[runner] 폼: {form.class_name} — {form.title}")
            cli._dump(form)
            w = driver.window(form.handle); w.set_focus(); time.sleep(0.5)
            snap = ROOT / "reports" / f"dump_2docs_{ts}_{doc_id}.png"
            w.capture_as_image().save(str(snap)); print(f"[runner] 스냅샷: {snap.name}")
        except Exception as e:  # noqa: BLE001
            traceback.print_exc(); print(f"[runner] {doc_id} 실패: {e!r}"); rc = 1
        finally:
            navigate.close_context_menu(); navigate.close_forms(session)
            print(f"[runner] 폼 닫기(저장 없음). 남은 폼={len(navigate.open_forms(session))}")
except Exception as e:  # noqa: BLE001
    traceback.print_exc(); print(f"[runner] exception: {e!r}")
finally:
    print(f"[runner] end rc={rc}"); log.close()
sys.exit(rc)
