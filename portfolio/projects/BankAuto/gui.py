"""
Bank24 자동화 제어 센터 - PyQt6 Modern Dark UI
"""
import sys
import json
import threading
import traceback
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QLineEdit, QPushButton, QTextEdit,
    QGroupBox, QDateEdit, QComboBox, QFrame, QSplitter,
    QSystemTrayIcon, QMenu, QSizePolicy, QScrollArea,
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QDate, QSize, QTimer,
)
from PyQt6.QtGui import (
    QFont, QColor, QTextCursor, QIcon, QPalette, QAction,
)

CONFIG_PATH = "config.json"

# ─── 색상 팔레트 ──────────────────────────────────────────────────────────────
COLORS = {
    "bg":        "#1a1a2e",
    "surface":   "#16213e",
    "surface2":  "#0f3460",
    "accent":    "#e94560",
    "accent2":   "#00b4d8",
    "success":   "#06d6a0",
    "warning":   "#ffd166",
    "error":     "#ef476f",
    "text":      "#eaeaea",
    "text_dim":  "#8892a4",
    "border":    "#2d3561",
}

STYLESHEET = f"""
QMainWindow, QWidget {{
    background-color: {COLORS['bg']};
    color: {COLORS['text']};
    font-family: 'Segoe UI', sans-serif;
    font-size: 13px;
}}
QGroupBox {{
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    margin-top: 14px;
    padding: 10px;
    font-weight: bold;
    color: {COLORS['accent2']};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}}
QLineEdit {{
    background-color: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    padding: 6px 10px;
    color: {COLORS['text']};
    selection-background-color: {COLORS['accent']};
}}
QLineEdit:focus {{
    border: 1px solid {COLORS['accent2']};
}}
QDateEdit {{
    background-color: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    padding: 5px 10px;
    color: {COLORS['text']};
}}
QDateEdit::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox {{
    background-color: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    padding: 5px 10px;
    color: {COLORS['text']};
}}
QComboBox::drop-down {{ border: none; }}
QComboBox QAbstractItemView {{
    background-color: {COLORS['surface2']};
    color: {COLORS['text']};
    selection-background-color: {COLORS['accent']};
}}
QTextEdit {{
    background-color: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    padding: 8px;
    color: {COLORS['text']};
    font-family: 'Consolas', 'D2Coding', monospace;
    font-size: 12px;
}}
QPushButton {{
    border-radius: 8px;
    padding: 9px 20px;
    font-weight: bold;
    font-size: 13px;
    border: none;
}}
QPushButton#btn_start {{
    background-color: {COLORS['success']};
    color: #000;
}}
QPushButton#btn_start:hover {{ background-color: #04c48e; }}
QPushButton#btn_start:disabled {{ background-color: #3a4a44; color: #666; }}
QPushButton#btn_stop {{
    background-color: {COLORS['error']};
    color: #fff;
}}
QPushButton#btn_stop:hover {{ background-color: #d63060; }}
QPushButton#btn_stop:disabled {{ background-color: #4a2030; color: #666; }}
QPushButton#btn_save {{
    background-color: {COLORS['surface2']};
    color: {COLORS['text']};
    border: 1px solid {COLORS['border']};
}}
QPushButton#btn_save:hover {{ background-color: {COLORS['accent2']}; color: #000; }}
QLabel#stage_label {{
    font-size: 12px;
    padding: 4px 12px;
    border-radius: 12px;
    font-weight: bold;
}}
QSplitter::handle {{
    background-color: {COLORS['border']};
    width: 2px;
}}
QScrollBar:vertical {{
    background: {COLORS['surface']};
    width: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: {COLORS['border']};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
"""


# ─── 자동화 워커 스레드 ───────────────────────────────────────────────────────
class AutoWorker(QThread):
    log_signal    = pyqtSignal(str, str)   # (message, level)
    stage_signal  = pyqtSignal(str)        # stage name
    done_signal   = pyqtSignal(bool)       # success/fail

    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg
        self._stop_flag = False

    def stop(self):
        self._stop_flag = True

    def run(self):
        try:
            from bank24_auto import Bank24App, SearchFilter, DataCollector, DataSink

            self.log_signal.emit("자동화 시작", "info")

            # 로그인
            self.stage_signal.emit("로그인 중")
            app_obj = Bank24App(self.cfg)
            app_obj.launch()
            if self._stop_flag: return
            self.log_signal.emit("로그인 완료", "success")

            # 필터
            self.stage_signal.emit("검색 필터 설정")
            SearchFilter(app_obj).apply()
            if self._stop_flag: return
            self.log_signal.emit("검색 필터 적용 완료", "success")

            # 그리드 데이터 로드
            self.stage_signal.emit("데이터 수집 중")
            collector = DataCollector(app_obj, self.cfg)
            if self._stop_flag: return

            # 의뢰서 출력 → PDF 파싱 → MSSQL 저장
            self.stage_signal.emit("의뢰서 수집 중")
            if self._stop_flag: return
            collector.collect_and_upsert_pdfs()
            self.log_signal.emit("의뢰서 수집 완료", "success")

            self.stage_signal.emit("완료")
            self.done_signal.emit(True)

        except Exception as e:
            self.log_signal.emit(f"오류: {e}\n{traceback.format_exc()}", "error")
            self.stage_signal.emit("오류")
            self.done_signal.emit(False)


# ─── 상태 배지 ────────────────────────────────────────────────────────────────
class StageBadge(QLabel):
    STAGE_COLORS = {
        "대기":       ("#8892a4", "#1a1a2e"),
        "로그인 중":  ("#ffd166", "#2a2010"),
        "검색 필터 설정": ("#00b4d8", "#0a2030"),
        "데이터 수집 중": ("#e94560", "#2a0a10"),
        "저장 중":    ("#00b4d8", "#0a2030"),
        "완료":       ("#06d6a0", "#0a2a20"),
        "오류":       ("#ef476f", "#3a0a10"),
        "중단됨":     ("#8892a4", "#1a1a2e"),
    }

    def __init__(self):
        super().__init__("● 대기")
        self.setObjectName("stage_label")
        self.set_stage("대기")

    def set_stage(self, stage: str):
        fg, bg = self.STAGE_COLORS.get(stage, ("#eaeaea", "#1a1a2e"))
        self.setText(f"● {stage}")
        self.setStyleSheet(
            f"color: {fg}; background-color: {bg}; "
            f"padding: 4px 14px; border-radius: 12px; font-weight: bold; font-size: 12px;"
        )


# ─── 로그 창 ──────────────────────────────────────────────────────────────────
class LogView(QTextEdit):
    LEVEL_COLORS = {
        "info":    COLORS["text"],
        "success": COLORS["success"],
        "warning": COLORS["warning"],
        "error":   COLORS["error"],
    }

    def __init__(self):
        super().__init__()
        self.setReadOnly(True)

    def append_log(self, msg: str, level: str = "info"):
        ts = datetime.now().strftime("%H:%M:%S")
        color = self.LEVEL_COLORS.get(level, COLORS["text"])
        icon = {"info": "ℹ", "success": "✔", "warning": "⚠", "error": "✖"}.get(level, "•")
        html = (
            f'<span style="color:{COLORS["text_dim"]}">[{ts}]</span> '
            f'<span style="color:{color}">{icon} {msg.replace(chr(10), "<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;")}</span>'
        )
        self.append(html)
        self.moveCursor(QTextCursor.MoveOperation.End)


# ─── 설정 패널 ────────────────────────────────────────────────────────────────
class ConfigPanel(QScrollArea):
    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet("QScrollArea { border: none; }")
        inner = QWidget()
        self.setWidget(inner)
        self._build(inner)

    def _build(self, parent=None):
        layout = QVBoxLayout(parent or self)
        layout.setSpacing(10)
        layout.setContentsMargins(4, 4, 4, 4)

        # 로그인
        login_box = QGroupBox("로그인 정보")
        lg = QGridLayout(login_box)
        self.id_edit = QLineEdit(); self.id_edit.setPlaceholderText("사용자 ID")
        self.pw_edit = QLineEdit(); self.pw_edit.setPlaceholderText("비밀번호")
        self.pw_edit.setEchoMode(QLineEdit.EchoMode.Password)
        lg.addWidget(QLabel("ID"), 0, 0); lg.addWidget(self.id_edit, 0, 1)
        lg.addWidget(QLabel("PW"), 1, 0); lg.addWidget(self.pw_edit, 1, 1)
        layout.addWidget(login_box)

        # 검색
        search_box = QGroupBox("검색 조건")
        sg = QGridLayout(search_box)
        self.type_combo = QComboBox()
        self.type_combo.addItems(["담보", "탁상", "전체"])
        today = QDate.currentDate()
        self.date_from = QDateEdit(today); self.date_from.setCalendarPopup(True)
        self.date_to   = QDateEdit(today); self.date_to.setCalendarPopup(True)
        self.date_from.setDisplayFormat("yyyy-MM-dd")
        self.date_to.setDisplayFormat("yyyy-MM-dd")
        self.excel_reason = QLineEdit(".")
        sg.addWidget(QLabel("유형"),     0, 0); sg.addWidget(self.type_combo,   0, 1)
        sg.addWidget(QLabel("시작일"),   1, 0); sg.addWidget(self.date_from,    1, 1)
        sg.addWidget(QLabel("종료일"),   2, 0); sg.addWidget(self.date_to,      2, 1)
        sg.addWidget(QLabel("변환사유"), 3, 0); sg.addWidget(self.excel_reason, 3, 1)
        layout.addWidget(search_box)

        # MSSQL
        db_box = QGroupBox("MSSQL 연결")
        dg = QGridLayout(db_box)
        self.db_server = QLineEdit(); self.db_server.setPlaceholderText("서버\\인스턴스")
        self.db_name   = QLineEdit(); self.db_name.setPlaceholderText("데이터베이스명")
        self.db_user   = QLineEdit(); self.db_user.setPlaceholderText("사용자명")
        self.db_pw     = QLineEdit(); self.db_pw.setPlaceholderText("비밀번호")
        self.db_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.db_table  = QLineEdit("Bank24Data")
        for i, (lbl, w) in enumerate([
            ("서버", self.db_server), ("DB", self.db_name),
            ("계정", self.db_user),  ("PW", self.db_pw),
            ("테이블", self.db_table),
        ]):
            dg.addWidget(QLabel(lbl), i, 0); dg.addWidget(w, i, 1)
        layout.addWidget(db_box)

        # 저장 버튼
        btn_save = QPushButton("💾  설정 저장")
        btn_save.setObjectName("btn_save")
        btn_save.clicked.connect(self.save_config)
        layout.addWidget(btn_save)
        layout.addStretch()

    def load_config(self, cfg: dict):
        self._current_cfg = cfg  # 원본 보존 (output_dir 등 GUI 없는 값)
        self.id_edit.setText(cfg.get("login", {}).get("id", ""))
        self.pw_edit.setText(cfg.get("login", {}).get("pw", ""))
        self.type_combo.setCurrentText(cfg.get("search", {}).get("type", "담보"))
        df = cfg.get("search", {}).get("date_from", "")
        dt = cfg.get("search", {}).get("date_to", "")
        if df: self.date_from.setDate(QDate.fromString(df, "yyyyMMdd"))
        if dt: self.date_to.setDate(QDate.fromString(dt, "yyyyMMdd"))
        self.excel_reason.setText(cfg.get("search", {}).get("excel_reason", "자동수집"))
        m = cfg.get("mssql", {})
        self.db_server.setText(m.get("server", ""))
        self.db_name.setText(m.get("database", ""))
        self.db_user.setText(m.get("username", ""))
        self.db_pw.setText(m.get("password", ""))
        self.db_table.setText(m.get("table", "Bank24Data"))

    def to_config(self) -> dict:
        base = getattr(self, "_current_cfg", {})
        return {
            "app_path":   base.get("app_path", "C:\\KADC\\X11\\bank24.exe"),
            "output_dir": base.get("output_dir", "D:\\AI\\Claude\\BankAuto\\output"),
            "login": {
                "id": self.id_edit.text(),
                "pw": self.pw_edit.text(),
            },
            "search": {
                "type":         self.type_combo.currentText(),
                "date_from":    self.date_from.date().toString("yyyyMMdd"),
                "date_to":      self.date_to.date().toString("yyyyMMdd"),
                "excel_reason": self.excel_reason.text(),
            },
            "mssql": {
                "server":   self.db_server.text(),
                "database": self.db_name.text(),
                "username": self.db_user.text(),
                "password": self.db_pw.text(),
                "table":    self.db_table.text(),
            },
        }

    def save_config(self):
        cfg = self.to_config()
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)


# ─── 메인 윈도우 ──────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.worker: AutoWorker | None = None
        self._setup_tray()
        self._build_ui()
        self._load_config()

    # ── 트레이 ────────────────────────────────────────────────────────────────
    def _setup_tray(self):
        self.tray = QSystemTrayIcon(self)
        self.tray.setToolTip("Bank24 자동화")
        menu = QMenu()
        act_show = QAction("창 보기", self); act_show.triggered.connect(self.show)
        act_quit = QAction("종료",   self); act_quit.triggered.connect(QApplication.quit)
        menu.addAction(act_show); menu.addAction(act_quit)
        self.tray.setContextMenu(menu)
        self.tray.show()

    def _notify(self, title: str, msg: str):
        self.tray.showMessage(title, msg, QSystemTrayIcon.MessageIcon.Information, 4000)

    # ── UI 구성 ───────────────────────────────────────────────────────────────
    def _build_ui(self):
        self.setWindowTitle("Bank24 자동화 제어 센터")
        self.resize(1100, 700)
        self.setMinimumSize(800, 500)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # 헤더
        root.addWidget(self._build_header())

        # 본문 (설정 | 로그)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.config_panel = ConfigPanel()
        self.config_panel.setFixedWidth(320)
        splitter.addWidget(self.config_panel)
        splitter.addWidget(self._build_log_panel())
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

        # 하단 컨트롤
        root.addWidget(self._build_controls())

    def _build_header(self) -> QWidget:
        w = QFrame()
        w.setStyleSheet(
            f"background-color: {COLORS['surface']}; border-radius: 10px;"
            f"border: 1px solid {COLORS['border']};"
        )
        h = QHBoxLayout(w)
        h.setContentsMargins(16, 10, 16, 10)

        title = QLabel("🏦  Bank24 자동화 제어 센터")
        title.setStyleSheet(f"font-size: 17px; font-weight: bold; color: {COLORS['text']}; border: none;")
        h.addWidget(title)
        h.addStretch()

        self.stage_badge = StageBadge()
        h.addWidget(self.stage_badge)
        return w

    def _build_log_panel(self) -> QWidget:
        box = QGroupBox("📋  실시간 로그")
        v = QVBoxLayout(box)
        self.log_view = LogView()
        v.addWidget(self.log_view)

        btn_clear = QPushButton("로그 지우기")
        btn_clear.setObjectName("btn_save")
        btn_clear.setFixedHeight(28)
        btn_clear.clicked.connect(self.log_view.clear)
        v.addWidget(btn_clear, alignment=Qt.AlignmentFlag.AlignRight)
        return box

    def _build_controls(self) -> QWidget:
        w = QFrame()
        w.setStyleSheet(
            f"background-color: {COLORS['surface']}; border-radius: 10px;"
            f"border: 1px solid {COLORS['border']};"
        )
        h = QHBoxLayout(w)
        h.setContentsMargins(16, 10, 16, 10)
        h.setSpacing(12)

        self.btn_start = QPushButton("▶  수집 시작")
        self.btn_start.setObjectName("btn_start")
        self.btn_start.setFixedHeight(42)
        self.btn_start.clicked.connect(self.start_automation)

        self.btn_stop = QPushButton("■  강제 종료")
        self.btn_stop.setObjectName("btn_stop")
        self.btn_stop.setFixedHeight(42)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_automation)

        h.addWidget(self.btn_start)
        h.addWidget(self.btn_stop)
        h.addStretch()
        return w

    # ── 설정 로드 ─────────────────────────────────────────────────────────────
    def _load_config(self):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg = json.load(f)
            self.config_panel.load_config(cfg)
        except Exception:
            pass

    # ── 자동화 제어 ───────────────────────────────────────────────────────────
    def start_automation(self):
        self.config_panel.save_config()
        cfg = self.config_panel.to_config()
        self.log_view.clear()
        self.log_view.append_log("수집 시작", "info")

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)

        self.worker = AutoWorker(cfg)
        self.worker.log_signal.connect(self.log_view.append_log)
        self.worker.stage_signal.connect(self.stage_badge.set_stage)
        self.worker.done_signal.connect(self._on_done)
        self.worker.start()

    def stop_automation(self):
        if self.worker:
            self.worker.stop()
            self.log_view.append_log("강제 종료 요청", "warning")
            self.stage_badge.set_stage("중단됨")
        self._reset_buttons()

    def _on_done(self, success: bool):
        self._reset_buttons()
        if success:
            self.log_view.append_log("모든 작업 완료!", "success")
            self._notify("Bank24 자동화", "데이터 수집이 완료되었습니다.")
        else:
            self.log_view.append_log("작업 중 오류 발생", "error")
            self._notify("Bank24 자동화", "오류가 발생했습니다. 로그를 확인하세요.")

    def _reset_buttons(self):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
        event.accept()


# ─── 진입점 ───────────────────────────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLESHEET)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
