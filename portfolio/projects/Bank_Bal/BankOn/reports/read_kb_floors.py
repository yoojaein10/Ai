"""국민 담보폼 '총층수/층수' 두 칸을 실물에서 읽는다 — **읽기 전용**(입력·저장 없음).

1.png(2804 화면) 에서 '총층수/층수' 라벨 오른쪽에 칸이 **둘**인 것을 확인했다(왼쪽 7=총층수, 오른쪽 1=층수).
우리는 왼쪽만 채우고 오른쪽을 비워 뒀다(담당자 제보 '구분건물 층수 누락'). 규칙을 확정하려고
발송완료(담당자 완성본) 건들의 두 칸 값을 물건마다 읽는다.
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

# (문서, 탭) — 2804 는 작성 탭(담당자가 방금 채움), 나머지는 발송완료(완성본)
TARGETS = [
    ("01-2609-3-2804", "작성", "2026-09-04", "2026-09-12"),
    ("01-2609-3-2788", "발송완료", "2026-09-01", "2026-09-12"),
    ("01-2608-3-2742", "발송완료", "2026-08-25", "2026-09-05"),
    ("01-2608-3-2715", "발송완료", "2026-08-20", "2026-09-05"),
]
LABELS = ["물건:건물 층수", "물건:호", "물건:총층수/층수", "물건:총층수/층수@2", "물건:총세대수", "물건:물건종류"]

ts = time.strftime("%Y%m%d_%H%M%S")
log = open(ROOT / "reports" / f"kb_floors_{ts}.log", "w", encoding="utf-8", errors="replace", buffering=1)
sys.stdout = sys.stderr = log
import ctypes
try:
    admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
except Exception:  # noqa: BLE001
    admin = False
print(f"[read] start {ts} 관리자권한={admin} 대상={[t[0] for t in TARGETS]}")

rc = 1
try:
    from bankon.config import load_config
    from bankon.mapping import kookmin
    from bankon.ui import driver, form, navigate

    form.use_layout(kookmin.POSITIONAL, kookmin.REGIONS)
    cfg = load_config(None)
    session = navigate.open_app(cfg.loader_cmd, cfg.bankon_user, cfg.bankon_password)

    for doc, tab, d_from, d_to in TARGETS:
        print(f"\n================ {doc} · 탭 {tab} ================")
        try:
            navigate.close_forms(session)
            if not navigate.select_tab(session, tab):
                print("  탭 선택 실패 → 건너뜀")
                continue

            def requery():
                navigate.query_documents(session, start=d_from, end=d_to, work_type="담보")
                navigate.close_forms(session)

            requery()
            if not navigate.find_row_by_doc(session, doc):
                requery()
                if not navigate.find_row_by_doc(session, doc):
                    print("  행 못 찾음 → 건너뜀")
                    continue
            form_ref = navigate.open_write_form(session, home=False)
            print(f"  폼: {form_ref.class_name}")
            if form_ref.class_name != "TBNKKBB24DAMB":
                print("  국민 폼 아님 → 건너뜀")
                continue
            n = navigate.kb_count_object_rows(form_ref)
            print(f"  물건 {n}개")
            for oi in range(n):
                navigate.kb_select_object_row(form_ref, oi)
                vals = {}
                for label in LABELS:
                    action, current, _ = form.plan_field(form_ref, label, "?")
                    vals[label] = "(미발견)" if action == "미발견" else current
                print(f"   물건 {oi + 1}: " + " · ".join(f"{k.replace('물건:', '')}={v!r}" for k, v in vals.items()))
        except Exception as error:  # noqa: BLE001
            traceback.print_exc()
            print(f"  실패 {error!r}")
        finally:
            navigate.close_context_menu()
            navigate.close_forms(session)
    rc = 0
except Exception as error:  # noqa: BLE001
    traceback.print_exc()
    print(f"[read] 실패 {error!r}")
finally:
    print(f"[read] exit={rc}")
    log.close()
sys.exit(rc)
