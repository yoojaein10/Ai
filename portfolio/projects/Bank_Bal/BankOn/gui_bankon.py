"""BankOn GUI — Apw_YJI_Send 큐를 지켜보다가 등록된 신한·국민·기업·농협은행·수협·하나·우리·새마을금고 담보 감정서를 Bank24 에 자동 작성한다.
(Y_BankAuto gui_prototype 과 같은 PyQt6 구성: 헤더 / 왼쪽 설정 / 오른쪽 처리 목록 / 아래 로그)

흐름: 시작 → 관리자 권한 확인(아니면 스스로 재실행) → Bank24 연결(없으면 러너가 기동·로그인)
      → N초마다 Apw_YJI_Send 조회 → 신한/국민 담보 건마다 run_shinhan_full / run_kb_full 을 자식 프로세스로 실행
      (작성 입력→저장→PDF등록→현장조사서→저장[→국민 현장조사서 PDF]) → Apw_YJI_BankAuto 이력 기록.
      발송(B/G)은 하지 않는다(수동). 입력 거부 칸은 비운 채 저장하고 '완료'+비고(담당자 확인) — 2026-09-03 정책.

모드·은행·주기·PDF 옵션은 gui_settings.ini [run] 에서(mode=live|dry, banks, interval_seconds, attach_pdf, max_per_round, statuses, only_doc). 화면엔 조회일자만.
실행: python gui_bankon.py   (exe: pyinstaller bankon_gui.spec → dist/BankOn.exe, 관리자 매니페스트 포함)
설정: <실행폴더>/gui_settings.ini   로그: reports/gui_<날짜>.log + 러너별 reports/full_<ts>.log
"""
from __future__ import annotations

import configparser
import ctypes
import datetime as dt
import os
import re
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path
from types import SimpleNamespace

FROZEN = bool(getattr(sys, "frozen", False))
ROOT = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
SRC_ROOT = ROOT            # 소스 실행: 저장소 루트. exe: exe 폴더(.env·gui_settings.ini·work·output·reports 가 여기 생김)
if not FROZEN:
    sys.path.insert(0, str(SRC_ROOT / "src"))
    sys.path.insert(0, str(SRC_ROOT / "tools"))
os.chdir(SRC_ROOT)


def _run_bundled_runner(argv: list[str]) -> int:
    """`BankOn.exe --runner <모듈> <인자…>` — 큐 워커가 러너(run_kb_full 등)를 띄울 때 exe 가 자기 자신을 재호출한다.
    단일 exe 배포(2026-08-31): 별도 python·소스 트리 없이 번들 안의 tools 모듈을 스크립트처럼 실행한다."""
    import io
    import runpy
    if sys.stdout is None:                      # 창 없는 exe 는 stdout 이 None 일 수 있다 → 부모 파이프(fd 1)로 연다
        sys.stdout = io.TextIOWrapper(os.fdopen(1, "wb", closefd=False), encoding="utf-8", errors="replace", line_buffering=True)
    else:                                       # PyInstaller 는 PYTHONIOENCODING 을 무시(isolated) → cp949 로 잡힘 → UTF-8 강제
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    if sys.stderr is None:
        sys.stderr = sys.stdout
    else:
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    sys.__stdout__, sys.__stderr__ = sys.stdout, sys.stderr   # 러너의 Tee 가 sys.__stdout__ 에 쓴다
    module, rest = argv[0], argv[1:]
    sys.argv = [f"{module}.py", *rest]
    try:
        runpy.run_module(module, run_name="__main__", alter_sys=True)
    except SystemExit as exc:
        code = exc.code
        return code if isinstance(code, int) else (0 if code is None else 1)
    return 0


if len(sys.argv) >= 3 and sys.argv[1] == "--runner":
    sys.exit(_run_bundled_runner(sys.argv[2:]))

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal          # noqa: E402
from PyQt6.QtGui import QColor, QTextCursor                          # noqa: E402
from PyQt6.QtWidgets import (                                        # noqa: E402
    QApplication, QCheckBox, QDateEdit, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

APP_TITLE = "BankOn — Bank24 담보 자동작성"
APP_VERSION = "v0.1"
SETTINGS_INI = ROOT / "gui_settings.ini"
LOG_DIR = ROOT / "reports"
LOG_DIR.mkdir(parents=True, exist_ok=True)
TABLE_COLS = ["감정서번호", "은행명", "처리일자", "처리시간", "완료여부", "비고"]

C = {
    "bg": "#f3f5f8", "surface": "#ffffff", "surface_soft": "#f8fafc", "line": "#d7dde6", "line_strong": "#b9c3d0",
    "text": "#202733", "muted": "#687486", "blue": "#1264d8", "blue_soft": "#e9f2ff", "green": "#16864b",
    "green_soft": "#e8f7ef", "amber": "#a86712", "amber_soft": "#fff4dc", "red": "#c43b3b", "red_soft": "#fff0f0",
}
STYLESHEET = f"""
QMainWindow, QWidget {{ background-color: {C['bg']}; color: {C['text']};
    font-family: 'Segoe UI', 'Pretendard', 'Noto Sans KR', '맑은 고딕', sans-serif; font-size: 13px; }}
QLineEdit, QDateEdit, QSpinBox {{ background-color: {C['surface']}; border: 1px solid {C['line_strong']};
    border-radius: 6px; padding: 4px 8px; min-height: 30px; }}
QPushButton {{ border-radius: 6px; padding: 5px 12px; font-size: 13px; border: 1px solid {C['line_strong']};
    background-color: {C['surface']}; color: #344256; font-weight: 700; }}
QPushButton:hover {{ background-color: #f4f6f8; }}
QPushButton:disabled {{ background-color: #eef1f4; color: #9aa4b2; border-color: {C['line']}; }}
QPushButton#btn_run {{ background-color: {C['green']}; color: #ffffff; border: 1px solid {C['green']}; }}
QPushButton#btn_run:hover {{ background-color: #0e6b39; }}
QPushButton#btn_stop {{ background-color: {C['red']}; color: #ffffff; border: 1px solid {C['red']}; }}
QCheckBox {{ spacing: 7px; color: #465468; font-size: 12px; font-weight: 600; }}
QCheckBox::indicator {{ width: 15px; height: 15px; border: 1px solid {C['line_strong']}; border-radius: 3px;
    background: {C['surface']}; }}
QCheckBox::indicator:checked {{ background-color: {C['blue']}; border-color: {C['blue']}; }}
QTableWidget {{ background-color: {C['surface']}; border: none; gridline-color: #eef1f4;
    selection-background-color: {C['blue_soft']}; selection-color: {C['text']}; font-size: 12px; }}
QHeaderView::section {{ background-color: #f0f3f7; border: none; border-bottom: 1px solid {C['line_strong']};
    border-right: 1px solid {C['line']}; padding: 4px 8px; font-weight: 700; font-size: 12px; color: #465468; height: 32px; }}
QTextEdit {{ background-color: #fbfcfd; border: none; color: #48576a; font-family: 'Consolas', '맑은 고딕', monospace;
    font-size: 12px; padding: 8px 12px; }}
"""

_DEFAULT_INI = """\
[run]
mode = live
banks = 신한,국민,기업,농협,수협,하나,우리,새마을
interval_seconds = 600
since_days = 0
attach_pdf = true
max_per_round = 20
; 큐 Status 허용값(쉼표). 사용자 확정(2026-09-03): 대기 건만 처리(종전 진행)
statuses = 대기
; 테스트용: 감정서번호를 적으면 그 1건만 처리(조회일자 무시). 시연 끝나면 비울 것
only_doc =
; 시연·재작성용: 사람이 이미 작성한 폼이어도 진행(사람이 쓴 값에 덮어쓸 수 있음).
; 감정서번호를 적으면 **그 건에만** 걸린다(쉼표로 여러 개). true 로 두면 번호 칸에 적은 아무 건이나 뚫린다 — 권하지 않음.
; 화면에 번호를 적고 '1회 처리' 한 경우에만 동작한다(감시 모드는 무시). 시연 끝나면 비울 것
force =
; 전례 PDF 가 아예 없는 건: 감정서번호를 적으면 그 건은 PDF 탐색·등록을 통째로 건너뛰고 바로 입력으로 간다
; (네트워크 공유에서 4번 헛찾는 데만 3분). force 와 같은 형식 — 번호(쉼표 구분) 또는 true
no_pdf_docs =
"""


# ── 유틸 ─────────────────────────────────────────────────────────
def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def relaunch_as_admin() -> None:
    """Bank24 가 elevated 라 일반 권한으로는 입력이 막힌다(UIPI) → 관리자로 스스로 재실행."""
    if getattr(sys, "frozen", False):
        exe, params = sys.executable, ""
    else:
        exe, params = sys.executable, f'"{Path(__file__).resolve()}"'
    ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, str(SRC_ROOT), 1)


def load_settings() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    cfg.read_string(_DEFAULT_INI)
    if SETTINGS_INI.exists():
        cfg.read(SETTINGS_INI, encoding="utf-8")
    return cfg


def save_settings(cfg: configparser.ConfigParser) -> None:
    with open(SETTINGS_INI, "w", encoding="utf-8") as fh:
        cfg.write(fh)


def bank24_running() -> bool:
    try:
        from bankon.ui import driver
        return bool(driver.find_windows(driver.MAIN_CLASS, title_any=driver.MAIN_TITLE_HINTS))
    except Exception:  # noqa: BLE001
        return False


# ── 큐 워커 스레드 ───────────────────────────────────────────────
class QueueWorker(QThread):
    log = pyqtSignal(str, str)          # (메시지, 색)
    item = pyqtSignal(dict)
    round_done = pyqtSignal(int)
    finished_ok = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, opt: SimpleNamespace, once: bool):
        super().__init__()
        self.opt = opt
        self.once = once
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        try:
            import run_queue_worker as W
            from bankon.config import load_config
            cfg = load_config(None)
            if W.STOP_FILE.exists():
                W.STOP_FILE.unlink()
            while not self._stop.is_set():
                try:
                    n = W.one_round(cfg, self.opt, emit=lambda m: self.log.emit(m, ""),
                                    on_item=self.item.emit, should_stop=self._stop.is_set,
                                    on_line=lambda ln: self.log.emit("    " + ln, "muted"))
                    self.round_done.emit(n)
                except Exception as error:  # noqa: BLE001
                    self.log.emit(f"바퀴 실패 {error!r}", "red")
                    self.log.emit(traceback.format_exc(), "muted")
                if self.once or self._stop.is_set():
                    break
                for _ in range(int(self.opt.interval)):
                    if self._stop.is_set():
                        break
                    time.sleep(1)
            self.finished_ok.emit()
        except Exception as error:  # noqa: BLE001
            self.failed.emit(f"{error!r}\n{traceback.format_exc()}")


# ── 위젯 ─────────────────────────────────────────────────────────
class HeaderWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(56)
        self.setStyleSheet(f"background-color: {C['surface']}; border-bottom: 1px solid {C['line']};")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 0, 18, 0)
        lay.setSpacing(11)
        mark = QLabel("◆")
        mark.setStyleSheet(f"color: {C['blue']}; font-size: 14px; background: transparent; border: none;")
        title = QLabel(APP_TITLE)
        title.setStyleSheet(f"font-size: 16px; font-weight: 700; color: {C['text']}; background: transparent; border: none;")
        lay.addWidget(mark)
        lay.addWidget(title)
        lay.addStretch()
        self.bank24 = QLabel("Bank24: 확인 중")
        self.bank24.setStyleSheet(f"color: {C['muted']}; font-size: 12px; background: transparent; border: none;")
        lay.addWidget(self.bank24)
        self._dot, self._text = QLabel("●"), QLabel("대기")
        self.badge = QWidget()
        self.badge.setFixedHeight(28)
        bl = QHBoxLayout(self.badge)
        bl.setContentsMargins(11, 0, 11, 0)
        bl.setSpacing(7)
        bl.addWidget(self._dot)
        bl.addWidget(self._text)
        lay.addWidget(self.badge)
        ver = QLabel(APP_VERSION + ("  [관리자]" if is_admin() else "  [일반권한]"))
        ver.setStyleSheet(f"color: {C['muted']}; font-size: 12px; background: transparent; border: none; margin-left: 12px;")
        lay.addWidget(ver)
        self.set_state("wait")

    def set_state(self, state: str):
        m = {"wait": ("#edf1f5", "#31506f", "대기"), "run": ("#e8f7ef", "#0e6b39", "감시 중"),
             "busy": ("#fff4dc", "#a86712", "처리 중"), "stop": ("#fff4dc", "#a86712", "중단됨"),
             "err": ("#fff0f0", "#c43b3b", "오류")}
        bg, fg, label = m.get(state, m["wait"])
        self.badge.setStyleSheet(f"background-color: {bg}; border-radius: 14px; border: none;")
        self._dot.setStyleSheet(f"color: {fg}; font-size: 9px; background: transparent; border: none;")
        self._text.setStyleSheet(f"color: {fg}; font-size: 12px; font-weight: 700; background: transparent; border: none;")
        self._text.setText(label)

    def set_bank24(self, running: bool):
        self.bank24.setText("Bank24: 실행 중" if running else "Bank24: 없음(시작 시 자동 기동)")
        self.bank24.setStyleSheet(f"color: {C['green'] if running else C['amber']}; font-size: 12px; background: transparent; border: none;")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1180, 760)
        self.setMinimumSize(980, 600)
        self.setStyleSheet(STYLESHEET)
        self._cfg = load_settings()
        self._worker: QueueWorker | None = None
        self._rows: dict[int, int] = {}
        self._log_file = None

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.header = HeaderWidget()
        root.addWidget(self.header)
        ws_widget = QWidget()
        ws = QHBoxLayout(ws_widget)
        ws.setContentsMargins(14, 14, 14, 14)
        ws.setSpacing(14)
        ws.addWidget(self._build_left())
        ws.addWidget(self._build_table(), 1)
        root.addWidget(ws_widget, 1)
        root.addWidget(self._build_log())
        self._apply_settings()

        self._bank_timer = QTimer(self)
        self._bank_timer.timeout.connect(lambda: self.header.set_bank24(bank24_running()))
        self._bank_timer.start(5000)
        self.header.set_bank24(bank24_running())
        self.since.dateChanged.connect(lambda _d: (self.table.setRowCount(0), self._rows.clear(), self._load_history()))
        QTimer.singleShot(300, self._load_history)
        if not is_admin():
            self._log("⚠ 일반 권한입니다 — Bank24(관리자)에 입력이 막힙니다. 시작을 누르면 관리자로 재실행합니다.", "amber")

    # ── 패널 ──
    def _panel(self, title: str):
        outer = QWidget()
        outer.setObjectName("panelOuter")
        outer.setStyleSheet(f"QWidget#panelOuter {{ background: {C['surface']}; border: 1px solid {C['line']}; border-radius: 8px; }}")
        ov = QVBoxLayout(outer)
        ov.setContentsMargins(0, 0, 0, 0)
        ov.setSpacing(0)
        hdr = QWidget()
        hdr.setFixedHeight(40)
        hdr.setStyleSheet(f"background: transparent; border-bottom: 1px solid {C['line']};")
        hh = QHBoxLayout(hdr)
        hh.setContentsMargins(14, 0, 14, 0)
        t = QLabel(title)
        t.setStyleSheet("font-size: 13px; font-weight: 700; background: transparent; border: none;")
        hh.addWidget(t)
        ov.addWidget(hdr)
        body = QWidget()
        body.setStyleSheet("background: transparent;")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(14, 12, 14, 12)
        bl.setSpacing(10)
        ov.addWidget(body, 1)
        return outer, bl

    def _build_left(self) -> QWidget:
        panel, lay = self._panel("설정")
        panel.setFixedWidth(330)

        lay.addWidget(QLabel("조회일자"))
        self.since = QDateEdit()
        self.since.setCalendarPopup(True)
        self.since.setDisplayFormat("yyyy-MM-dd")
        self.since.setFixedHeight(34)
        lay.addWidget(self.since)

        self.mode_hint = QLabel("")
        self.mode_hint.setWordWrap(True)
        self.mode_hint.setStyleSheet(f"color: {C['muted']}; font-size: 11px; background: transparent;")
        lay.addWidget(self.mode_hint)

        lay.addSpacing(6)
        self.btn_run = QPushButton("▶  감시 시작")
        self.btn_run.setFixedHeight(40)
        self.btn_run.setStyleSheet(f"QPushButton {{ background-color: {C['green']}; color: white; border: 1px solid {C['green']};"
                                   f" border-radius: 6px; font-weight: 700; font-size: 14px; }}"
                                   f" QPushButton:hover {{ background-color: #0e6b39; }}"
                                   f" QPushButton:disabled {{ background-color: #eef1f4; color: #9aa4b2; border-color: {C['line']}; }}")
        self.btn_run.clicked.connect(lambda: self._start(once=False))
        lay.addWidget(self.btn_run)
        # 감정서번호 칸 + 1회 처리: 번호를 적으면 그 건만(큐 Status 무관하게 조회), 비우면 큐 전체(ini only_doc 적용)
        once_row = QHBoxLayout()
        once_row.setSpacing(6)
        self.doc_edit = QLineEdit()
        self.doc_edit.setPlaceholderText("감정서번호 (예: 01-2608-3-2703)")
        self.doc_edit.setFixedHeight(34)
        self.doc_edit.setClearButtonEnabled(True)
        self.doc_edit.returnPressed.connect(lambda: self._start(once=True))
        once_row.addWidget(self.doc_edit, 3)
        self.btn_once = QPushButton("1회 처리")
        self.btn_once.setFixedHeight(34)
        self.btn_once.setMinimumWidth(80)
        self.btn_once.clicked.connect(lambda: self._start(once=True))
        once_row.addWidget(self.btn_once, 1)
        lay.addLayout(once_row)
        self.btn_stop = QPushButton("■  정지 (현재 건 마친 뒤)")
        self.btn_stop.setFixedHeight(34)
        self.btn_stop.setStyleSheet(f"QPushButton {{ background-color: {C['red']}; color: white; border: 1px solid {C['red']};"
                                    f" border-radius: 6px; font-weight: 700; }}"
                                    f" QPushButton:disabled {{ background-color: #eef1f4; color: #9aa4b2; border-color: {C['line']}; }}")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop)
        lay.addWidget(self.btn_stop)
        lay.addStretch()
        b1 = QPushButton("로그 폴더")
        b1.setFixedHeight(32)
        b1.clicked.connect(lambda: os.startfile(str(LOG_DIR)))
        lay.addWidget(b1)
        note = QLabel("발송(B/G)은 자동화하지 않습니다.\n입력 거부 칸·없는 PDF 는 건너뛰고 '완료'로 남기니 비고를 보고 담당자가 보완하세요.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {C['muted']}; font-size: 11px; background: transparent;")
        lay.addWidget(note)
        return panel

    def _build_table(self) -> QWidget:
        panel, lay = self._panel("처리 목록 (이력 + 이번 세션)")
        self.table = QTableWidget(0, len(TABLE_COLS))
        self.table.setHorizontalHeaderLabels(TABLE_COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        hh = self.table.horizontalHeader()
        for i in range(len(TABLE_COLS) - 1):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(len(TABLE_COLS) - 1, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.table)
        return panel

    def _build_log(self) -> QWidget:
        panel, lay = self._panel("로그")
        panel.setFixedHeight(230)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        lay.addWidget(self.log_view)
        return panel

    # ── 설정 ──
    def _apply_settings(self):
        r = self._cfg["run"]
        self.since.setDate(dt.date.today() - dt.timedelta(days=r.getint("since_days", 0)))
        live = r.get("mode", "live") == "live"
        banks = ",".join(b.strip() for b in r.get("banks", "신한,국민,기업,농협,수협,하나,우리,새마을").split(","))
        self.mode_hint.setText(
            (f"모드: {'★실입력(LIVE) — 저장·PDF등록·현장조사서까지' if live else '드라이런 — 계획만, 저장 없음'}"
             f"\n은행: {banks} · 주기 {r.getint('interval_seconds', 600)}초 · PDF등록 {'포함' if r.getboolean('attach_pdf', True) else '제외'}"
             f"\n(변경은 {SETTINGS_INI.name})"))
        self.mode_hint.setStyleSheet(f"color: {C['red'] if live else C['muted']}; font-size: 11px; background: transparent;")

    def _save(self):
        r = self._cfg["run"]
        r["since_days"] = str((dt.date.today() - self.since.date().toPyDate()).days)
        save_settings(self._cfg)

    # ── 실행 ──
    def _opt(self, *, once: bool = True) -> SimpleNamespace:
        r = self._cfg["run"]
        banks = {b.strip() for b in r.get("banks", "신한,국민,기업,농협,수협,하나,우리,새마을").split(",") if b.strip()}
        live = r.get("mode", "live") == "live"
        statuses = tuple(x.strip() for x in r.get("statuses", "대기").split(",") if x.strip())
        only_doc = r.get("only_doc", "").strip() or None
        typed = self.doc_edit.text().strip() if once else ""   # 감시 모드는 화면 번호를 무시
        if typed:
            only_doc = typed            # 화면에 적은 번호가 ini 보다 우선. 큐 Status 도 가리지 않는다(대기/진행/완료).
            statuses = tuple(dict.fromkeys(statuses + ("대기", "진행", "완료")))
        return SimpleNamespace(live=live, dry=not live, record=False, since=self.since.date().toString("yyyy-MM-dd"),
                               seq=None, max=r.getint("max_per_round", 20), no_pdf=not r.getboolean("attach_pdf", True),
                               banks=banks, interval=r.getint("interval_seconds", 600),
                               statuses=statuses, only_doc=only_doc, force=r.get("force", "").strip(),
                               no_pdf_docs=r.get("no_pdf_docs", "").strip())

    def _start(self, once: bool):
        if self._worker and self._worker.isRunning():
            return
        if not is_admin():
            QMessageBox.information(self, "관리자 권한 필요", "Bank24 가 관리자 권한이라 일반 권한으로는 입력이 막힙니다.\n관리자로 다시 실행합니다.")
            relaunch_as_admin()
            QApplication.quit()
            return
        typed = self.doc_edit.text().strip()
        if once and typed and not re.fullmatch(r"\d{2}-\d{4}-\d-\d{4}", typed):
            QMessageBox.warning(self, "감정서번호", f"감정서번호 형식이 아닙니다: {typed}\n예: 01-2608-3-2703")
            return
        opt = self._opt(once=once)
        if not opt.banks:
            QMessageBox.warning(self, "은행 선택", "대상 은행을 하나 이상 고르세요.")
            return
        self._save()
        self._open_log_file()
        self._log(f"===== {'1회' if once else '감시'} 시작 모드={'LIVE' if opt.live else 'DRY'} 은행={sorted(opt.banks)} "
                  f"since={opt.since} interval={opt.interval}s pdf={'포함' if not opt.no_pdf else '제외'}"
                  f"{' ★only_doc=' + opt.only_doc if opt.only_doc else ''} statuses={opt.statuses}"
                  f"{' ★force(사람 작성 폼도 진행)' if (opt.force and opt.only_doc) else ''} =====", "blue")
        self._worker = QueueWorker(opt, once)
        self._worker.log.connect(self._log)
        self._worker.item.connect(self._on_item)
        self._worker.round_done.connect(lambda n: (self.header.set_state("run"), self._load_history()))
        self._worker.finished_ok.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._set_running(True)
        self._worker.start()

    def _stop(self):
        if self._worker:
            self._worker.stop()
            self._log("정지 요청 — 현재 건을 마치면 멈춥니다.", "amber")
            self.btn_stop.setEnabled(False)

    def _set_running(self, running: bool):
        for w in (self.btn_run, self.btn_once, self.since, self.doc_edit):
            w.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self.header.set_state("run" if running else "wait")

    def _on_finished(self):
        self._log("===== 종료 =====", "blue")
        self._set_running(False)
        self.header.set_state("stop" if self._worker and self._worker._stop.is_set() else "wait")

    def _on_failed(self, msg: str):
        self._log(f"워커 오류: {msg}", "red")
        self._set_running(False)
        self.header.set_state("err")

    # ── 표·로그 ──
    _COLOR = {"완료": C["green_soft"], "실패": C["red_soft"], "처리중": C["amber_soft"], "제외": "#eef1f4",
              "보류": "#eef1f4", "대기": C["surface"], "후보": C["surface"]}

    def _put_row(self, key, doc: str, bank: str, when, status: str, note: str):
        if key not in self._rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self._rows[key] = row
        row = self._rows[key]
        day = when.strftime("%Y-%m-%d") if when else ""
        tm = when.strftime("%H:%M:%S") if when else ""
        values = [doc, bank or "", day, tm, status, note]
        color = self._COLOR.get(status, C["surface"])
        for col, val in enumerate(values):
            cell = QTableWidgetItem(val)
            cell.setBackground(QColor(color))
            if col == 5:
                cell.setToolTip(val)
            self.table.setItem(row, col, cell)
        self.table.scrollToItem(self.table.item(row, 0))

    def _on_item(self, item: dict):
        import run_queue_worker as W
        note = W.humanize(item.get("msg")) if item["status"] in ("완료", "실패") else (item.get("msg") or "")
        self._put_row(("send", item["seq"]), item["doc"], item["bank"], dt.datetime.now(), item["status"], note)
        if item["status"] == "처리중":
            self.header.set_state("busy")

    def _load_history(self):
        """이력 테이블(Apw_YJI_BankAuto)에서 조회일자 이후 건을 표에 채운다(재시작해도 보이게)."""
        try:
            import run_queue_worker as W
            from bankon.config import load_config
            from bankon.db import connect
            since = self.since.date().toString("yyyy-MM-dd")
            with connect(load_config(None).source_sql, readonly=True) as ro:
                rows = W.history(ro, since)
            for r in rows:
                self._put_row(("send", r["Send_Seq"]), r["Docid"], r["Bank"], r["End_Date"] or r["Start_Date"],
                              r["Status"], W.humanize(r["Msg"]) if r["Status"] in ("완료", "실패") else (r["Msg"] or ""))
            self._log(f"이력 {len(rows)}건 표시 (처리일 ≥ {since})", "muted")
        except Exception as error:  # noqa: BLE001
            self._log(f"이력 조회 실패: {error!r}", "amber")

    def _open_log_file(self):
        LOG_DIR.mkdir(exist_ok=True)
        if self._log_file is None:
            self._log_file = open(LOG_DIR / f"gui_{dt.date.today():%Y%m%d}.log", "a", encoding="utf-8")

    def _log(self, msg: str, color: str = ""):
        stamp = dt.datetime.now().strftime("%H:%M:%S")
        col = {"red": C["red"], "amber": C["amber"], "blue": C["blue"], "muted": C["muted"], "green": C["green"]}.get(color, "#48576a")
        for line in msg.splitlines() or [""]:
            self.log_view.append(f'<span style="color:{C["muted"]}">{stamp}</span> <span style="color:{col}">{line}</span>')
        self.log_view.moveCursor(QTextCursor.MoveOperation.End)
        if self._log_file:
            self._log_file.write(f"[{stamp}] {msg}\n")
            self._log_file.flush()

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            ok = QMessageBox.question(self, "종료", "처리 중입니다. 현재 건을 마친 뒤 멈추고 닫을까요?",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if ok != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._worker.stop()
            self._worker.wait(600_000)
        if self._log_file:
            self._log_file.close()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
