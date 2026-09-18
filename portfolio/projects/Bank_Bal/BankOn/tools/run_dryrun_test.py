"""신한·국민·기업 각 1건 드라이런 대조 보고 러너 — 관리자 권한 python(UIPI). 읽기 전용.

흐름: 작성 탭 조건 조회 → 행 순회로 은행 셀이 '신한'/'국민'인 첫 행 선택(감정서번호는 행에서
읽음, '찾 기' 안 씀) → 작성 폼 열기 → autofill_*(드라이런: 화면값 vs 매핑값 표) → 스크린샷
→ '닫 기'. 저장/입력 없음.
출력: reports/dryrun_<ts>.log / .png
실행: Start-Process python -ArgumentList '"...\tools\run_dryrun_test.py" [from] [to]' -Verb RunAs -Wait
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

DATE_FROM = sys.argv[1] if len(sys.argv) > 1 else "2026-08-10"
DATE_TO = sys.argv[2] if len(sys.argv) > 2 else DATE_FROM
ONLY_DOC = sys.argv[3] if len(sys.argv) > 3 else None   # 특정 감정서번호만(행에서 대조, 찾 기 안 씀)
TAB = sys.argv[4] if len(sys.argv) > 4 else "작성"       # 작성 | 발송완료(사람이 완성·발송한 건 대조용)
EXTRA = sys.argv[5:]                                       # autofill_* 추가 인자(예: --all-objects)
BANKS = {"신한": "autofill_shinhan", "국민": "autofill_kb", "기업": "autofill_ibk"}
# 은행 제한(예: DRYRUN_BANKS=기업) — 지정하면 그 은행 후보만 연다(2026-08-31 기업 대조용).
_only = [b.strip() for b in os.environ.get("DRYRUN_BANKS", "").split(",") if b.strip()]
if _only:
    BANKS = {k: v for k, v in BANKS.items() if k in _only}
import re  # noqa: E402
DOC_RE = re.compile(r"\d{2}-\d{4}-\d-\d{4}")

ts = time.strftime("%Y%m%d_%H%M%S")
log_path = ROOT / "reports" / f"dryrun_{ts}.log"
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

print(f"[runner] start {ts}, 탭={TAB}, 기간={DATE_FROM}~{DATE_TO}, 대상={ONLY_DOC}")
from bankon.config import load_config  # noqa: E402
from bankon.db import connect  # noqa: E402
from bankon.resolver import resolve_document  # noqa: E402
from bankon.ui import driver, navigate  # noqa: E402


SENT_RESULT = "10"   # apw_masterex.Result: 10=완료처리(발송). 반려(22 등)·처리전(01)은 제외.


def apw_progress(cfg, doc_id: str) -> tuple[str, str, bool]:
    """APW(읽기전용) 진행상태(LStatus, Result)와 .gam 유무 — Bank24 그리드 상태('의뢰-접수완료')는
    반려·처리전·발송을 구분 못 하므로 여기서 가른다."""
    try:
        with connect(cfg.source_sql, readonly=True) as conn:
            cur = conn.cursor()
            cur.execute("SELECT LStatus, Result FROM apw_masterex WHERE DocID = ?", doc_id)
            row = cur.fetchone()
            lstatus, result = (str(row[0] or ""), str(row[1] or "")) if row else ("(APW 없음)", "")
            gam = bool(resolve_document(conn, doc_id).remote("gam")) if row else False
            return lstatus, result, gam
    except Exception as error:  # noqa: BLE001
        print(f"[runner] {doc_id} APW 조회 실패: {error!r}")
        return "(조회실패)", "", False


def data_cells(text: str) -> list[str]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return [c.strip() for c in lines[-1].split("\t")] if lines else []


rc = 1
try:
    cfg = load_config(None)
    session = navigate.open_app(cfg.loader_cmd, cfg.bankon_user, cfg.bankon_password)
    if not navigate.select_tab(session, TAB):
        raise navigate.NavigationError(f"{TAB} 탭 선택 실패")
    navigate.query_documents(session, start=DATE_FROM, end=DATE_TO, work_type="담보")
    navigate.close_forms(session)

    candidates: dict[str, list[tuple[int, str, str]]] = {k: [] for k in BANKS}
    for attempt in range(3):   # 행 순회 간헐 실패(클립보드 갱신 지연) → 재조회·재순회
        if attempt:
            print(f"[runner] 후보 0건 — 재조회·재순회 {attempt + 1}/3")
            navigate.query_documents(session, start=DATE_FROM, end=DATE_TO, work_type="담보")
            navigate.close_forms(session)
        seen_rows = 0
        for i, text in navigate.walk_rows(session):
            seen_rows += 1
            cells = data_cells(text)
            if len(cells) < 3:
                continue
            # 탭마다 열 배치가 다를 수 있어 감정서번호는 패턴으로, 은행은 '은행' 들어간 셀로 찾는다.
            found = [c for c in cells if DOC_RE.fullmatch(c)]
            doc_id = found[0] if found else ""
            bank = next((c for c in cells if "은행" in c or "금고" in c or "은  행" in c), cells[0])
            status = cells[8] if len(cells) > 8 else ""
            if not doc_id or (ONLY_DOC and doc_id != ONLY_DOC):
                continue
            for key in BANKS:
                if key in bank:
                    candidates[key].append((i, doc_id, status))
        print(f"[runner] 순회 {seen_rows}행, 후보 {sum(len(v) for v in candidates.values())}건")
        if any(candidates.values()):
            break
    targets: dict[str, tuple[int, str, str]] = {}   # bank -> (index, doc_id, status)
    for key, rows in candidates.items():
        print(f"[runner] {key} 후보 {len(rows)}건")
        for i, doc_id, status in rows:
            lstatus, result, gam = apw_progress(cfg, doc_id)
            ok = (result == SENT_RESULT or bool(ONLY_DOC)) and gam
            print(f"[runner]   {i + 1:3}행 {doc_id} Bank24={status} APW={lstatus}({result}) "
                  f".gam={'있음' if gam else '없음'} → {'대상' if ok else '제외'}")
            if ok and key not in targets:
                targets[key] = (i, doc_id, status)
    missing = [k for k in BANKS if k not in targets]
    if missing:
        print(f"[runner] 목록에 없음: {missing}")

    rc = 0
    for key, (idx, doc_id, status) in targets.items():
        print(f"\n================ {key} {doc_id} ================")
        try:
            navigate.close_forms(session)
            if not navigate.find_row_by_doc(session, doc_id):
                raise navigate.NavigationError(f"{doc_id} 행 재탐색 실패")
            form_ref = navigate.open_write_form(session, home=False)
            print(f"[runner] 폼: {form_ref.class_name} — {form_ref.title}")
            mod = __import__(BANKS[key])
            try:
                r = mod.main([doc_id, *EXTRA])   # 드라이런(기본) — --live 없으면 값 입력 안 함
            except SystemExit as stop:       # verify_*가 .gam 없음 등을 SystemExit로 알림
                print(f"[runner] {BANKS[key]} 중단: {stop}")
                r = 1
            print(f"[runner] {BANKS[key]} exit = {r}")
            rc = rc or r
            try:
                w = driver.window(form_ref.handle)
                w.set_focus()
                time.sleep(0.5)
                snap = ROOT / "reports" / f"dryrun_{ts}_{key}_{form_ref.class_name}.png"
                w.capture_as_image().save(str(snap))
                print(f"[runner] 스냅샷: {snap.name}")
            except Exception as error:  # noqa: BLE001
                print(f"[runner] 스냅샷 실패: {error!r}")
        except Exception as error:  # noqa: BLE001
            traceback.print_exc()
            print(f"[runner] {key} 실패: {error!r}")
            rc = 1
        finally:
            navigate.close_context_menu()
            navigate.close_forms(session)
            print(f"[runner] 폼 닫기(저장 없음). 남은 폼={len(navigate.open_forms(session))}")
except Exception as error:  # noqa: BLE001
    traceback.print_exc()
    print(f"[runner] exception: {error!r}")
finally:
    log.close()

sys.exit(rc)
