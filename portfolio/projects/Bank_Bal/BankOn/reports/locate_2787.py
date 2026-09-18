"""01-2609-3-2787(하나) 이 Bank24 어느 탭·어느 조건에 있는지 찾는다 — **읽기 전용**(입력·저장·발송·우클릭 메뉴 없음).

큐 워커가 '행을 목록에서 찾지 못했습니다'로 실패한 원인을 가린다. 탭(작성·발송완료)과 업무구분(담보·탁상)을
바꿔 가며 목록만 훑고, 마지막으로 감정서번호 '찾 기'(전 기간)로 직접 조회한다.
그리드는 Ctrl+C 로 행 텍스트만 읽고 가속키는 안 보낸다(빈 그리드에 키를 보내면 다른 앱으로 샌다 — 09-08 교훈).
"""
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(r"D:\AI\Claude\Bank_Bal\BankOn")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
os.chdir(ROOT)

DOC = "01-2609-3-2787"
FROM, TO = "2026-08-20", "2026-09-20"
MAX_ROWS = 300

ts = time.strftime("%Y%m%d_%H%M%S")
log = open(ROOT / "reports" / f"locate_2787_{ts}.log", "w", encoding="utf-8", errors="replace", buffering=1)
sys.stdout = sys.stderr = log
import ctypes
try:
    _admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
except Exception:  # noqa: BLE001
    _admin = False
print(f"[locate] start {ts} 대상={DOC} 기간={FROM}~{TO} 관리자권한={_admin}")
if not _admin:
    print("[locate] ⛔ 관리자 권한이 아니다 — Bank24(elevated)에 입력이 막힌다(UIPI). 승격해서 다시 실행할 것.")

rc = 1
session = None
try:
    from bankon.config import load_config
    from bankon.ui import driver, navigate

    cfg = load_config(None)
    session = navigate.open_app(cfg.loader_cmd, cfg.bankon_user, cfg.bankon_password)

    def scan(tab: str, work: str) -> None:
        ok_tab = navigate.select_tab(session, tab)
        navigate.query_documents(session, start=FROM, end=TO, work_type=work)
        rows = navigate.list_rows(session, max_rows=MAX_ROWS)
        hit = [r for r in rows if DOC in r]
        print(f"\n=== 탭 {tab}(선택={ok_tab}) · 업무구분 {work} — 행 {len(rows)}개 · 대상 {len(hit)}건")
        for h in hit:
            print("   ★", h.replace("\t", " | ")[:400])
        if not hit:
            for r in rows[:2]:
                print("   (표본)", r.replace("\t", " | ")[:220])

    for tab, work in (("작성", "담보"), ("작성", "탁상"), ("발송완료", "담보")):
        try:
            scan(tab, work)
        except Exception as error:  # noqa: BLE001
            print(f"\n=== 탭 {tab} · {work} — 실패 {error!r}")

    for tab in ("작성", "발송완료"):
        try:
            print(f"\n=== '찾 기'(전 기간) · 탭 {tab}")
            navigate.select_tab(session, tab)
            navigate.find_document(session, DOC, settle=6.0)
            rows = navigate.list_rows(session, max_rows=30)
            print(f"   행 {len(rows)}개")
            for r in rows[:5]:
                print("   ", r.replace("\t", " | ")[:400])
        except Exception as error:  # noqa: BLE001
            print(f"   실패 {error!r}")
    rc = 0
except Exception as error:  # noqa: BLE001
    traceback.print_exc()
    print(f"[locate] 실패 {error!r}")
finally:
    try:
        navigate.close_context_menu()
        if session:
            navigate.close_forms(session)
    except Exception:  # noqa: BLE001
        pass
    print(f"[locate] exit={rc}")
    log.close()
sys.exit(rc)
