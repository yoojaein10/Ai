"""
Bank24 담보 데이터 추출기 - GUI v0.4
"""
import sys
import configparser
import traceback as _traceback
import re as _re
from datetime import datetime, timedelta
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit,
    QCheckBox, QComboBox, QRadioButton,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QSizePolicy,
)
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QTextCursor

# ── 상수 ─────────────────────────────────────────────────────────
APP_TITLE    = "Bank24 담보 데이터 추출기"
APP_VERSION  = "v0.4"
APP_DIR      = Path(r"C:\Y_KKBankAuto")
OUTPUT_DIR   = APP_DIR / "output"
PDF_DIR      = Path(r"C:\Bank24PDF")
LOG_DIR      = APP_DIR / "logs"
SETTINGS_INI = APP_DIR / "settings.ini"
CRASH_LOG    = LOG_DIR / "crash.log"

TABLE_COLS = ["의뢰번호", "감정서번호", "은행", "BankOnline_In", "처리 결과"]

# ── 색상 (mockup CSS variables) ──────────────────────────────────
C = {
    "bg":           "#f3f5f8",
    "surface":      "#ffffff",
    "surface_soft": "#f8fafc",
    "line":         "#d7dde6",
    "line_strong":  "#b9c3d0",
    "text":         "#202733",
    "muted":        "#687486",
    "blue":         "#1264d8",
    "blue_soft":    "#e9f2ff",
    "green":        "#16864b",
    "green_soft":   "#e8f7ef",
    "amber":        "#a86712",
    "amber_soft":   "#fff4dc",
    "red":          "#c43b3b",
    "red_soft":     "#fff0f0",
}

STYLESHEET = f"""
QMainWindow, QWidget {{
    background-color: {C['bg']};
    color: {C['text']};
    font-family: 'Segoe UI', 'Pretendard', 'Noto Sans KR', '맑은 고딕', sans-serif;
    font-size: 13px;
}}
QLineEdit {{
    background-color: {C['surface']};
    border: 1px solid {C['line_strong']};
    border-radius: 6px;
    padding: 5px 10px;
    color: {C['text']};
    font-size: 13px;
    selection-background-color: {C['blue']};
    min-height: 33px;
}}
QLineEdit:focus {{ border: 1px solid {C['blue']}; }}
QLineEdit:disabled {{ background-color: #eef1f4; color: #9aa4b2; }}
QComboBox {{
    background-color: {C['surface']};
    border: 1px solid {C['line_strong']};
    border-radius: 6px;
    padding: 3px 8px;
    color: {C['text']};
    font-size: 12px;
    min-height: 30px;
}}
QComboBox:focus {{ border: 1px solid {C['blue']}; }}
QComboBox:disabled {{ background-color: #eef1f4; color: #9aa4b2; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {C['muted']};
    margin-right: 5px;
}}
QComboBox QAbstractItemView {{
    background-color: {C['surface']};
    border: 1px solid {C['line']};
    selection-background-color: {C['blue_soft']};
    color: {C['text']};
    padding: 2px;
}}
QPushButton {{
    border-radius: 6px;
    padding: 5px 12px;
    font-size: 13px;
    border: 1px solid {C['line_strong']};
    background-color: {C['surface']};
    color: #344256;
    font-weight: 700;
}}
QPushButton:hover {{ background-color: #f4f6f8; }}
QPushButton:disabled {{ background-color: #eef1f4; color: #9aa4b2; border-color: {C['line']}; }}
QPushButton#btn_run {{
    background-color: {C['green']};
    color: #ffffff;
    border: 1px solid {C['green']};
}}
QPushButton#btn_run:hover {{ background-color: #0e6b39; border-color: #0e6b39; }}
QPushButton#btn_run:disabled {{ background-color: #eef1f4; color: #9aa4b2; border-color: {C['line']}; }}
QCheckBox {{ spacing: 7px; color: #465468; font-size: 12px; font-weight: 600; }}
QCheckBox::indicator {{
    width: 15px; height: 15px;
    border: 1px solid {C['line_strong']};
    border-radius: 3px;
    background: {C['surface']};
}}
QCheckBox::indicator:checked {{
    background-color: {C['blue']};
    border-color: {C['blue']};
}}
QTableWidget {{
    background-color: {C['surface']};
    border: none;
    gridline-color: #eef1f4;
    selection-background-color: {C['blue_soft']};
    selection-color: {C['text']};
    font-size: 12px;
}}
QTableWidget::item {{ padding: 4px 10px; border: none; }}
QHeaderView::section {{
    background-color: #f0f3f7;
    border: none;
    border-bottom: 1px solid {C['line_strong']};
    border-right: 1px solid {C['line']};
    padding: 4px 10px;
    font-weight: 700;
    font-size: 12px;
    color: #465468;
    height: 36px;
}}
QScrollBar:vertical {{
    background: {C['surface_soft']};
    width: 8px;
    border-radius: 4px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {C['line_strong']};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ height: 0; }}
QTextEdit {{
    background-color: #fbfcfd;
    border: none;
    color: #48576a;
    font-family: 'Consolas', '맑은 고딕', monospace;
    font-size: 12px;
    padding: 9px 15px;
}}
"""

_DEFAULT_INI = '[login]\nsave_credentials = true\nbank24_id =\nREDACTED_CONFIGURE_LOCALLY =\n\n[database]\nenabled = true\nserver = 192.0.2.10\nport = 1433\ndatabase = apworksdw\nusername = dh\npassword =\ndriver = ODBC Driver 17 for SQL Server\ntrust_server_certificate = true\ntable = YJI_BankRequest\nreg_lookup_database = apworksdw\nreg_lookup_table = APW_RegHist\n\n[bankonline]\nenabled = true\nendpoint = https://webrest.kapanet.or.kr/WEB_RESTAPI\nmethod = POST\nrequest_format = form\ntimeout_seconds = 10\nsuccess_field = success\nsuccess_value = true\nallow_http = false\ntoken_endpoint = https://authtoken.kapanet.or.kr/AuthServer\nkapa_user_name = 이일우\n\n[options]\nsource_tab = 미접수\n\n[schedule]\nenabled = false\ninterval_minutes = 5\n'


def ensure_app_dirs():
    for d in [APP_DIR, OUTPUT_DIR, LOG_DIR, PDF_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def load_settings() -> configparser.ConfigParser:
    ensure_app_dirs()
    cfg = configparser.ConfigParser()
    if not SETTINGS_INI.exists():
        SETTINGS_INI.write_text(_DEFAULT_INI, encoding="utf-8")
    cfg.read(str(SETTINGS_INI), encoding="utf-8")
    for sec in ("login", "database", "bankonline", "options", "schedule"):
        if not cfg.has_section(sec):
            cfg.add_section(sec)
    return cfg


def save_settings(cfg: configparser.ConfigParser):
    ensure_app_dirs()
    with open(str(SETTINGS_INI), "w", encoding="utf-8") as f:
        cfg.write(f)


# ── 모듈 헬퍼 (MainWindow / write_crash_log / ExtractionWorker보다 위) ─
def _normalize_pdf_dir(path_text: str) -> str:
    """빈 값이면 PDF_DIR 반환; legacy C:\\Bank24Extractor\\{output,pdf}도 보정."""
    path = (path_text or "").strip()
    if not path:
        return str(PDF_DIR)
    try:
        p = Path(path)
        if p.parent == APP_DIR and p.name.lower() in {"output", "pdf"}:
            return str(PDF_DIR)
    except Exception:
        pass
    return path


def _normalize_result_docid(value) -> str:
    """의뢰번호 정규화: 앞 공백·Excel ' 제거, 숫자 변환 금지."""
    text = str(value or "").strip()
    if text.startswith("'"):
        text = text[1:].strip()
    return text


def _sanitize_sensitive_text(value, secrets=()) -> str:
    """인증정보·연결문자열 마스킹."""
    text = str(value or "")
    for secret in secrets:
        secret = str(secret or "")
        if len(secret) >= 3:
            text = text.replace(secret, "***")
    text = _re.sub(
        r"(?i)\b(PWD|PASSWORD|UID|USER ID)\s*=\s*[^;\s]*",
        r"\1=***",
        text,
    )
    safe_lines = []
    for line in text.splitlines():
        upper = line.upper()
        if "DRIVER=" in upper and "SERVER=" in upper:
            safe_lines.append("[보안] DB 연결정보가 포함된 로그를 차단했습니다.")
        else:
            safe_lines.append(line)
    return "\n".join(safe_lines)


# ── crash 로그 ───────────────────────────────────────────────────
def write_crash_log(exc, tb_text: str, secrets=()):
    safe_exc = _sanitize_sensitive_text(str(exc), secrets)
    safe_tb  = _sanitize_sensitive_text(tb_text,  secrets)
    try:
        ensure_app_dirs()
        ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        body = "\n".join([
            f"[crash] {ts}",
            f"예외: {safe_exc}",
            "traceback:",
            safe_tb.rstrip(),
            f"sys.executable: {sys.executable}",
            f"cwd: {Path.cwd()}",
            f"frozen: {getattr(sys, 'frozen', False)}",
            "",
        ])
        with open(CRASH_LOG, "a", encoding="utf-8") as f:
            f.write(body + "\n" + "─" * 64 + "\n")
    except Exception:
        pass


# ── 추출 워커 ────────────────────────────────────────────────────
class ExtractionWorker(QThread):
    log_signal      = pyqtSignal(str)
    step_signal     = pyqtSignal(str, str)
    summary_signal  = pyqtSignal(dict)
    item_signal     = pyqtSignal(dict)
    finished_signal = pyqtSignal(bool)
    error_signal    = pyqtSignal(str)

    def __init__(self, config: dict):
        super().__init__()
        self._config         = config
        self._stop_requested = False

    def request_stop(self):
        self._stop_requested = True

    def run(self):
        try:
            import extract_shinhan as es
            callbacks = {
                "on_log":      lambda msg: self.log_signal.emit(str(msg)),
                "on_step":     lambda name, state: self.step_signal.emit(name, state),
                "on_summary":  lambda d: self.summary_signal.emit(d),
                "on_item":     lambda item: self.item_signal.emit(item),
                "should_stop": lambda: self._stop_requested,
            }
            es.run_extraction(self._config, callbacks)
            self.finished_signal.emit(not self._stop_requested)
        except BaseException as exc:
            tb_text = _traceback.format_exc()
            db_cfg  = self._config.get("database", {}) or {}
            secrets = (
                self._config.get("bank24_id", ""),
                self._config.get('REDACTED_CONFIGURE_LOCALLY', ""),
                db_cfg.get("username", ""),
                db_cfg.get("password", ""),
            )
            safe_exc = _sanitize_sensitive_text(str(exc), secrets)
            safe_tb  = _sanitize_sensitive_text(tb_text,  secrets)
            write_crash_log(safe_exc, safe_tb, secrets=secrets)
            self.error_signal.emit(safe_exc)


# ── 토글 스위치 ──────────────────────────────────────────────────
class ToggleSwitch(QPushButton):
    toggled_state = pyqtSignal(bool)

    _SS_OFF = ("QPushButton { background: #aeb8c5; border: none; border-radius: 11px;"
               " color: white; font-size: 10px; font-weight: 700; }")
    _SS_ON  = ("QPushButton { background: #1264d8; border: none; border-radius: 11px;"
               " color: white; font-size: 10px; font-weight: 700; }")

    def __init__(self):
        super().__init__()
        self._on = False
        self.setFixedSize(44, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self._toggle)
        self._refresh()

    def _toggle(self):
        self._on = not self._on
        self._refresh()
        self.toggled_state.emit(self._on)

    def is_on(self) -> bool:
        return self._on

    def set_on(self, v: bool):
        if self._on != v:
            self._on = v
            self._refresh()

    def _refresh(self):
        self.setStyleSheet(self._SS_ON if self._on else self._SS_OFF)
        self.setText("ON" if self._on else "OFF")


# ── 헤더 위젯 ────────────────────────────────────────────────────
class HeaderWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(56)
        self.setStyleSheet(
            f"background-color: {C['surface']}; border-bottom: 1px solid {C['line']};"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 0, 18, 0)
        lay.setSpacing(11)

        mark = QLabel("◆")
        mark.setStyleSheet(
            f"color: {C['blue']}; font-size: 14px; background: transparent; border: none;"
        )
        lay.addWidget(mark)

        title = QLabel(APP_TITLE)
        title.setStyleSheet(
            f"font-size: 16px; font-weight: 700; color: {C['text']};"
            "background: transparent; border: none;"
        )
        lay.addWidget(title)
        lay.addStretch()

        self._dot  = QLabel("●")
        self._text = QLabel("대기")
        self._dot.setStyleSheet(
            "color: #31506f; font-size: 9px; background: transparent; border: none;"
        )
        self._text.setStyleSheet(
            "color: #31506f; font-size: 12px; font-weight: 700;"
            "background: transparent; border: none;"
        )
        self.badge = QWidget()
        self.badge.setFixedHeight(28)
        self.badge.setStyleSheet(
            "background-color: #edf1f5; border-radius: 14px; border: none;"
        )
        bl = QHBoxLayout(self.badge)
        bl.setContentsMargins(11, 0, 11, 0)
        bl.setSpacing(7)
        bl.addWidget(self._dot)
        bl.addWidget(self._text)
        lay.addWidget(self.badge)

        ver = QLabel(APP_VERSION)
        ver.setStyleSheet(
            f"color: {C['muted']}; font-size: 12px; background: transparent;"
            "border: none; margin-left: 12px;"
        )
        lay.addWidget(ver)

    def set_state(self, state: str):
        _MAP = {
            "wait": ("#edf1f5", "#31506f", "대기"),
            "run":  ("#e8f7ef", "#0e6b39", "실행 중"),
            "done": ("#e8f7ef", "#0e6b39", "완료"),
            "stop": ("#fff4dc", "#a86712", "중단됨"),
            "err":  ("#fff0f0", "#c43b3b", "오류"),
        }
        bg, fg, label = _MAP.get(state, _MAP["wait"])
        self.badge.setStyleSheet(
            f"background-color: {bg}; border-radius: 14px; border: none;"
        )
        dot_ss  = f"color: {fg}; font-size: 9px; background: transparent; border: none;"
        text_ss = (
            f"color: {fg}; font-size: 12px; font-weight: 700;"
            "background: transparent; border: none;"
        )
        self._dot.setStyleSheet(dot_ss)
        self._text.setStyleSheet(text_ss)
        self._text.setText(label)


# ── 메인 윈도우 ──────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1100, 720)
        self.setMinimumSize(1024, 720)
        self.setStyleSheet(STYLESHEET)

        self._running  = False
        self._worker: ExtractionWorker | None = None
        self._run_log_file = None
        self._cfg = load_settings()
        self._schedule_timer = QTimer(self)
        self._schedule_timer.timeout.connect(self._on_schedule_timeout)
        self._next_run_at: datetime | None = None
        self._result_rows_by_docid: dict[str, int] = {}
        self._result_items_by_row:  dict[int, dict] = {}

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.header = HeaderWidget()
        root.addWidget(self.header)

        workspace = QWidget()
        workspace.setStyleSheet(f"background-color: {C['bg']};")
        ws = QHBoxLayout(workspace)
        ws.setContentsMargins(14, 14, 14, 14)
        ws.setSpacing(14)
        ws.addWidget(self._build_left())
        ws.addWidget(self._build_result_panel(), 1)
        root.addWidget(workspace, 1)

        root.addWidget(self._build_log())

        self._apply_settings()
        self._update_schedule_ui()

    # ── 패널 헬퍼 ────────────────────────────────────────────────
    def _panel(self, title: str) -> tuple[QWidget, QVBoxLayout]:
        outer = QWidget()
        outer.setObjectName("panelOuter")
        outer.setStyleSheet(
            f"QWidget#panelOuter {{ background: {C['surface']};"
            f" border: 1px solid {C['line']}; border-radius: 8px; }}"
        )
        ov = QVBoxLayout(outer)
        ov.setContentsMargins(0, 0, 0, 0)
        ov.setSpacing(0)

        hdr = QWidget()
        hdr.setFixedHeight(42)
        hdr.setStyleSheet(
            f"background: transparent; border-bottom: 1px solid {C['line']};"
        )
        hh = QHBoxLayout(hdr)
        hh.setContentsMargins(14, 0, 14, 0)
        t = QLabel(title)
        t.setStyleSheet(
            "font-size: 13px; font-weight: 700; background: transparent; border: none;"
        )
        hh.addWidget(t)
        ov.addWidget(hdr)

        body = QWidget()
        body.setObjectName("panelBody")
        body.setStyleSheet(
            "QWidget#panelBody { background: transparent; }"
        )
        bv = QVBoxLayout(body)
        bv.setContentsMargins(14, 14, 14, 14)
        bv.setSpacing(11)
        ov.addWidget(body)

        return outer, bv

    def _muted(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {C['muted']}; font-size: 12px; font-weight: 600;"
            "background: transparent; border: none;"
        )
        return lbl

    # ── 왼쪽 열 ─────────────────────────────────────────────────
    def _build_left(self) -> QWidget:
        left = QWidget()
        left.setObjectName("leftCol")
        left.setFixedWidth(330)
        left.setStyleSheet(
            "QWidget#leftCol { background: transparent; }"
        )
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(12)

        # 로그인 패널
        login_panel, lb = self._panel("Bank24 로그인")
        lb.setContentsMargins(14, 12, 14, 12)
        lb.setSpacing(6)
        login_panel.setMinimumHeight(225)
        lb.addWidget(self._muted("Bank24 ID"))
        self.edit_id = QLineEdit()
        self.edit_id.setPlaceholderText("아이디 입력")
        lb.addWidget(self.edit_id)
        lb.addWidget(self._muted("Bank24 PW"))
        self.edit_pw = QLineEdit()
        self.edit_pw.setPlaceholderText("비밀번호 입력")
        self.edit_pw.setEchoMode(QLineEdit.EchoMode.Password)
        lb.addWidget(self.edit_pw)
        self.chk_save_cred = QCheckBox("ID/PW 저장")
        self.chk_save_cred.setChecked(True)
        lb.addWidget(self.chk_save_cred)
        lv.addWidget(login_panel)

        # 자동 실행 패널
        sched_panel, sb = self._panel("자동 실행")
        sched_panel.setMinimumHeight(225)

        # switch + interval 행
        top = QWidget()
        top.setObjectName("scheduleTopRow")
        top.setStyleSheet(
            "QWidget#scheduleTopRow { background: transparent; }"
        )
        tl = QHBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(9)
        self.schedule_switch = ToggleSwitch()
        self.schedule_switch.toggled_state.connect(self._on_schedule_toggled)
        tl.addWidget(self.schedule_switch)
        self.lbl_sched_state = QLabel("자동 실행 OFF")
        self.lbl_sched_state.setStyleSheet(
            "font-size: 13px; font-weight: 700; background: transparent; border: none;"
        )
        tl.addWidget(self.lbl_sched_state)
        tl.addStretch()
        int_lbl = QLabel("간격")
        int_lbl.setStyleSheet(
            f"color: {C['muted']}; font-size: 12px; background: transparent; border: none;"
        )
        tl.addWidget(int_lbl)
        self.cmb_interval = QComboBox()
        self.cmb_interval.addItems(["5분", "10분"])
        self.cmb_interval.setFixedWidth(78)
        self.cmb_interval.currentIndexChanged.connect(self._on_interval_changed)
        tl.addWidget(self.cmb_interval)
        sb.addWidget(top)

        # next-run 박스
        nbox = QWidget()
        nbox.setObjectName("nbox")
        nbox.setStyleSheet(
            f"QWidget#nbox {{ background-color: {C['blue_soft']};"
            " border: 1px solid #cddcf0; border-radius: 6px; }"
        )
        nv = QVBoxLayout(nbox)
        nv.setContentsMargins(12, 11, 12, 11)
        nv.setSpacing(5)
        nlbl = QLabel("다음 실행")
        nlbl.setStyleSheet(
            "color: #55708f; font-size: 11px; font-weight: 700;"
            "background: transparent; border: none;"
        )
        nv.addWidget(nlbl)
        nr = QWidget()
        nr.setObjectName("nextRunRow")
        nr.setStyleSheet(
            "QWidget#nextRunRow { background: transparent; }"
        )
        nrl = QHBoxLayout(nr)
        nrl.setContentsMargins(0, 0, 0, 0)
        nrl.setSpacing(10)
        self.lbl_next_run = QLabel("-")
        self.lbl_next_run.setStyleSheet(
            "color: #173f6d; font-size: 18px; font-weight: 700;"
            "background: transparent; border: none;"
        )
        nrl.addWidget(self.lbl_next_run)
        nrl.addStretch()
        self.lbl_last_run = QLabel("마지막 실행 없음")
        self.lbl_last_run.setStyleSheet(
            "color: #55708f; font-size: 12px; background: transparent; border: none;"
        )
        nrl.addWidget(self.lbl_last_run)
        nv.addWidget(nr)
        sb.addWidget(nbox)

        # 대상 탭 선택
        tab_row = QWidget()
        tab_row.setObjectName("tabRow")
        tab_row.setStyleSheet("QWidget#tabRow { background: transparent; }")
        tab_rl = QHBoxLayout(tab_row)
        tab_rl.setContentsMargins(0, 2, 0, 2)
        tab_rl.setSpacing(12)
        tab_rl.addWidget(self._muted("대상 탭"))
        self.radio_mijeopsu = QRadioButton("미접수")
        self.radio_jaksung  = QRadioButton("작성")
        self.radio_mijeopsu.setChecked(True)
        tab_rl.addWidget(self.radio_mijeopsu)
        tab_rl.addWidget(self.radio_jaksung)
        tab_rl.addStretch()
        sb.addWidget(tab_row)
        tab_row.setVisible(False)   # 운영 모드: 대상 탭 선택 UI 숨김

        # 실행 버튼들
        act = QWidget()
        act.setObjectName("actionRow")
        act.setStyleSheet(
            "QWidget#actionRow { background: transparent; }"
        )
        al = QHBoxLayout(act)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(8)
        self.btn_run = QPushButton("▶  즉시 1회 실행")
        self.btn_run.setObjectName("btn_run")
        self.btn_run.setStyleSheet(
            f"""
            QPushButton#btn_run {{
                background-color: {C["green"]};
                color: #ffffff;
                border: 1px solid {C["green"]};
                border-radius: 6px;
                padding: 5px 12px;
                font-size: 13px;
                font-weight: 700;
            }}
            QPushButton#btn_run:hover {{
                background-color: #0e6b39;
                border-color: #0e6b39;
            }}
            QPushButton#btn_run:disabled {{
                background-color: #eef1f4;
                color: #9aa4b2;
                border-color: {C["line"]};
            }}
            """
        )
        self.btn_run.setFixedHeight(42)
        self.btn_run.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_run.clicked.connect(self._on_start)
        al.addWidget(self.btn_run, 1)
        self.btn_pause = QPushButton("■  일시정지")
        self.btn_pause.setObjectName("btn_pause")
        self.btn_pause.setFixedWidth(120)
        self.btn_pause.setFixedHeight(42)
        self.btn_pause.setEnabled(False)
        self.btn_pause.clicked.connect(self._on_stop)
        al.addWidget(self.btn_pause)
        sb.addWidget(act)

        lv.addWidget(sched_panel)
        lv.addStretch()
        return left

    # ── 처리 결과 패널 ───────────────────────────────────────────
    def _build_result_panel(self) -> QWidget:
        outer = QWidget()
        outer.setObjectName("resultOuter")
        outer.setStyleSheet(
            f"QWidget#resultOuter {{ background: {C['surface']};"
            f" border: 1px solid {C['line']}; border-radius: 8px; }}"
        )
        ov = QVBoxLayout(outer)
        ov.setContentsMargins(0, 0, 0, 0)
        ov.setSpacing(0)

        phdr = QWidget()
        phdr.setFixedHeight(42)
        phdr.setStyleSheet(
            f"background: transparent; border-bottom: 1px solid {C['line']};"
        )
        ph = QHBoxLayout(phdr)
        ph.setContentsMargins(14, 0, 14, 0)
        ph.setSpacing(12)
        t = QLabel("처리 결과")
        t.setStyleSheet(
            "font-size: 13px; font-weight: 700; background: transparent; border: none;"
        )
        ph.addWidget(t)
        ph.addStretch()
        note = QLabel("담보 · 당일 · 미접수 · 지원 은행 전체")
        note.setStyleSheet(
            f"color: {C['muted']}; font-size: 11px; background: transparent; border: none;"
        )
        ph.addWidget(note)
        ov.addWidget(phdr)

        self.table = QTableWidget(0, len(TABLE_COLS))
        self.table.setHorizontalHeaderLabels(TABLE_COLS)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hdr.setStretchLastSection(False)
        self.table.setColumnWidth(0, 130)  # 의뢰번호
        self.table.setColumnWidth(1, 120)  # 감정서번호
        hdr.setSectionResizeMode(
            2,
            QHeaderView.ResizeMode.Stretch,
        )  # 은행
        self.table.setColumnWidth(3, 130)  # BankOnline_In
        self.table.setColumnWidth(4, 100)  # 처리 결과
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        ov.addWidget(self.table, 1)

        det = QWidget()
        det.setFixedHeight(54)
        det.setStyleSheet(
            f"background: {C['surface_soft']}; border-top: 1px solid {C['line']};"
        )
        dl = QHBoxLayout(det)
        dl.setContentsMargins(14, 0, 14, 0)
        dl.setSpacing(0)
        strong = QLabel("선택 항목")
        strong.setStyleSheet(
            "color: #344256; font-weight: 700; font-size: 12px;"
            "margin-right: 8px; background: transparent; border: none;"
        )
        dl.addWidget(strong)
        self.lbl_selection_detail = QLabel("행을 선택하면 처리 내용을 표시합니다.")
        self.lbl_selection_detail.setStyleSheet(
            f"color: {C['muted']}; font-size: 12px; background: transparent; border: none;"
        )
        dl.addWidget(self.lbl_selection_detail, 1)
        ov.addWidget(det)

        return outer

    # ── 로그 패널 ────────────────────────────────────────────────
    def _build_log(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(150)
        w.setStyleSheet(
            f"background-color: {C['surface']}; border-top: 1px solid {C['line_strong']};"
        )
        wl = QVBoxLayout(w)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(0)

        toolbar = QWidget()
        toolbar.setFixedHeight(38)
        toolbar.setStyleSheet(
            f"background: {C['surface']}; border-bottom: 1px solid {C['line']};"
        )
        tl = QHBoxLayout(toolbar)
        tl.setContentsMargins(16, 0, 12, 0)
        tl.setSpacing(6)
        hdr_lbl = QLabel("실행 로그")
        hdr_lbl.setStyleSheet(
            f"font-size: 12px; font-weight: 700; color: {C['text']};"
            "background: transparent; border: none;"
        )
        tl.addWidget(hdr_lbl)
        tl.addStretch()
        for label, slot in [("로그 복사", self._copy_log), ("로그 지우기", self._clear_log)]:
            b = QPushButton(label)
            b.setFixedHeight(28)
            b.setFixedWidth(70)
            b.setStyleSheet(
                f"QPushButton {{ height: 28px; padding: 0 10px;"
                f" border: 1px solid {C['line']}; border-radius: 6px;"
                f" background: #fff; color: #465468; font-size: 11px; font-weight: 700; }}"
                "QPushButton:hover { background: #f4f6f8; }"
            )
            b.clicked.connect(slot)
            tl.addWidget(b)
        wl.addWidget(toolbar)

        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        wl.addWidget(self.log_edit, 1)

        self._log("대기 중")
        return w

    # ── 헬퍼 ────────────────────────────────────────────────────
    def _today_str(self) -> str:
        return datetime.today().strftime("%Y-%m-%d")

    def _fixed_run_options(self) -> dict:
        tab_row = self.findChild(QWidget, "tabRow")
        if tab_row is None or not tab_row.isVisible():
            src = "미접수"
        else:
            src = "작성" if getattr(self, "radio_jaksung", None) and self.radio_jaksung.isChecked() else "미접수"
        return {
            "banks":      ["전체"],
            "bank":       "전체",
            "source_tab": src,
            "date_mode":  "today",
            "work_type":  "담보",
        }

    def _sanitize_log_message(self, message: str) -> str:
        return _sanitize_sensitive_text(
            message,
            secrets=(
                self.edit_id.text().strip(),
                self.edit_pw.text(),
                self._cfg.get("database", "username", fallback=""),
                self._cfg.get("database", "password", fallback=""),
            ),
        )

    def _log(self, msg: str, color: str = ""):
        ts   = datetime.now().strftime("%H:%M:%S")
        safe = str(msg).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        cursor = self.log_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.log_edit.setTextCursor(cursor)
        ts_html  = f'<span style="color:#9aa4b2;">[{ts}]</span>'
        fg       = color if color else "#48576a"
        msg_html = f'<span style="color:{fg};">{safe}</span>'
        self.log_edit.insertHtml(f'{ts_html} {msg_html}<br>')
        sb = self.log_edit.verticalScrollBar()
        sb.setValue(sb.maximum())
        if self._run_log_file:
            try:
                self._run_log_file.write(f"[{ts}] {msg}\n")
                self._run_log_file.flush()
            except Exception:
                pass

    def _selected_interval_minutes(self) -> int:
        txt = self.cmb_interval.currentText().replace("분", "").strip()
        try:
            return int(txt)
        except ValueError:
            return 5

    def _schedule_next_label(self):
        if self._next_run_at and self.schedule_switch.is_on():
            self.lbl_next_run.setText(self._next_run_at.strftime("%H:%M"))
        else:
            self.lbl_next_run.setText("-")

    def _reset_ui(self):
        self.table.setRowCount(0)
        self._result_rows_by_docid.clear()
        self._result_items_by_row.clear()
        self.lbl_selection_detail.setText("행을 선택하면 처리 내용을 표시합니다.")
        self.lbl_selection_detail.setToolTip("")
        self.lbl_selection_detail.setStyleSheet(
            f"color: {C['muted']}; font-size: 12px; background: transparent; border: none;"
        )

    def _set_running(self, running: bool):
        self._running = running
        self.btn_run.setEnabled(not running)
        self.btn_pause.setEnabled(running or self.schedule_switch.is_on())
        self.edit_id.setEnabled(not running)
        self.edit_pw.setEnabled(not running)

    # ── 테이블 행 상태 갱신 ─────────────────────────────────────
    def _set_row_status(self, row: int, status: str, error_text: str = "") -> None:
        if row < 0 or row >= self.table.rowCount():
            return
        col = TABLE_COLS.index("처리 결과")
        cell = self.table.item(row, col)
        if cell is None:
            cell = QTableWidgetItem()
            self.table.setItem(row, col, cell)
        _STYLES = {
            "처리 대기": (C["blue"],  C["blue_soft"]),
            "처리 완료": (C["blue"],  C["blue_soft"]),
            "DB 성공":   (C["green"], C["green_soft"]),
            "중복 SKIP": (C["amber"], C["amber_soft"]),
            "저장 제외": (C["red"],   C["red_soft"]),
            "실패":      (C["red"],   C["red_soft"]),
        }
        fg, bg = _STYLES.get(status, (C["text"], C["surface"]))
        cell.setText(status)
        cell.setForeground(QColor(fg))
        cell.setBackground(QColor(bg))
        if error_text:
            self._result_items_by_row.setdefault(row, {})["DB 오류"] = str(error_text)

    # ── 자동 실행 ───────────────────────────────────────────────
    def _update_schedule_ui(self):
        enabled = self.schedule_switch.is_on()
        self.lbl_sched_state.setText("자동 실행 ON" if enabled else "자동 실행 OFF")
        if enabled:
            minutes = self._selected_interval_minutes()
            self._schedule_timer.start(minutes * 60 * 1000)
            self._next_run_at = datetime.now() + timedelta(minutes=minutes)
            self._log(f"[스케줄] 자동 실행 ON: {minutes}분 간격", C['blue'])
        else:
            self._schedule_timer.stop()
            self._next_run_at = None
            self._log("[스케줄] 자동 실행 OFF", C['muted'])
        self._schedule_next_label()
        self.btn_pause.setEnabled(self._running or enabled)

    def _on_schedule_toggled(self, _: bool):
        self._save_settings()
        self._update_schedule_ui()

    def _on_interval_changed(self):
        self._save_settings()
        if self.schedule_switch.is_on():
            self._update_schedule_ui()

    def _on_schedule_timeout(self):
        minutes = self._selected_interval_minutes()
        self._next_run_at = datetime.now() + timedelta(minutes=minutes)
        self._schedule_next_label()
        if self._running:
            self._log("[스케줄] 이전 작업 진행 중 — 이번 실행 스킵", C['amber'])
            return
        self._log("[스케줄] 예약 실행 시작", C['blue'])
        self._start_extraction(schedule_run=True)

    # ── 워커 시그널 핸들러 ───────────────────────────────────────
    def _on_worker_log(self, msg: str):
        self._log(self._sanitize_log_message(msg))

    def _on_worker_step(self, name: str, state: str):
        if state == "error":
            self.header.set_state("err")
        elif state == "stopped":
            self.header.set_state("stop")

    def _on_worker_item(self, item: dict):
        r = self.table.rowCount()
        self.table.insertRow(r)

        docid = _normalize_result_docid(
            item.get("의뢰번호") or item.get("상세창 의뢰번호") or ""
        )
        self._result_items_by_row[r] = dict(item)
        if docid and docid not in self._result_rows_by_docid:
            self._result_rows_by_docid[docid] = r

        status_raw     = str(item.get("처리상태", "") or "").strip()
        failure_reason = str(item.get("실패사유", "") or "").strip()
        if status_raw == "성공" and not failure_reason:
            display_status = "처리 대기"
        else:
            display_status = "저장 제외"

        col_vals = {
            "의뢰번호":      docid,
            "감정서번호":    str(item.get("감정서번호", "") or ""),
            "은행":          str(item.get("은행", "") or ""),
            "BankOnline_In": "",
            "처리 결과":     display_status,
        }
        _STATUS_COLORS = {
            "처리 대기": (C["blue"],  C["blue_soft"]),
            "저장 제외": (C["red"],   C["red_soft"]),
        }
        detail = str(item.get("비고", "") or status_raw)

        for ci, col in enumerate(TABLE_COLS):
            cell = QTableWidgetItem(col_vals.get(col, ""))
            cell.setData(Qt.ItemDataRole.UserRole, detail)
            if col == "처리 결과":
                fg, bg = _STATUS_COLORS.get(display_status, (C["text"], C["surface"]))
                cell.setForeground(QColor(fg))
                cell.setBackground(QColor(bg))
            self.table.setItem(r, ci, cell)

        self.table.scrollToBottom()

    def _on_worker_summary(self, d: dict):
        fname = d.get("file", "")
        if fname:
            self._log(f"저장 완료: {fname}", C['green'])

        db = d.get("db", {}) or {}
        if db.get("enabled"):
            db_ok   = db.get("success", 0)
            db_fail = db.get("fail", 0)
            db_dup  = db.get("duplicate_skipped", 0)
            color   = C['green'] if db_fail == 0 else C['red']
            self._log(
                f"DB insert: 시도={db.get('tried', 0)} 성공={db_ok} 실패={db_fail}"
                + (f" 중복SKIP={db_dup}" if db_dup else ""),
                color,
            )
        # outputs → DB 성공 + NewDocID + BankOnline_In
        gam_col = TABLE_COLS.index("감정서번호")
        bo_col  = TABLE_COLS.index("BankOnline_In")
        for output in db.get("outputs", []) or []:
            docid = _normalize_result_docid(output.get("의뢰번호", ""))
            row   = self._result_rows_by_docid.get(docid)
            if row is not None:
                self._set_row_status(row, "DB 성공")
                new_doc_id = str(output.get("NewDocID", "") or "").strip()
                if new_doc_id:
                    gam_cell = self.table.item(row, gam_col)
                    if gam_cell is None:
                        gam_cell = QTableWidgetItem()
                        self.table.setItem(row, gam_col, gam_cell)
                    gam_cell.setText(new_doc_id)
                bo_value = str(output.get("BankOnline_In", "") or "").strip()
                if bo_value in ("Y", "N"):
                    bo_cell = self.table.item(row, bo_col)
                    if bo_cell is None:
                        bo_cell = QTableWidgetItem()
                        self.table.setItem(row, bo_col, bo_cell)
                    bo_cell.setText(bo_value)
                    if bo_value == "Y":
                        bo_cell.setForeground(QColor(C["green"]))
                    else:
                        bo_cell.setForeground(QColor(C["red"]))

        # errors → 마스킹 후 로그 + 실패 상태
        for error in db.get("errors", []) or []:
            docid      = _normalize_result_docid(error.get("의뢰번호", ""))
            safe_error = self._sanitize_log_message(str(error.get("error", "") or ""))
            if docid:
                self._log(f"  INSERT 실패: {docid} -> {safe_error}", C["red"])
            row = self._result_rows_by_docid.get(docid)
            if row is not None:
                self._set_row_status(row, "실패", safe_error)

        # 처리 대기 → 처리 완료
        status_col = TABLE_COLS.index("처리 결과")
        for row in range(self.table.rowCount()):
            cell = self.table.item(row, status_col)
            if cell and cell.text() == "처리 대기":
                self._set_row_status(row, "처리 완료")

    def _on_worker_finished(self, success: bool):
        self._set_running(False)
        self.lbl_last_run.setText(datetime.now().strftime("마지막 실행 %H:%M"))
        if success:
            self._log("추출 완료", C['green'])
        else:
            self._log("중단됨", C['amber'])
        self._worker = None
        self._close_run_log()
        self.header.set_state("wait")

    def _on_worker_error(self, msg: str):
        self._set_running(False)
        self.header.set_state("err")
        safe_msg   = self._sanitize_log_message(msg)
        first_line = safe_msg.splitlines()[0] if safe_msg.strip() else "알 수 없는 오류"
        self._log(f"[오류] {first_line}", C["red"])
        self._log(f"crash.log 저장: {CRASH_LOG}", C["amber"])
        self._worker = None
        self._close_run_log()

    def _close_run_log(self):
        if self._run_log_file:
            try:
                self._run_log_file.close()
            except Exception:
                pass
            self._run_log_file = None

    # ── 버튼 이벤트 ─────────────────────────────────────────────
    def _on_start(self):
        self._start_extraction(schedule_run=False)

    def _start_extraction(self, schedule_run: bool = False):
        if self._running:
            if schedule_run:
                self._log("[스케줄] 이전 작업 진행 중 — 이번 실행 스킵", C['amber'])
            return

        uid = self.edit_id.text().strip()
        pwd = self.edit_pw.text()
        if not uid:
            self._log("[경고] ID가 비어 있습니다.", C['red']); return
        if not pwd:
            self._log("[경고] PW가 비어 있습니다.", C['red']); return

        self._save_settings()
        opts  = self._fixed_run_options()
        today = self._today_str()
        cfg   = self._cfg

        pdf_dir = str(PDF_DIR)

        db_cfg = {
            "enabled":                  True,
            "server":                   cfg.get("database", "server",   fallback='192.0.2.10'),
            "port":                     cfg.get("database", "port",     fallback="1433"),
            "database":                 cfg.get("database", "database", fallback="apworksdw"),
            "username":                 cfg.get("database", "username", fallback="dh"),
            "password":                 cfg.get("database", "password", fallback=""),
            "driver":                   cfg.get("database", "driver",   fallback="ODBC Driver 17 for SQL Server"),
            "trust_server_certificate": cfg.getboolean("database", "trust_server_certificate", fallback=True),
            "table":                    cfg.get("database", "table",               fallback="YJI_BankRequest"),
            "reg_lookup_database":      cfg.get("database", "reg_lookup_database", fallback="apworksdw"),
            "reg_lookup_table":         cfg.get("database", "reg_lookup_table",    fallback="APW_RegHist"),
        }
        bankonline_cfg = {
            "enabled":         cfg.getboolean("bankonline", "enabled", fallback=False),
            "endpoint":        cfg.get("bankonline", "endpoint", fallback="https://webrest.kapanet.or.kr/WEB_RESTAPI").strip(),
            "method":          cfg.get("bankonline", "method", fallback="POST").strip(),
            "request_format":  cfg.get("bankonline", "request_format", fallback="form").strip(),
            "timeout_seconds": cfg.get("bankonline", "timeout_seconds", fallback="10").strip(),
            "success_field":   cfg.get("bankonline", "success_field", fallback="success").strip(),
            "success_value":   cfg.get("bankonline", "success_value", fallback="true").strip(),
            "allow_http":      cfg.getboolean("bankonline", "allow_http", fallback=False),
            "token_endpoint":  cfg.get("bankonline", "token_endpoint", fallback="https://authtoken.kapanet.or.kr/AuthServer").strip(),
            "kapa_user_name":  cfg.get("bankonline", "kapa_user_name", fallback="이일우").strip(),
        }

        config = {
            "bank24_id":             uid,
            'REDACTED_CONFIGURE_LOCALLY':             pwd,
            "date_mode":             opts["date_mode"],
            "date_from":             today,
            "date_to":               today,
            "banks":                 opts["banks"],
            "bank":                  opts["bank"],
            "work_type":             opts["work_type"],
            "output_dir":            pdf_dir,
            "save_txt":              True,
            "db_insert":             True,
            "database":              db_cfg,
            "bankonline":            bankonline_cfg,
            "restart":               False,
            "auto_launch_if_closed": True,
            "pdf_enabled":           True,
            "pdf_dir":               pdf_dir,
            "source_tab":            opts["source_tab"],
        }

        self._reset_ui()
        self._set_running(True)
        self.header.set_state("run")

        try:
            ensure_app_dirs()
            log_fname = LOG_DIR / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
            self._run_log_file = open(log_fname, "w", encoding="utf-8")
        except Exception:
            self._run_log_file = None

        self._log("예약 실행 시작" if schedule_run else "즉시 실행 시작", C['blue'])
        self._log(f"담보 · {today} · {opts['source_tab']} · 지원 은행 전체", C['muted'])

        self._worker = ExtractionWorker(config)
        self._worker.log_signal.connect(self._on_worker_log)
        self._worker.step_signal.connect(self._on_worker_step)
        self._worker.summary_signal.connect(self._on_worker_summary)
        self._worker.item_signal.connect(self._on_worker_item)
        self._worker.finished_signal.connect(self._on_worker_finished)
        self._worker.error_signal.connect(self._on_worker_error)
        self._worker.start()

    def _on_stop(self):
        if self.schedule_switch.is_on():
            self.schedule_switch.set_on(False)
            self._update_schedule_ui()
            self._log("[스케줄] 일시정지", C['amber'])
        if self._running and self._worker is not None:
            self._worker.request_stop()
            self.btn_pause.setEnabled(False)
            self._log("중지 요청됨 — 현재 단계 완료 후 중단합니다.", C['amber'])

    def _on_row_selected(self):
        row = self.table.currentRow()
        if row < 0:
            return
        item   = self._result_items_by_row.get(row, {})
        detail = str(
            item.get("실패사유")
            or item.get("DB 오류")
            or item.get("비고")
            or item.get("처리상태")
            or "처리 내용이 없습니다."
        )
        detail  = self._sanitize_log_message(detail)
        preview = detail[:200] + ("…" if len(detail) > 200 else "")
        self.lbl_selection_detail.setText(preview or "(처리 정보 없음)")
        self.lbl_selection_detail.setToolTip(detail)
        self.lbl_selection_detail.setStyleSheet(
            f"color: {C['text']}; font-size: 12px; background: transparent; border: none;"
        )

    def _copy_log(self):
        QApplication.clipboard().setText(self.log_edit.toPlainText())
        self._log("로그 복사됨", C['blue'])

    def _clear_log(self):
        self.log_edit.clear()

    # ── 설정 관리 ────────────────────────────────────────────────
    def _apply_settings(self):
        cfg = self._cfg
        save_cred = cfg.getboolean("login", "save_credentials", fallback=True)
        self.chk_save_cred.setChecked(save_cred)
        if save_cred:
            self.edit_id.setText(cfg.get("login", "bank24_id", fallback=""))
            self.edit_pw.setText(cfg.get("login", 'REDACTED_CONFIGURE_LOCALLY', fallback=""))
        interval_raw = cfg.get("schedule", "interval_minutes", fallback="5")
        idx = self.cmb_interval.findText(f"{interval_raw}분")
        if idx >= 0:
            self.cmb_interval.setCurrentIndex(idx)
        # else: 기존 설정값 30/60분이면 기본값 0(5분) 유지
        self.schedule_switch.set_on(
            cfg.getboolean("schedule", "enabled", fallback=False)
        )
        src_tab = cfg.get("options", "source_tab", fallback="미접수").strip()
        if src_tab == "작성":
            self.radio_jaksung.setChecked(True)
        else:
            self.radio_mijeopsu.setChecked(True)

    def _save_settings(self):
        cfg = self._cfg
        if not cfg.has_section("login"):
            cfg.add_section("login")
        if not cfg.has_section("schedule"):
            cfg.add_section("schedule")
        save_cred = self.chk_save_cred.isChecked()
        cfg.set("login", "save_credentials", "true" if save_cred else "false")
        cfg.set("login", "bank24_id", self.edit_id.text().strip() if save_cred else "")
        cfg.set("login", 'REDACTED_CONFIGURE_LOCALLY', self.edit_pw.text()         if save_cred else "")
        cfg.set("schedule", "enabled",
                "true" if self.schedule_switch.is_on() else "false")
        cfg.set("schedule", "interval_minutes",
                str(self._selected_interval_minutes()))
        if not cfg.has_section("options"):
            cfg.add_section("options")
        _tab_row = self.findChild(QWidget, "tabRow")
        _tab_hidden = (_tab_row is None or not _tab_row.isVisible())
        cfg.set("options", "source_tab",
                "미접수" if _tab_hidden else ("작성" if self.radio_jaksung.isChecked() else "미접수"))
        save_settings(cfg)

    def closeEvent(self, event):
        self._save_settings()
        super().closeEvent(event)


# ── 진입점 ───────────────────────────────────────────────────────
def main():
    ensure_app_dirs()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
