"""query 실화면 시험 러너 — 관리자 권한 python으로 실행.

'찾 기'(감정서번호 검색)는 쓰지 않는다. 작성 탭에서 업무구분·기간 조건 조회만 시험.
출력은 reports/query_test_<ts>.log 에 남긴다.
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

ts = time.strftime("%Y%m%d_%H%M%S")
log_path = ROOT / "reports" / f"query_test_{ts}.log"
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

print(f"[runner] start {ts}, cwd={os.getcwd()}")
from bankon import cli  # noqa: E402

rc = 1
try:
    rc = cli.main([
        "query",
        "--from", "2026-08-18",
        "--to", "2026-08-18",
        "--work-type", "담보",
    ])
    print(f"[runner] exit code = {rc}")
    # 검증용: 업무구분·기간검색 라디오 그룹 스크린샷(판독은 사람이/Claude가)
    try:
        from bankon.config import load_config
        from bankon.ui import driver

        cfg = load_config(None)
        windows = driver.find_windows(
            driver.MAIN_CLASS, title_any=driver.MAIN_TITLE_HINTS)
        if windows:
            handle = windows[0].handle
            driver.window(handle).set_focus()
            time.sleep(0.5)
            for name in ("업무구분", "기간검색"):
                group = driver.by_text(handle, name, "TcxRadioGroup")
                if group is not None:
                    snap = ROOT / "reports" / f"query_test_{ts}_{name}.png"
                    group.capture_as_image().save(str(snap))
                    print(f"[runner] 스냅샷: {snap.name}")
    except Exception as error:  # noqa: BLE001
        print(f"[runner] 스냅샷 실패: {error!r}")
except Exception as error:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    print(f"[runner] exception: {error!r}")
finally:
    log.close()

sys.exit(rc)
