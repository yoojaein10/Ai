"""하나 폼(2871) 물건 그리드 정찰 — **읽기전용**. 행 이동이 왜 안 먹는지 본다.

① 폼 안 TcxGridSite 를 전부 나열(좌표·크기) ② 그리드마다 포커스 → Ctrl+Home → ↓ 를 눌러가며
화면 일련번호·감정평가액이 어떻게 바뀌는지 기록 ③ 각 단계 스크린샷.
입력·저장·행추가 없음(닫기는 '아니오'). 관리자 python.
"""
import sys, time, traceback, pathlib, os, datetime as dt

ROOT = pathlib.Path(r"D:\AI\Claude\Bank_Bal\BankOn")
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "tools")); os.chdir(ROOT)
DOC, REQ = "01-2609-3-2871", dt.date(2026, 9, 11)
ts = time.strftime("%Y%m%d_%H%M%S")
log = open(ROOT / "reports" / f"probe_hnb_{ts}.log", "w", encoding="utf-8", errors="replace", buffering=1)
sys.stdout = log; sys.stderr = log
rc = 1
session = None
try:
    from bankon.config import load_config
    from bankon.ui import driver, navigate
    from pywinauto.keyboard import send_keys
    import run_queue_worker as W
    import verify_form as vf
    import autofill_slot as A

    cfg = load_config(None)
    session = navigate.open_app(cfg.loader_cmd, cfg.bankon_user, cfg.bankon_password)
    print(f"[probe] BANK24 {session.main.title!r}")
    d0, d1 = W.query_window(REQ)
    found = None
    for tab in ("발송완료", "작성"):
        navigate.close_forms(session)
        if not navigate.select_tab(session, tab):
            continue
        navigate.query_documents(session, start=d0, end=d1, work_type="담보")
        navigate.close_forms(session)
        if navigate.find_row_by_doc(session, DOC):
            found = tab; break
        navigate.find_document(session, DOC, settle=6.0)
        if navigate.find_row_by_doc(session, DOC, max_rows=30):
            found = tab; break
    if found is None:
        raise navigate.NavigationError("2871 없음")
    print(f"[probe] 탭={found}")

    form = navigate.open_write_form(session, home=False)
    print(f"[probe] 폼: {form.class_name} — {form.title}")
    window = driver.window(form.handle)

    def slot():
        values = vf.screen_values(form)
        return (A._screen_slot(values), (values.get("감정평가액") or "").strip(),
                (values.get("물건종류") or "").strip(), (values.get("사정면적") or "").strip())

    grids = driver.by_class(form.handle, "TcxGridSite")
    print(f"\n[probe] TcxGridSite {len(grids)}개")
    for i, g in enumerate(grids):
        r = g.rectangle()
        print(f"   [{i}] L={r.left} T={r.top} W={r.right - r.left} H={r.bottom - r.top} "
              f"text={(g.window_text() or '')[:40]!r}")

    for i, g in enumerate(grids):
        print(f"\n===== 그리드 [{i}] 에서 ↓ 이동 =====")
        try:
            g.set_focus()
        except Exception as error:                      # noqa: BLE001
            print(f"   set_focus 실패: {error!r}"); continue
        time.sleep(0.4)
        send_keys("^{HOME}"); time.sleep(0.5)
        print(f"   Ctrl+Home → {slot()}")
        for step in range(1, 7):
            send_keys("{DOWN}"); time.sleep(0.45)
            print(f"   ↓×{step}      → {slot()}")
        send_keys("^{END}"); time.sleep(0.6)
        print(f"   Ctrl+End  → {slot()}")
        window.set_focus(); time.sleep(0.3)
        window.capture_as_image().save(str(ROOT / "reports" / f"probe_hnb_{ts}_grid{i}.png"))

    # 물건 그리드 팝업(행 추가 메뉴)이 어떤 항목인지 — 열기만 하고 ESC 로 닫는다(추가 안 함).
    print("\n===== 물건 그리드 팝업 열어보기(추가 안 함) =====")
    try:
        target = navigate._object_grid(form)
        target.set_focus(); time.sleep(0.4)
        before = navigate._menu_handles()
        send_keys("+{F10}"); time.sleep(1.2)
        opened = navigate._menu_handles() - before
        print(f"   팝업 핸들: {sorted(opened)}")
        window.set_focus(); time.sleep(0.3)
        window.capture_as_image().save(str(ROOT / "reports" / f"probe_hnb_{ts}_menu.png"))
        navigate.close_context_menu()
    except Exception as error:                          # noqa: BLE001
        print(f"   팝업 확인 실패: {error!r}")
    rc = 0
except Exception as error:                              # noqa: BLE001
    traceback.print_exc(); print(f"[probe] exception: {error!r}")
finally:
    try:
        if session:
            navigate.close_context_menu()
            navigate.close_forms(session)
            print(f"[probe] 폼 닫기(저장 없음). 남은 폼={len(navigate.open_forms(session))}")
    except Exception as error:                          # noqa: BLE001
        print(f"[probe] close 실패 {error!r}")
    print(f"[probe] end rc={rc}"); log.close()
sys.exit(rc)
