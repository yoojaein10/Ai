"""농협 발송완료 탭 화면값 대조 — **읽기 전용**(입력·저장·발송 없음). 관리자 권한 python 필요(UIPI).
run_cmp_sent_20260907.py 의 농협판(2026-09-07, 이식 직후 첫 실화면 대조).
    발송완료 탭 기간 조회(담보) → 감정서번호마다 행 찾기(행 순회) → 작성(A) 폼 열기 → autofill_nh 드라이런
    ("화면값 vs 우리 매핑값" 표) → 스냅샷 → '닫 기'(저장 없음).
출력: reports/cmp_nh_<ts>.log / _<doc>.png
"""
import sys, time, traceback, pathlib, os
ROOT = pathlib.Path(r"D:\AI\Claude\Bank_Bal\BankOn")
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "tools"))
os.chdir(ROOT)

DATE_FROM, DATE_TO = "2026-08-10", "2026-09-07"
TAB = "발송완료"
DOCS = ["01-2608-3-2728", "01-2608-3-2686", "01-2608-3-2616", "01-2608-3-2625", "01-2608-3-2645"]

ts = time.strftime("%Y%m%d_%H%M%S")
log = open(ROOT / "reports" / f"cmp_nh_{ts}.log", "w", encoding="utf-8", errors="replace", buffering=1)
sys.stdout = log; sys.stderr = log
print(f"[runner] start {ts} 탭={TAB} 기간={DATE_FROM}~{DATE_TO} 대상={DOCS}")

rc = 1
try:
    from bankon.config import load_config
    from bankon.ui import driver, navigate
    import autofill_nh

    cfg = load_config(None)
    session = navigate.open_app(cfg.loader_cmd, cfg.bankon_user, cfg.bankon_password)
    if not navigate.select_tab(session, TAB):
        raise navigate.NavigationError(f"{TAB} 탭 선택 실패")

    def requery():
        navigate.query_documents(session, start=DATE_FROM, end=DATE_TO, work_type="담보")
        navigate.close_forms(session)

    requery()
    rc = 0
    for doc_id in DOCS:
        print(f"\n================ 농협 {doc_id} ================")
        try:
            navigate.close_forms(session)
            found = False
            for attempt in range(3):
                if navigate.find_row_by_doc(session, doc_id):
                    found = True
                    break
                print(f"[runner] {doc_id} 행 못 찾음 — 재조회 {attempt + 1}/3")
                requery()
            if not found:
                raise navigate.NavigationError(f"{doc_id} 행 탐색 실패(기간·탭 확인)")
            print("[runner] 행:", navigate.focused_row_text(session)[:300].replace("\t", " | "))
            form_ref = navigate.open_write_form(session, home=False)
            print(f"[runner] 폼: {form_ref.class_name} — {form_ref.title}")
            if form_ref.class_name != autofill_nh.FORM_CLASS:
                raise navigate.NavigationError(f"농협 폼이 아님: {form_ref.class_name}")
            try:
                r = autofill_nh.main([doc_id])      # 드라이런(--live 없음)
            except SystemExit as stop:
                print(f"[runner] autofill 중단: {stop}")
                r = 1
            print(f"[runner] autofill_nh exit = {r}")
            rc = rc or r
            try:
                w = driver.window(form_ref.handle); w.set_focus(); time.sleep(0.5)
                snap = ROOT / "reports" / f"cmp_nh_{ts}_{doc_id}.png"
                w.capture_as_image().save(str(snap))
                print(f"[runner] 스냅샷: {snap.name}")
            except Exception as error:  # noqa: BLE001
                print(f"[runner] 스냅샷 실패: {error!r}")
        except Exception as error:  # noqa: BLE001
            traceback.print_exc()
            print(f"[runner] {doc_id} 실패: {error!r}")
            rc = 1
        finally:
            navigate.close_context_menu()
            navigate.close_forms(session)
            print(f"[runner] 폼 닫기(저장 없음). 남은 폼={len(navigate.open_forms(session))}")
except Exception as error:  # noqa: BLE001
    traceback.print_exc()
    print(f"[runner] exception: {error!r}")
finally:
    print(f"[runner] end rc={rc}")
    log.close()
sys.exit(rc)
