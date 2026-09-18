# human_guard 실폼 검증(읽기 전용, 저장 없음) — 관리자 권한으로 띄움. 결과: reports/guard_check2.out
#   2780 기업: 오늘 우리가 작성(작성 탭, 미발송) → 사람 작성으로 '제외'돼야 함
#   2776 기업: 09-07 작성·(사람이) 발송 → 작성 탭에 없고 발송완료 탭에 있어 '이미 발송완료' 제외돼야 함
#   2805 농협(오늘 접수, 미작성) → 새 폼 → 통과해야 함
import sys, pathlib, traceback, time
ROOT = pathlib.Path(r"D:\AI\Claude\Bank_Bal\BankOn")
sys.path.insert(0, str(ROOT / "tools")); sys.path.insert(0, str(ROOT / "src"))
out = open(ROOT / "reports" / "guard_check2.out", "w", encoding="utf-8", errors="replace", buffering=1)
sys.stdout = out; sys.stderr = out
from bankon.config import load_config
from bankon.ui import navigate
import human_guard as G
import run_queue_worker as W
import datetime as dt

CASES = [  # (doc, bank, APW RequestDate, 기대)
    ("01-2608-3-2717", "신한", dt.date(2026, 8, 26), "제외(사람 작성) — 오늘 15:47 작성, 미발송이면 작성 탭에 값 있음"),
    ("01-2609-3-2784", "기업", dt.date(2026, 9, 4), "제외(사람 작성) — 배포 PC 워커가 14:29 작성, 미발송이면"),
]
try:
    cfg = load_config(None)
    session = navigate.open_app(cfg.loader_cmd, cfg.bankon_user, cfg.bankon_password)
    print(f"[check] BANK24 {session.main.title!r} pid={session.pid}")
    for doc, bank, req, expect in CASES:
        print(f"\n===== {doc} [{bank}] 기대: {expect} =====")
        d0, d1 = W.query_window(req)
        try:
            navigate.close_forms(session)
            navigate.select_tab(session, "작성")
            def requery(d0=d0, d1=d1):
                navigate.query_documents(session, start=d0, end=d1, work_type="담보")
                navigate.close_forms(session)
            requery()
            how = G.ensure_row_or_sent(session, doc, requery=requery, date_from=d0, date_to=d1)
            print(f"[check] 행 위치: {how}")
            form = navigate.open_write_form(session, home=False)
            print(f"[check] 폼: {form.class_name} — {form.title}")
            G.assert_not_written(form, bank, {})
            print("[check] 결과: 새 폼 통과")
        except G.Excluded as ex:
            print(f"[check] 결과: 제외 — {ex}")
        except Exception as e:  # noqa: BLE001
            print(f"[check] 결과: 오류 {e!r}")
            traceback.print_exc()
        finally:
            try:
                navigate.close_context_menu()
                navigate.close_forms(session)
            except Exception as e:  # noqa: BLE001
                print(f"[check] close 실패 {e!r}")
    print("\n[check] done")
except Exception:
    traceback.print_exc()
finally:
    out.close()
