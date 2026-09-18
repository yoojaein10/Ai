"""감정서번호 없는 실화면 시험 러너 — 관리자 권한 python으로 실행(UIPI).

읽기 전용: '찾 기' 안 씀, 저장/발송 안 함. 흐름은
  ① 작성 탭 조건 조회 → 행 순회(rows)로 목록 전부 읽기(Ctrl+A 1행 문제 검증)
  ② 첫 행(--row 1) 작성 폼 열기 → 필드 덤프 → 폼 스크린샷 → '닫 기'
출력: reports/noid_test_<ts>.log / .png
실행: Start-Process python -ArgumentList '"...\tools\run_noid_test.py"' -Verb RunAs -Wait
"""
from __future__ import annotations

import io
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "src"))

DATE_FROM = sys.argv[1] if len(sys.argv) > 1 else "2026-08-18"
DATE_TO = sys.argv[2] if len(sys.argv) > 2 else DATE_FROM
ROW = sys.argv[3] if len(sys.argv) > 3 else "1"   # "0" 이면 rows 만

ts = time.strftime("%Y%m%d_%H%M%S")
log_path = ROOT / "reports" / f"noid_test_{ts}.log"
log_path.parent.mkdir(exist_ok=True)


class Tee(io.TextIOBase):
    def __init__(self, *streams):
        self.streams = streams

    def write(self, s):
        for st in self.streams:
            st.write(s)
            st.flush()
        return len(s)


log = open(log_path, "w", encoding="utf-8", errors="replace")
sys.stdout = Tee(log)
sys.stderr = Tee(log)

print(f"[runner] start {ts}, cwd={os.getcwd()}, 기간={DATE_FROM}~{DATE_TO}, row={ROW}")
from bankon import cli  # noqa: E402
from bankon.config import load_config  # noqa: E402
from bankon.ui import driver, navigate  # noqa: E402

rc = 1
try:
    print("[runner] ① rows — 행 순회")
    rc = cli.main(["rows", "--from", DATE_FROM, "--to", DATE_TO, "--work-type", "담보"])
    print(f"[runner] rows exit = {rc}")

    if ROW == "0":
        raise SystemExit(rc)
    print(f"[runner] ② dump --row {ROW} — 작성 폼 열어 읽기")
    rc2 = cli.main(["dump", "--row", ROW, "--from", DATE_FROM, "--to", DATE_TO])
    print(f"[runner] dump exit = {rc2}")
    rc = rc or rc2

    cfg = load_config(None)
    mains = driver.find_windows(driver.MAIN_CLASS, title_any=driver.MAIN_TITLE_HINTS)
    if mains:
        session = navigate.Session(mains[0])
        for form in navigate.open_forms(session):
            try:
                w = driver.window(form.handle)
                w.set_focus()
                time.sleep(0.5)
                snap = ROOT / "reports" / f"noid_test_{ts}_{form.class_name}.png"
                w.capture_as_image().save(str(snap))
                print(f"[runner] 폼 스냅샷: {snap.name} ({form.title})")
            except Exception as error:  # noqa: BLE001
                print(f"[runner] 스냅샷 실패: {error!r}")
        navigate.close_forms(session)
        print(f"[runner] 폼 닫기 완료(저장 없음). 남은 폼={len(navigate.open_forms(session))}")
except Exception as error:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    print(f"[runner] exception: {error!r}")
finally:
    log.close()

sys.exit(rc)
