"""2871 하나 — 담당자 완성본 **읽기전용** 덤프. 평가외(옥탑) 행에 뭘 넣었는지 보려는 것.

물건 행마다 화면값을 그대로 찍고 스크린샷을 남긴다. 입력·저장 없음(닫기는 '아니오').
덤으로 autofill_slot 의 새 행 이동(_count_rows·_select_row)이 하나 폼에서 먹는지 실측한다.
관리자 python 으로 띄울 것.
"""
import sys, time, traceback, pathlib, os, datetime as dt

ROOT = pathlib.Path(r"D:\AI\Claude\Bank_Bal\BankOn")
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "tools")); os.chdir(ROOT)
DOC, REQ = "01-2609-3-2871", dt.date(2026, 9, 11)
ts = time.strftime("%Y%m%d_%H%M%S")
log = open(ROOT / "reports" / f"dump_2871_{ts}.log", "w", encoding="utf-8", errors="replace", buffering=1)
sys.stdout = log; sys.stderr = log
rc = 1
session = None
try:
    from bankon.config import load_config
    from bankon.ui import driver, navigate
    import run_queue_worker as W
    import verify_form as vf
    import autofill_slot as A

    cfg = load_config(None)
    session = navigate.open_app(cfg.loader_cmd, cfg.bankon_user, cfg.bankon_password)
    print(f"[dump] BANK24 {session.main.title!r}")
    d0, d1 = W.query_window(REQ)
    found = None
    for tab in ("발송완료", "작성"):
        navigate.close_forms(session)
        if not navigate.select_tab(session, tab):
            print(f"[dump] {tab} 탭 선택 실패"); continue
        navigate.query_documents(session, start=d0, end=d1, work_type="담보")
        navigate.close_forms(session)
        if navigate.find_row_by_doc(session, DOC):
            found = tab; break
        navigate.find_document(session, DOC, settle=6.0)
        if navigate.find_row_by_doc(session, DOC, max_rows=30):
            found = tab; break
    if found is None:
        raise navigate.NavigationError("발송완료·작성 탭에 2871 없음")
    print(f"[dump] 탭={found}")

    form = navigate.open_write_form(session, home=False)
    print(f"[dump] 폼: {form.class_name} — {form.title}")

    rows, grid = A._count_rows(form)
    print(f"[dump] ★_count_rows = {rows} (그리드 left={grid.rectangle().left if grid else None})")
    window = driver.window(form.handle)
    for index in range((rows or 1)):
        try:
            A._select_row(form, grid, index)
            ok = "OK"
        except Exception as error:                      # noqa: BLE001
            ok = f"실패({error})"
        values = vf.screen_values(form)
        print(f"\n===== {index + 1}행 선택 {ok} =====")
        for label in sorted(values):
            text = str(values[label] or "").strip()
            if text:
                print(f"    {label:20} = {text}")
        window.set_focus(); time.sleep(0.4)
        window.capture_as_image().save(str(ROOT / "reports" / f"dump_2871_{ts}_row{index + 1}.png"))
    rc = 0
except Exception as error:                              # noqa: BLE001
    traceback.print_exc(); print(f"[dump] exception: {error!r}")
finally:
    try:
        if session:
            navigate.close_context_menu()
            navigate.close_forms(session)
            print(f"[dump] 폼 닫기(저장 없음). 남은 폼={len(navigate.open_forms(session))}")
    except Exception as error:                          # noqa: BLE001
        print(f"[dump] close 실패 {error!r}")
    print(f"[dump] end rc={rc}"); log.close()
sys.exit(rc)
