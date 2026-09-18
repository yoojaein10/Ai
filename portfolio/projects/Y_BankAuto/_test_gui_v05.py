# -*- coding: utf-8 -*-
"""gui_prototype.py v0.5 검증: geometry / btn_run 렌더링 / 테이블 / 보안 회귀"""
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
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QImage

app = QApplication(sys.argv)

all_ok = True

def chk(label, cond, detail=""):
    global all_ok
    if cond:
        print(f"OK  {label}")
    else:
        print(f"FAIL {label}" + (f" | {detail}" if detail else ""))
        all_ok = False

def rect_in_win(w):
    tl = w.mapTo(win, w.rect().topLeft())
    return QRect(tl, w.rect().size())

def overlaps(w1, w2):
    return rect_in_win(w1).intersects(rect_in_win(w2))

# ── 창 초기화 ────────────────────────────────────────────────────
win = g.MainWindow()
win.resize(1024, 720)
win.show()
app.processEvents()

# ── 10. 1024x720 geometry 검증 ──────────────────────────────────
print("\n[10] 1024x720 geometry")

# login panel body 위젯 목록 (edit_id 의 부모 = panelBody)
login_body  = win.edit_id.parent()
login_lo    = login_body.layout()
login_items = [login_lo.itemAt(i).widget() for i in range(login_lo.count())]
# 예상: QLabel(ID), QLineEdit(id), QLabel(PW), QLineEdit(pw), QCheckBox

lbl_id_w = login_items[0] if len(login_items) > 0 else None
lbl_pw_w  = login_items[2] if len(login_items) > 2 else None

if lbl_id_w:
    chk("ID 라벨-ID 입력 교차 없음",   not overlaps(lbl_id_w, win.edit_id),
        f"lbl={rect_in_win(lbl_id_w)} edit={rect_in_win(win.edit_id)}")
if lbl_pw_w:
    chk("ID 입력-PW 라벨 교차 없음",   not overlaps(win.edit_id, lbl_pw_w),
        f"edit={rect_in_win(win.edit_id)} lbl={rect_in_win(lbl_pw_w)}")
    chk("PW 라벨-PW 입력 교차 없음",   not overlaps(lbl_pw_w, win.edit_pw),
        f"lbl={rect_in_win(lbl_pw_w)} edit={rect_in_win(win.edit_pw)}")
chk("PW 입력-저장 체크박스 교차 없음", not overlaps(win.edit_pw, win.chk_save_cred),
    f"pw={rect_in_win(win.edit_pw)} chk={rect_in_win(win.chk_save_cred)}")
chk("즉시실행-일시정지 교차 없음",     not overlaps(win.btn_run, win.btn_pause),
    f"run={rect_in_win(win.btn_run)} pause={rect_in_win(win.btn_pause)}")

# 자동실행 패널 항목 가시성 (잘림 없음 = isVisible + height > 0)
for label, attr in [
    ("자동실행 상태 레이블 표시", "lbl_sched_state"),
    ("실행 간격 콤보박스 표시",   "cmb_interval"),
    ("다음 실행 레이블 표시",     "lbl_next_run"),
    ("마지막 실행 레이블 표시",   "lbl_last_run"),
    ("즉시실행 버튼 표시",        "btn_run"),
    ("일시정지 버튼 표시",        "btn_pause"),
]:
    ww = getattr(win, attr)
    chk(label, ww.isVisible() and ww.height() > 0,
        f"visible={ww.isVisible()} h={ww.height()}")

# ── 10b. 1280x800 geometry ────────────────────────────────────────
print("\n[10b] 1280x800 geometry")
win.resize(1280, 800)
app.processEvents()

if lbl_id_w:
    chk("1280 ID 라벨-ID 입력 교차 없음",   not overlaps(lbl_id_w, win.edit_id))
if lbl_pw_w:
    chk("1280 PW 라벨-PW 입력 교차 없음",   not overlaps(lbl_pw_w, win.edit_pw))
chk("1280 PW 입력-저장 체크박스 교차 없음", not overlaps(win.edit_pw, win.chk_save_cred))
chk("1280 즉시실행-일시정지 교차 없음",     not overlaps(win.btn_run, win.btn_pause))
chk("1280 자동실행 패널 버튼 표시",
    win.btn_run.isVisible() and win.btn_pause.isVisible())

# ── 11. btn_run 렌더링 검증 ──────────────────────────────────────
print("\n[11] btn_run 렌더링")
win.resize(1024, 720)
app.processEvents()

chk("btn_run 텍스트",     win.btn_run.text() == "▶  즉시 1회 실행", win.btn_run.text())
chk("btn_run isVisible",  win.btn_run.isVisible())
chk("btn_run isEnabled",  win.btn_run.isEnabled())
hint_w = win.btn_run.sizeHint().width()
chk("btn_run 너비≥sizeHint",
    win.btn_run.width() >= hint_w,
    f"width={win.btn_run.width()} sizeHint={hint_w}")

# 로컬 stylesheet 정적 검증
local_ss = win.btn_run.styleSheet()

chk(
    "btn_run 로컬 stylesheet 존재",
    "QPushButton#btn_run" in local_ss,
)
chk(
    "btn_run 로컬 녹색 배경",
    "#16864b" in local_ss,
)
chk(
    "btn_run 로컬 흰색 글자",
    "#ffffff" in local_ss,
)
chk(
    "btn_run 로컬 hover",
    "#0e6b39" in local_ss,
)
chk(
    "btn_run 로컬 disabled",
    "#eef1f4" in local_ss,
)

# 폭 검증
chk(
    "btn_pause width=120",
    win.btn_pause.width() == 120,
    f"width={win.btn_pause.width()}",
)
pause_hint = win.btn_pause.sizeHint().width()
chk(
    "btn_pause 너비>=sizeHint",
    win.btn_pause.width() >= pause_hint,
    f"width={win.btn_pause.width()} sizeHint={pause_hint}",
)
run_hint = win.btn_run.sizeHint().width()
chk(
    "btn_run 너비>=sizeHint",
    win.btn_run.width() >= run_hint,
    f"width={win.btn_run.width()} sizeHint={run_hint}",
)

# 활성 상태 픽셀 검증
win.btn_run.setEnabled(True)
app.processEvents()

image = win.btn_run.grab().toImage().convertToFormat(
    QImage.Format.Format_RGB32
)

color = image.pixelColor(10, 10)
active_rgb = (
    color.red(),
    color.green(),
    color.blue(),
)

target_active = (22, 134, 75)
tolerance = 8

active_ok = all(
    abs(actual - expected) <= tolerance
    for actual, expected in zip(active_rgb, target_active)
)

chk(
    "btn_run 활성 배경 실제 녹색",
    active_ok,
    f"active_rgb={active_rgb}",
)

# 비활성 상태 픽셀 검증
win.btn_run.setEnabled(False)
app.processEvents()

disabled_image = win.btn_run.grab().toImage().convertToFormat(
    QImage.Format.Format_RGB32
)

disabled_color = disabled_image.pixelColor(10, 10)
disabled_rgb = (
    disabled_color.red(),
    disabled_color.green(),
    disabled_color.blue(),
)

target_disabled = (238, 241, 244)  # #eef1f4
disabled_tolerance = 8

disabled_ok = all(
    abs(actual - expected) <= disabled_tolerance
    for actual, expected in zip(disabled_rgb, target_disabled)
)

chk(
    "btn_run 비활성 배경 실제 회색",
    disabled_ok,
    f"disabled_rgb={disabled_rgb}",
)

win.btn_run.setEnabled(True)
app.processEvents()

# 스크린샷 임시 저장 후 삭제 (실제 ID/PW 없음)
grab = win.btn_run.grab()
ss_path = tmp / "btn_run_check.png"
grab.save(str(ss_path))
if ss_path.exists():
    ss_path.unlink()

# ── 12. 테이블 5컬럼 mock ──────────────────────────────────────
print("\n[12] 테이블 5컬럼 mock")
STATUS_COL = g.TABLE_COLS.index("처리 결과")

chk("TABLE_COLS 5개", len(g.TABLE_COLS) == 5, str(g.TABLE_COLS))
chk("컬럼 수 5",       win.table.columnCount() == 5)
chk("헤더[0] 의뢰번호",       win.table.horizontalHeaderItem(0).text() == "의뢰번호")
chk("헤더[1] 감정서번호",     win.table.horizontalHeaderItem(1).text() == "감정서번호")
chk("헤더[2] 은행",           win.table.horizontalHeaderItem(2).text() == "은행")
chk("헤더[3] BankOnline_In",  win.table.horizontalHeaderItem(3).text() == "BankOnline_In")
chk("헤더[4] 처리 결과",      win.table.horizontalHeaderItem(4).text() == "처리 결과")

col_texts = [win.table.horizontalHeaderItem(i).text() for i in range(5)]
chk("영업점 컬럼 없음", "영업점" not in col_texts)
chk("담당자 컬럼 없음", "담당자" not in col_texts)

# mock item (영업점/담당자 포함 — 테이블에는 표시 안 됨)
win._reset_ui()
mock_item = {
    "의뢰번호":   "'00001",
    "감정서번호": "",
    "은행":       "기업은행",
    "영업점":     "테스트지점",
    "담당자":     "테스트담당자",
    "처리상태":   "성공",
}
win._on_worker_item(mock_item)

chk("행 생성",               win.table.rowCount() == 1)
chk("의뢰번호 = 00001",      win.table.item(0, 0).text() == "00001")
chk("감정서번호 = ''",        win.table.item(0, 1).text() == "")
chk("은행 = 기업은행",        win.table.item(0, 2).text() == "기업은행")
chk("BankOnline_In = ''",     win.table.item(0, 3).text() == "")
chk("처리 결과 = 처리 대기", win.table.item(0, STATUS_COL).text() == "처리 대기")

# summary outputs → DB 성공, BankOnline_In 빈값 유지
summary_ok = {
    "db": {
        "enabled": True, "tried": 1, "success": 1, "fail": 0,
        "duplicate_skipped": 0,
        "outputs": [{"의뢰번호": "00001"}],
        "errors":  [],
    }
}
win._on_worker_summary(summary_ok)
chk("summary 후 처리 결과 = DB 성공", win.table.item(0, STATUS_COL).text() == "DB 성공")
chk("summary 후 BankOnline_In = ''",  win.table.item(0, 3).text() == "")

# summary errors → 실패, BankOnline_In 빈값 유지
win._reset_ui()
win._on_worker_item(mock_item)
summary_fail = {
    "db": {
        "enabled": True, "tried": 1, "success": 0, "fail": 1,
        "duplicate_skipped": 0,
        "outputs": [],
        "errors":  [{"의뢰번호": "00001", "error": "insert error"}],
    }
}
win._on_worker_summary(summary_fail)
chk("errors 후 처리 결과 = 실패",   win.table.item(0, STATUS_COL).text() == "실패")
chk("errors 후 BankOnline_In = ''", win.table.item(0, 3).text() == "")

# ── 13. 보안 회귀 ──────────────────────────────────────────────
print("\n[13] 보안 회귀")
win.edit_id.setText("mock-user"); win.edit_pw.setText("mock-password")
win._cfg.read_dict({"database": {"username": "mock-db-user", "password": "mock-db-password"}})

msg = win._sanitize_log_message(
    'login mock-user pw=mock-password DRIVER=ODBC SERVER=192.0.2.10'
)
chk("GUI log ID 마스킹",          "mock-user"     not in msg, msg)
chk("GUI log PW 마스킹",          "mock-password" not in msg, msg)
chk("GUI log DRIVER+SERVER 차단", "[보안]"        in msg,     msg)

# summary 오류 마스킹
win._reset_ui()
win._on_worker_item({"의뢰번호": "'99001", "처리상태": "성공"})
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
chk("summary log mock-user 마스킹",     "mock-user"     not in log_text, log_text)
chk("summary log mock-password 마스킹", "mock-password" not in log_text, log_text)

row99 = win._result_rows_by_docid.get("99001")
if row99 is not None:
    win.table.selectRow(row99); app.processEvents()
    win._on_row_selected()
    detail = win.lbl_selection_detail.text()
    chk("summary row detail mock-user 마스킹",     "mock-user"     not in detail, detail)
    chk("summary row detail mock-password 마스킹", "mock-password" not in detail, detail)
else:
    chk("summary row detail: row 찾기", False, "row not found")

# worker_error 마스킹
win.log_edit.clear()
win._running = False; win._worker = None
raw_msg = 'Connection failed mock-user mock-password DRIVER=SQL SERVER=192.0.2.10'
win._on_worker_error(raw_msg)
log_text2 = win.log_edit.toPlainText()
chk("worker_error log mock-user 마스킹",     "mock-user"     not in log_text2, log_text2)
chk("worker_error log mock-password 마스킹", "mock-password" not in log_text2, log_text2)

# crash.log 마스킹
g.ensure_app_dirs()
g.write_crash_log(
    "conn mock-user fail PASSWORD=mock-password DRIVER=x SERVER=y",
    "tb\nDRIVER=x SERVER=y",
    secrets=("mock-user", "mock-password"),
)
if g.CRASH_LOG.exists():
    content = g.CRASH_LOG.read_text(encoding="utf-8")
    chk("crash.log mock-user 마스킹",     "mock-user"     not in content, "mock-user found!")
    chk("crash.log mock-password 마스킹", "mock-password" not in content, "mock-password found!")
    chk("crash.log conn 차단",            "[보안]"        in content,     "보안 not in crash.log")
else:
    print("SKIP crash.log (path not writable)")

print()
print("ALL PASS" if all_ok else "SOME FAIL")
