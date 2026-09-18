"""2819 신한 — 담당자 완성본의 2~6행 우편번호 보정(1행 값 복사) + 행 복사 추가(X) 실검증. 관리자 python.
흐름: ① 작성 탭에서 2819 열기 → 행 수 6 확인 → X(마지막위치 복사)로 7행 추가 → 7행 우편번호 읽기(복사 여부) → 저장 없이 닫기
      ② 다시 열기 → 행 수 6 아니면 중단(fail-closed) → 1행 우편번호 읽기 → 2~6행 빈칸이면 채움 → '저 장' → 닫기
      ③ 다시 열어 2~6행 우편번호 재확인 → 닫기. 우편번호 외 어떤 칸도 건드리지 않는다.
"""
import sys, time, traceback, pathlib, os, datetime as dt
ROOT = pathlib.Path(r"D:\AI\Claude\Bank_Bal\BankOn")
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "tools")); os.chdir(ROOT)
DOC, REQ = "01-2609-3-2819", dt.date(2026, 9, 8)
ts = time.strftime("%Y%m%d_%H%M%S")
log = open(ROOT / "reports" / f"xcopy_2819_{ts}.log", "w", encoding="utf-8", errors="replace", buffering=1)
sys.stdout = log; sys.stderr = log
rc = 1
try:
    from bankon.config import load_config
    from bankon.ui import driver, navigate, form as F
    import run_queue_worker as W
    cfg = load_config(None)
    session = navigate.open_app(cfg.loader_cmd, cfg.bankon_user, cfg.bankon_password)
    print(f"[runner] BANK24 {session.main.title!r}")
    d0, d1 = W.query_window(REQ)

    def open_doc():
        navigate.close_forms(session)
        if not navigate.select_tab(session, "작성"):
            raise navigate.NavigationError("작성 탭 선택 실패")
        navigate.query_documents(session, start=d0, end=d1, work_type="담보")
        navigate.close_forms(session)
        if not navigate.find_row_by_doc(session, DOC):
            raise navigate.NavigationError("작성 탭에 2819 없음(발송됐을 수 있음) — 중단")
        f = navigate.open_write_form(session, home=False)
        if f.class_name != "TBNKSHG24DAMB":
            raise navigate.NavigationError(f"신한 폼 아님 {f.class_name}")
        return f

    def zip_of(f, idx):
        navigate.select_object_row(f, idx); time.sleep(0.4)
        _, cur, _ = F.plan_field(f, "우편번호", "?")
        return (cur or "").strip()

    # ① 복사 추가(X) 실검증 — 저장 없음
    print("\n== ① X(마지막위치 복사) 검증 ==")
    f = open_doc()
    n = navigate.count_object_rows(f); print(f"행 수 {n}")
    zips = [zip_of(f, i) for i in range(n)]; print(f"현재 우편번호: {zips}")
    n2 = navigate.add_object_row(f, "copy_append"); print(f"X 추가 후 행 수 {n2}")
    print(f"추가된 {n2}행 우편번호={zip_of(f, n2 - 1)!r} (1행={zips[0]!r})")
    navigate.close_context_menu(); navigate.close_forms(session)
    print(f"저장 없이 닫음. 남은 폼={len(navigate.open_forms(session))}")

    rc = 0
except Exception as e:  # noqa: BLE001
    traceback.print_exc(); print(f"[runner] exception: {e!r}")
    try:
        navigate.close_context_menu(); navigate.close_forms(session)
    except Exception: pass
finally:
    print(f"[runner] end rc={rc}"); log.close()
sys.exit(rc)
