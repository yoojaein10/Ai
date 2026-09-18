# -*- coding: utf-8 -*-
"""gui_prototype.py v0.4 보강 검증 (offscreen mock)"""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, r'D:\AI\Claude\Y_BankAuto')

import gui_prototype as g

tmp = Path(tempfile.mkdtemp())
g.APP_DIR      = tmp
g.OUTPUT_DIR   = tmp / 'output'
g.LOG_DIR      = tmp / 'logs'
g.SETTINGS_INI = tmp / 'settings.ini'
g.CRASH_LOG    = tmp / 'logs' / 'crash.log'

from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)

all_ok = True

def chk(label, cond, detail=""):
    global all_ok
    if cond:
        print(f"OK  {label}")
    else:
        print(f"FAIL {label}" + (f" | {detail}" if detail else ""))
        all_ok = False

# ── 1. 오프스크린 레이아웃 ──────────────────────────────────
win = g.MainWindow()
win.resize(1024, 720); win.show(); app.processEvents()
chk("1024x720", win.width() >= 1024 and win.height() >= 720)
win.resize(1280, 800); app.processEvents()
chk("1280x800", win.width() >= 1024)

# ── 2. 간격 5분/10분만 ──────────────────────────────────────
items = [win.cmb_interval.itemText(i) for i in range(win.cmb_interval.count())]
chk("interval 5/10분만", items == ["5분", "10분"], str(items))

# ── 3. 모듈 헬퍼 위치 ───────────────────────────────────────
chk("_normalize_pdf_dir 빈값",  g._normalize_pdf_dir("") == str(g.PDF_DIR))
chk("_normalize_pdf_dir None",  g._normalize_pdf_dir(None) == str(g.PDF_DIR))
chk("_normalize_pdf_dir custom", g._normalize_pdf_dir(r"D:\custom\pdf") == r"D:\custom\pdf")

# legacy C:\Bank24Extractor\{pdf,output} 보정: APP_DIR을 실제 값으로 임시 복원
_real_app = Path(r"C:\Bank24Extractor")
_saved_app, g.APP_DIR = g.APP_DIR, _real_app
chk("_normalize_pdf_dir legacy pdf",
    g._normalize_pdf_dir(r"C:\Bank24Extractor\pdf") == str(g.PDF_DIR))
chk("_normalize_pdf_dir legacy output",
    g._normalize_pdf_dir(r"C:\Bank24Extractor\output") == str(g.PDF_DIR))
g.APP_DIR = _saved_app

chk("_normalize_result_docid quote",    g._normalize_result_docid("'00001") == "00001")
chk("_normalize_result_docid space",    g._normalize_result_docid("  5001 ") == "5001")
chk("_normalize_result_docid None",     g._normalize_result_docid(None) == "")

s = g._sanitize_sensitive_text("user=abc PWD=secret123", secrets=("abc",))
chk("_sanitize_sensitive_text",
    "abc" not in s and "secret123" not in s, s)

# ── 4. PDF 경로 우선순위 ─────────────────────────────────────
win.edit_id.setText("mockuser"); win.edit_pw.setText("mockpass")
cfg = win._cfg

# A: [pdf] dir 있음
cfg.read_dict({"pdf": {"dir": r"D:\custom\pdf"}, "paths": {"output_dir": ""}})
pdf_s = cfg.get("pdf", "dir", fallback="").strip()
pth_s = cfg.get("paths", "output_dir", fallback="").strip()
rA = g._normalize_pdf_dir(pdf_s or pth_s or str(g.PDF_DIR))
chk("pdf case A custom", rA == r"D:\custom\pdf", rA)

# B: [pdf] 빈값 + [paths] legacy
cfg.read_dict({"pdf": {"dir": ""}, "paths": {"output_dir": r"D:\legacy\pdf"}})
pdf_s = cfg.get("pdf", "dir", fallback="").strip()
pth_s = cfg.get("paths", "output_dir", fallback="").strip()
rB = g._normalize_pdf_dir(pdf_s or pth_s or str(g.PDF_DIR))
chk("pdf case B legacy path", rB == r"D:\legacy\pdf", rB)

# C: 둘 다 없음
cfg.read_dict({"pdf": {"dir": ""}, "paths": {"output_dir": ""}})
pdf_s = cfg.get("pdf", "dir", fallback="").strip()
pth_s = cfg.get("paths", "output_dir", fallback="").strip()
rC = g._normalize_pdf_dir(pdf_s or pth_s or str(g.PDF_DIR))
chk("pdf case C UNC fallback", rC == str(g.PDF_DIR), rC)

# D/E: legacy → UNC (APP_DIR 실제값으로 임시 복원)
_saved_app2, g.APP_DIR = g.APP_DIR, Path(r"C:\Bank24Extractor")
rD = g._normalize_pdf_dir(r"C:\Bank24Extractor\pdf")
chk("pdf case D legacy APP\\pdf", rD == str(g.PDF_DIR), rD)
rE = g._normalize_pdf_dir(r"C:\Bank24Extractor\output")
chk("pdf case E legacy APP\\output", rE == str(g.PDF_DIR), rE)
g.APP_DIR = _saved_app2

# ── 5. item / summary 상태 갱신 ─────────────────────────────
win._reset_ui()
STATUS_COL = g.TABLE_COLS.index("처리 결과")

# 성공 → 처리 대기
item_ok = {"의뢰번호": "'00001", "처리상태": "성공", "비고": "OK"}
win._on_worker_item(item_ok)
c0 = win.table.item(0, STATUS_COL)
chk("item 성공 → 처리 대기", c0 and c0.text() == "처리 대기", c0.text() if c0 else "None")
chk("docid 00001 row=0", win._result_rows_by_docid.get("00001") == 0)

# 실패 → 저장 제외
item_fail = {"의뢰번호": "00002", "처리상태": "실패", "실패사유": "PDF 오류"}
win._on_worker_item(item_fail)
c1 = win.table.item(1, STATUS_COL)
chk("item 실패 → 저장 제외", c1 and c1.text() == "저장 제외", c1.text() if c1 else "None")

# summary outputs → DB 성공, errors → 실패
summary = {
    "db": {
        "enabled": True, "tried": 2, "success": 1, "fail": 1,
        "duplicate_skipped": 0,
        "outputs": [{"의뢰번호": "00001"}],
        "errors":  [{"의뢰번호": "00002", "error": "insert fail"}],
    }
}
win._on_worker_summary(summary)
c0s = win.table.item(0, STATUS_COL)
c1s = win.table.item(1, STATUS_COL)
chk("summary 00001 → DB 성공", c0s and c0s.text() == "DB 성공", c0s.text() if c0s else "None")
chk("summary 00002 → 실패",    c1s and c1s.text() == "실패",    c1s.text() if c1s else "None")

# 처리 대기 → 처리 완료
win._reset_ui()
win._on_worker_item({"의뢰번호": "00003", "처리상태": "성공"})
assert win.table.item(0, STATUS_COL).text() == "처리 대기"
win._on_worker_summary({"db": {"enabled": True, "tried": 0, "success": 0, "fail": 0,
                                "outputs": [], "errors": [], "duplicate_skipped": 0}})
c3 = win.table.item(0, STATUS_COL)
chk("처리 대기 → 처리 완료", c3 and c3.text() == "처리 완료", c3.text() if c3 else "None")

# ── 6. 선택 상세 우선순위 ────────────────────────────────────
win._reset_ui()
win.table.insertRow(0)
win._result_items_by_row[0] = {
    "실패사유": "PDF 파싱 오류", "DB 오류": "timeout", "비고": "bigo", "처리상태": "실패"
}
win.table.selectRow(0); app.processEvents()
win._on_row_selected()
detail = win.lbl_selection_detail.text()
chk("선택상세 실패사유 우선", "PDF" in detail, detail)

win._result_items_by_row[0] = {"DB 오류": "db error msg", "비고": "bigo"}
win._on_row_selected()
chk("선택상세 DB 오류 우선", "db error msg" in win.lbl_selection_detail.text())

win._result_items_by_row[0] = {"비고": "only bigo"}
win._on_row_selected()
chk("선택상세 비고 fallback", "only bigo" in win.lbl_selection_detail.text())

# ── 7. 보안 마스킹 ───────────────────────────────────────────
win.edit_id.setText("testuser"); win.edit_pw.setText("testpass")

msg = win._sanitize_log_message(
    'login testuser pw=testpass DRIVER=ODBC SERVER=192.0.2.10'
)
chk("GUI log ID 마스킹",     "testuser" not in msg, msg)
chk("GUI log PW 마스킹",     "testpass" not in msg, msg)
chk("GUI log DRIVER+SERVER 차단", "[보안]" in msg, msg)

safe_e = g._sanitize_sensitive_text(
    "err testuser PASSWORD=testpass DRIVER=x SERVER=y",
    secrets=("testuser", "testpass"),
)
chk("error_signal ID 마스킹",     "testuser" not in safe_e, safe_e)
chk("error_signal PW 마스킹",     "testpass" not in safe_e, safe_e)
chk("error_signal conn 차단",     "[보안]" in safe_e,        safe_e)

g.ensure_app_dirs()
g.write_crash_log(
    "conn testuser fail PASSWORD=testpass DRIVER=x SERVER=y",
    "tb\nDRIVER=x SERVER=y",
    secrets=("testuser", "testpass"),
)
if g.CRASH_LOG.exists():
    content = g.CRASH_LOG.read_text(encoding="utf-8")
    chk("crash.log ID 마스킹",     "testuser" not in content, "testuser found!")
    chk("crash.log PW 마스킹",     "testpass" not in content, "testpass found!")
    chk("crash.log conn 차단",     "[보안]" in content,        "보안 not in crash.log")
else:
    print("SKIP crash.log (path not writable)")

# ── 8. 완료 후 헤더 대기 복귀 ───────────────────────────────
win.header.set_state("run")
chk("run state set", win.header._text.text() == "실행 중")
win._on_worker_finished(True)
chk("완료 후 헤더 대기 복귀", win.header._text.text() == "대기", win.header._text.text())

# 오류 후 err 유지
win.header.set_state("run")
win._running = False; win._worker = None
win._on_worker_error("mock error")
chk("오류 후 헤더 err", win.header._text.text() == "오류")

# ── 9. Task-7 보안 마스킹 (summary 오류 + worker 오류) ─────────
win.edit_id.setText("mock-user"); win.edit_pw.setText("mock-password")
# DB 설정을 configparser에 직접 세팅
win._cfg.read_dict({"database": {"username": "mock-db-user", "password": "mock-db-password"}})

# 9-a: _on_worker_summary — errors에 민감정보 포함 시 log/row 마스킹
win._reset_ui()
win._on_worker_item({"의뢰번호": "99001", "처리상태": "성공"})
raw_err = 'ODBC Error mock-user PASSWORD=mock-password SERVER=192.0.2.10 DRIVER=SQL'
summary_sec = {
    "db": {
        "enabled": True, "tried": 1, "success": 0, "fail": 1,
        "duplicate_skipped": 0,
        "outputs": [],
        "errors": [{"의뢰번호": "99001", "error": raw_err}],
    }
}
win.log_edit.clear()
win._on_worker_summary(summary_sec)
log_text = win.log_edit.toPlainText()
chk("summary log: mock-user 마스킹",     "mock-user"     not in log_text, log_text)
chk("summary log: mock-password 마스킹", "mock-password" not in log_text, log_text)
chk("summary log: 보안 차단 표시",       "[보안]" in log_text or "***" in log_text,
    log_text)

# 9-b: row status error_text 마스킹 (selection detail)
row99 = win._result_rows_by_docid.get("99001")
if row99 is not None:
    win.table.selectRow(row99); app.processEvents()
    win._on_row_selected()
    detail = win.lbl_selection_detail.text()
    chk("summary row detail: mock-user 마스킹",     "mock-user"     not in detail, detail)
    chk("summary row detail: mock-password 마스킹", "mock-password" not in detail, detail)
else:
    chk("summary row detail: mock-user 마스킹",     False, "row not found")
    chk("summary row detail: mock-password 마스킹", False, "row not found")

# 9-c: _on_worker_error — raw msg에 민감정보 포함 시 log 마스킹
win.log_edit.clear()
win._running = False; win._worker = None
raw_err_msg = 'Connection failed mock-user mock-password DRIVER=SQL SERVER=192.0.2.10'
win._on_worker_error(raw_err_msg)
log_text2 = win.log_edit.toPlainText()
chk("worker_error log: mock-user 마스킹",     "mock-user"     not in log_text2, log_text2)
chk("worker_error log: mock-password 마스킹", "mock-password" not in log_text2, log_text2)
chk("worker_error log: 보안 차단 표시",       "[보안]" in log_text2 or "***" in log_text2,
    log_text2)
chk("worker_error log: 헤더 err",             win.header._text.text() == "오류")

print()
print("ALL PASS" if all_ok else "SOME FAIL")
