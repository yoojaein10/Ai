"""01-2609-3-2804(국민 구분건물) 작성 탭 화면 대조 — **읽기 전용**(입력·저장·발송 없음, --no-touch).

담당자가 '구분건물 층수 누락'이라며 손으로 채워 둔 상태다. 우리가 낸 값과 화면값을 나란히 놓아
어느 칸이 비었는지·라벨을 못 짚은 것인지 가린다. run_cmp_sent_20260907.py 의 1건판(2026-09-10).
출력: reports/cmp_2804_<ts>.log / .png
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

DOC = "01-2609-3-2804"
DATE_FROM, DATE_TO = "2026-09-04", "2026-09-12"
TAB = "작성"

ts = time.strftime("%Y%m%d_%H%M%S")
log = open(ROOT / "reports" / f"cmp_2804_{ts}.log", "w", encoding="utf-8", errors="replace", buffering=1)
sys.stdout = sys.stderr = log
import ctypes
try:
    admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
except Exception:  # noqa: BLE001
    admin = False
print(f"[cmp] start {ts} 대상={DOC} 탭={TAB} 기간={DATE_FROM}~{DATE_TO} 관리자권한={admin}")

rc = 1
try:
    from bankon.config import load_config
    from bankon.ui import driver, navigate
    import autofill_kb

    cfg = load_config(None)
    session = navigate.open_app(cfg.loader_cmd, cfg.bankon_user, cfg.bankon_password)
    if not navigate.select_tab(session, TAB):
        raise navigate.NavigationError(f"{TAB} 탭 선택 실패")

    def requery():
        navigate.query_documents(session, start=DATE_FROM, end=DATE_TO, work_type="담보")
        navigate.close_forms(session)

    requery()
    found = False
    for attempt in range(3):
        if navigate.find_row_by_doc(session, DOC):
            found = True
            break
        print(f"[cmp] 행 못 찾음 — 재조회 {attempt + 1}/3")
        requery()
    if not found:
        raise navigate.NavigationError(f"{DOC} 행 탐색 실패(기간·탭 확인)")
    print("[cmp] 행:", navigate.focused_row_text(session)[:300].replace("\t", " | "))

    form_ref = navigate.open_write_form(session, home=False)
    print(f"[cmp] 폼: {form_ref.class_name} — {form_ref.title}")
    if form_ref.class_name != autofill_kb.FORM_CLASS:
        raise navigate.NavigationError(f"국민 폼이 아님: {form_ref.class_name}")

    print("\n########## ① 화면 덤프(물건·세부 행 전부) ##########")
    try:
        autofill_kb.main([DOC, "--dump"])
    except SystemExit as stop:
        print(f"[cmp] dump 중단: {stop}")

    print("\n########## ② 채울값 ↔ 화면 대조(드라이런) ##########")
    try:
        r = autofill_kb.main([DOC, "--no-touch"])
    except SystemExit as stop:
        print(f"[cmp] autofill 중단: {stop}")
        r = 1
    print(f"[cmp] autofill_kb exit = {r}")

    try:
        w = driver.window(form_ref.handle)
        w.set_focus()
        time.sleep(0.5)
        snap = ROOT / "reports" / f"cmp_2804_{ts}.png"
        w.capture_as_image().save(str(snap))
        print(f"[cmp] 스냅샷: {snap.name}")
    except Exception as error:  # noqa: BLE001
        print(f"[cmp] 스냅샷 실패: {error!r}")
    rc = 0
except Exception as error:  # noqa: BLE001
    traceback.print_exc()
    print(f"[cmp] 실패 {error!r}")
finally:
    try:
        navigate.close_context_menu()
        print(f"[cmp] 폼 닫기(저장 없음): {navigate.close_forms(session)}")
    except Exception as error:  # noqa: BLE001
        print(f"[cmp] 정리 실패 {error!r}")
    print(f"[cmp] exit={rc}")
    log.close()
sys.exit(rc)
