"""기업은행 작성(A) 폼 콤보 선택지 수집 — 읽기 전용(저장·발송 없음). 관리자 권한 python(UIPI).

폼을 열어 tools/list_combo_items.py(--probe: F4 로 열고 ↑↓로 훑은 뒤 ESC 복원, 값이 바뀌면 즉시 중단) 를 돌리고
닫기(확인창은 '아니오'). 배경: 2706 LIVE 에서 토지 물건종류 콤보에 '전'·'목장용지' 항목 없음(2026-09-01) → 목록 필요.

    Start-Process python -ArgumentList '"...\tools\recon_ibk_combo.py" <from> <to> <doc> [탭] [--only 물건종류,지목]' -Verb RunAs -WindowStyle Hidden -Wait
출력: recon/combo_ibk_<doc>.md, reports/ibkcombo_<ts>.log
"""
from __future__ import annotations

import io
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
DATE_FROM, DATE_TO, DOC = ARGS[0], ARGS[1], ARGS[2]
TAB = ARGS[3] if len(ARGS) > 3 else "작성"
ONLY = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None

ts = time.strftime("%Y%m%d_%H%M%S")
log = open(ROOT / "reports" / f"ibkcombo_{ts}.log", "w", encoding="utf-8", errors="replace")


class Tee(io.TextIOBase):
    def write(self, s):
        for st in (sys.__stdout__, log):
            st.write(s)
            st.flush()
        return len(s)


sys.stdout = sys.stderr = Tee()

from bankon.config import load_config      # noqa: E402
from bankon.ui import driver, navigate      # noqa: E402
import list_combo_items                     # noqa: E402

rc = 1
session = None
try:
    print(f"[combo] start {ts} 탭={TAB} 기간={DATE_FROM}~{DATE_TO} 대상={DOC} only={ONLY}")
    cfg = load_config(None)
    session = navigate.open_app(cfg.loader_cmd, cfg.bankon_user, cfg.bankon_password)
    if not navigate.select_tab(session, TAB):
        raise navigate.NavigationError(f"{TAB} 탭 선택 실패")

    def requery():
        navigate.query_documents(session, start=DATE_FROM, end=DATE_TO, work_type="담보")
        navigate.close_forms(session)

    requery()
    print("[combo] 행 위치:", navigate.ensure_row(session, DOC, requery=requery))
    form = navigate.open_write_form(session, home=False)
    print(f"[combo] 폼: {form.class_name} — {form.title} handle={form.handle:#x}")
    if not form.class_name.startswith("TBNKKIB"):
        raise navigate.NavigationError(f"기업 폼이 아님: {form.class_name}")
    out = ROOT / "recon" / f"combo_ibk_{DOC}.md"
    argv = ["--handle", str(form.handle), "--probe", "--out", str(out)]
    if ONLY:
        argv += ["--only", ONLY]
    rc = list_combo_items.main(argv) or 0
    print(f"[combo] list_combo_items exit={rc} → {out}")
    w = driver.window(form.handle)
    w.set_focus()
    time.sleep(0.5)
    w.capture_as_image().save(str(ROOT / "reports" / f"ibkcombo_{ts}_{DOC}.png"))
except Exception as error:  # noqa: BLE001
    traceback.print_exc()
    print(f"[combo] 실패: {error!r}")
    rc = 1
finally:
    if session is not None:
        navigate.close_context_menu()
        navigate.close_forms(session)      # 저장 확인창은 '아니오'
        print("[combo] 폼 닫음(저장 없음)")
print(f"[combo] exit={rc}")
sys.exit(rc)
