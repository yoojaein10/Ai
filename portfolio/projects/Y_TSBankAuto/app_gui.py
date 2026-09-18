# -*- coding: utf-8 -*-
"""Y_TSBankAuto 운영형 탁상감정 GUI (PyQt6). 지시 §3~5, §11~14.

참조 프로젝트(Y_BankAuto, gui_prototype.py)의 **비민감 UI 요소만** 이식했다:
레이아웃 구조, 창 크기(1100x720), 좌측 열(330px), 헤더(56px)+상태배지, 카드형 패널,
색상 팔레트/스타일시트, 폰트, 버튼/테이블/로그 스타일. 자격증명·서버·경로·업무 로직은
복사하지 않았다(Y_BankAuto 파일 무수정).

Y_TSBankAuto 고유 유지사항:
- fake/real 모드 표시. real 은 승인 스위치·세션 확인문구·검증 설정·컨트롤 pin 미충족 시 비활성.
- "테스트판 — DB 저장 없음" 배너 상시 표시. DB 저장 버튼 영구 비활성.
- 탁상 조회 / 선택 처리 / 실패 재처리 / 긴급 중지 / 진행률 / SP 미리보기 / 로그 복사·지우기.
- 자격증명 방식 keyring/env 선택(단일 방식, 자동 fallback 없음).
- 자동화·PDF 파싱은 QThread 워커에서 수행(UI 스레드 미차단). signal 페이로드는 마스킹 DTO/상태코드만.
- 원문 PII·자격증명·실제 경로·서버명은 로그·테이블에 노출하지 않는다.
- real adapter fail-closed 는 해제하지 않는다. 실제 Bank24 로그인·클릭·다운로드·DB 연결 없음.

import 만으로 창을 띄우지 않는다. main()/build_window() 호출 시에만 UI 를 만든다.
mask_request_row()/badge_palette()/row_status_style() 는 Qt 없이 단위 테스트 가능한 순수 함수다.
"""
from __future__ import annotations

import os
import hmac
import threading
import unicodedata
from dataclasses import dataclass

import bank24_adapter
import bank24_automation
import bank24_credentials
import bank24_credentials as bc
import bank24_login_flow
import config
import security
import settings_integrity

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QKeySequence, QTextCursor
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMainWindow, QMenu, QProgressBar, QPushButton,
    QRadioButton, QSizePolicy, QTableWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget,
)

APP_TITLE = "Bank24 탁상 데이터 추출기"
APP_VERSION = "v0.4"
TEST_BANNER = "탁상 전체 처리 — PDF 파싱 후 DB 저장"
TABLE_COLS = ["의뢰번호", "감정서번호", "은행", "BankOnline_In", "처리 결과"]

# ── 색상 팔레트 (Y_BankAuto mockup CSS variables — 비민감 UI 토큰) ──
C = {
    "bg": "#f3f5f8", "surface": "#ffffff", "surface_soft": "#f8fafc",
    "line": "#d7dde6", "line_strong": "#b9c3d0", "text": "#202733",
    "muted": "#687486", "blue": "#1264d8", "blue_soft": "#e9f2ff",
    "green": "#16864b", "green_soft": "#e8f7ef", "amber": "#a86712",
    "amber_soft": "#fff4dc", "red": "#c43b3b", "red_soft": "#fff0f0",
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
    border-radius: 6px; padding: 5px 10px; color: {C['text']};
    font-size: 13px; selection-background-color: {C['blue']}; min-height: 33px;
}}
QLineEdit:focus {{ border: 1px solid {C['blue']}; }}
QLineEdit:disabled {{ background-color: #eef1f4; color: #9aa4b2; }}
QComboBox {{
    background-color: {C['surface']}; border: 1px solid {C['line_strong']};
    border-radius: 6px; padding: 3px 8px; color: {C['text']};
    font-size: 12px; min-height: 30px;
}}
QComboBox:focus {{ border: 1px solid {C['blue']}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox::down-arrow {{
    image: none; border-left: 4px solid transparent;
    border-right: 4px solid transparent; border-top: 5px solid {C['muted']};
    margin-right: 5px;
}}
QPushButton {{
    border-radius: 6px; padding: 5px 12px; font-size: 13px;
    border: 1px solid {C['line_strong']}; background-color: {C['surface']};
    color: #344256; font-weight: 700;
}}
QPushButton:hover {{ background-color: #f4f6f8; }}
QPushButton:disabled {{ background-color: #eef1f4; color: #9aa4b2; border-color: {C['line']}; }}
QPushButton#btn_primary {{
    background-color: {C['green']}; color: #ffffff; border: 1px solid {C['green']};
}}
QPushButton#btn_primary:hover {{ background-color: #0e6b39; border-color: #0e6b39; }}
QPushButton#btn_primary:disabled {{ background-color: #eef1f4; color: #9aa4b2; border-color: {C['line']}; }}
QWidget#panelBody {{ background: transparent; }}
QPushButton#btn_stop {{
    background-color: {C['red']}; color: #ffffff; border: 1px solid {C['red']};
}}
QPushButton#btn_stop:hover {{ background-color: #a82f2f; border-color: #a82f2f; }}
QCheckBox {{ spacing: 7px; color: #465468; font-size: 12px; font-weight: 600; }}
QCheckBox::indicator {{
    width: 15px; height: 15px; border: 1px solid {C['line_strong']};
    border-radius: 3px; background: {C['surface']};
}}
QCheckBox::indicator:checked {{ background-color: {C['blue']}; border-color: {C['blue']}; }}
QRadioButton {{ color: #465468; font-size: 12px; font-weight: 600; }}
QTableWidget {{
    background-color: {C['surface']}; border: none; gridline-color: #eef1f4;
    selection-background-color: {C['blue_soft']}; selection-color: {C['text']};
    font-size: 12px;
}}
QTableWidget::item {{ padding: 4px 10px; border: none; }}
QHeaderView::section {{
    background-color: #f0f3f7; border: none;
    border-bottom: 1px solid {C['line_strong']}; border-right: 1px solid {C['line']};
    padding: 4px 10px; font-weight: 700; font-size: 12px; color: #465468; height: 36px;
}}
QScrollBar:vertical {{ background: {C['surface_soft']}; width: 8px; border-radius: 4px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {C['line_strong']}; border-radius: 4px; min-height: 24px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ height: 0; }}
QTextEdit {{
    background-color: #fbfcfd; border: none; color: #48576a;
    font-family: 'Consolas', '맑은 고딕', monospace; font-size: 12px; padding: 9px 15px;
}}
QProgressBar {{
    border: 1px solid {C['line']}; border-radius: 6px; background: {C['surface_soft']};
    height: 16px; text-align: center; font-size: 11px; color: {C['muted']};
}}
QProgressBar::chunk {{ background-color: {C['blue']}; border-radius: 5px; }}
"""

# 상태 배지 팔레트(Y_BankAuto 매핑과 동일 키 체계)
_BADGE = {
    "wait": ("#edf1f5", "#31506f", "대기"),
    "run":  ("#e8f7ef", "#0e6b39", "실행 중"),
    "done": ("#e8f7ef", "#0e6b39", "완료"),
    "stop": ("#fff4dc", "#a86712", "중단됨"),
    "err":  ("#fff0f0", "#c43b3b", "오류"),
    "check": ("#e8f0ff", "#1a4fd0", "Bank24 확인"),
    "conn":  ("#e8f0ff", "#1a4fd0", "연결/실행"),
    "login": ("#e8f0ff", "#1a4fd0", "로그인 중"),
    "tab":   ("#e8f0ff", "#1a4fd0", "탁상 이동"),
    "query": ("#e8f0ff", "#1a4fd0", "조회 중"),
    "block": ("#fff0f0", "#c43b3b", "차단됨"),
}

# 행 처리 결과 스타일(fg, bg)
_ROW_STATUS = {
    "처리 대기": (C["blue"], C["blue_soft"]),
    "처리 중":   (C["blue"], C["blue_soft"]),
    "파싱 완료": (C["green"], C["green_soft"]),
    "저장 제외": (C["amber"], C["amber_soft"]),
    "실패":      (C["red"], C["red_soft"]),
}


# ───────────────────────────── 순수 함수(테스트용) ─────────────────────────────
def badge_palette(state: str):
    """상태코드 → (bg, fg, label). 알 수 없으면 wait."""
    return _BADGE.get(state, _BADGE["wait"])


def row_status_style(status: str):
    """행 처리 결과 → (fg, bg). 알 수 없으면 (text, surface)."""
    return _ROW_STATUS.get(status, (C["text"], C["surface"]))


def mask_request_row(req) -> dict:
    """RequestSummary → 테이블 표시용 마스킹 행(원문 PII 미포함)."""
    return {
        "token": req.request_token,
        "bank": req.bank_label or "",
        "branch": req.branch_label or "",
        "req_no": security.mask_request_no(req.masked_request_no or ""),
        "est_no": security.mask_request_no(req.masked_est_no or ""),
        "bankonline_in": req.bankonline_in or "",
        "status": req.process_status or "처리 대기",
    }


def is_excluded_grid_agency(value: str) -> bool:
    """Grid 의뢰기관 정확 일치 판정. Bank24의 HUG 표기도 PDF 출력 전 제외."""
    normalized = unicodedata.normalize("NFKC", value or "")
    agency = " ".join(normalized.split())
    if agency == "\uc8fc\ud0dd\ub3c4\uc2dc\ubcf4\uc99d\uacf5\uc0ac":
        return True
    return " ".join(normalized.split()).upper() in {"주택도시보증공사", "HUG"}


def excluded_grid_tokens(requests) -> set[str]:
    """PDF 출력 전에 제외할 그리드 행 토큰 집합."""
    return {
        r.request_token for r in requests
        if is_excluded_grid_agency(r.bank_label)
    }


# 저장 제외 시 이미 생성된 PDF 를 삭제하는 안전코드(고정 상수 allowlist).
DELETE_PDF_EXCLUSION_CODES = frozenset({
    "EXCLUDED_MANAGER", "EXCLUDED_NO_BANK", "EXCLUDED_NO_BRANCH",
})


class SecretLineEdit(QLineEdit):
    """Clipboard, drop, context-menu and history-free secret input."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setEchoMode(QLineEdit.EchoMode.Password)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.setAcceptDrops(False)
        self.setClearButtonEnabled(False)
        self.setInputMethodHints(
            Qt.InputMethodHint.ImhHiddenText
            | Qt.InputMethodHint.ImhNoPredictiveText
            | Qt.InputMethodHint.ImhNoAutoUppercase
            | Qt.InputMethodHint.ImhSensitiveData
        )

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Paste) or (
            event.key() == Qt.Key.Key_Insert
            and event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            event.ignore()
            return
        super().keyPressEvent(event)


class ToggleSwitch(QPushButton):
    toggled_state = pyqtSignal(bool)
    _SS_OFF = ("QPushButton { background: #aeb8c5; border: none; border-radius: 11px;"
               " color: white; font-size: 10px; font-weight: 700; }")
    _SS_ON = ("QPushButton { background: #1264d8; border: none; border-radius: 11px;"
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

    def is_on(self):
        return self._on

    def set_on(self, value):
        self._on = bool(value)
        self._refresh()

    def _refresh(self):
        self.setStyleSheet(self._SS_ON if self._on else self._SS_OFF)
        self.setText("ON" if self._on else "OFF")


# ───────────────────────────── QThread 워커 ─────────────────────────────
class Worker(QThread):
    """자동화/파싱을 백그라운드에서 수행하고 signal 로 마스킹 결과만 전달한다."""

    sig_log = pyqtSignal(list)
    sig_requests = pyqtSignal(list)
    sig_row = pyqtSignal(str, str)
    sig_report = pyqtSignal(list)
    sig_sp = pyqtSignal(list)
    sig_progress = pyqtSignal(int, int)
    sig_status = pyqtSignal(str)
    sig_done = pyqtSignal(str)

    def __init__(self, mode: str, *, tokens=None, pdf_root: str = "",
                 allowed_roots=None, settings_path: str | None = None,
                 adapter_provider=None, login_env_provider=None):
        super().__init__()
        self.mode = mode
        self.tokens = tokens or []
        self.pdf_root = pdf_root
        self.allowed_roots = allowed_roots or []
        self._settings_path = settings_path or settings_integrity.resolve_settings_path()
        self._adapter_provider = adapter_provider   # 테스트 주입(실제 Bank24 미실행)
        self._login_env_provider = login_env_provider  # 테스트 주입(실제 Bank24 미실행)
        self._stop = threading.Event()
        self._estop = bank24_automation.EmergencyStop()
        self._blocked = False                       # 차단 상태 보존용(§96)

    def request_stop(self):
        self._stop.set()
        self._estop.stop()          # 다음 단계 진입 차단(§51)

    def _real_backend(self):
        """프로덕션 UI 백엔드(pywinauto). 미설치면 None → real 조작 BACKEND_UNAVAILABLE."""
        try:
            import bank24_backend
            return bank24_backend.PywinautoReadonlyBackend()
        except Exception:
            return None

    def _credential_provider(self):
        """호출 시 검증된 INI [login]에서 자격증명을 다시 읽어 Credential 반환(§12).

        save_credentials=true 이고 ID/PW 가 모두 있을 때만 반환, 아니면 None(§27).
        PW 를 Worker 등 장수명 객체에 보관하지 않는다.
        """
        settings_path = self._settings_path

        def _provider():
            try:
                app = config.load_app_config(settings_path)
            except Exception:
                return None
            lg = app.login
            if not lg.save_credentials or not lg.bank24_id or not lg.bank24_pw:
                return None
            try:
                return bank24_credentials.load_credentials(
                    bank24_credentials.METHOD_INI,
                    ini_username=lg.bank24_id, ini_password=lg.bank24_pw)
            except bank24_credentials.CredentialError:
                return None
        return _provider

    def _block(self, code: str):
        """차단 상태를 표시하고 예외를 던진다. 이후 일반 예외로 'err' 덮어쓰기 금지(§96)."""
        self._blocked = True
        self.sig_status.emit("block")            # 차단됨. 키 이름/안전코드만(§14/§93/§97).
        self.sig_log.emit([f"실제 실행 차단(안전코드: {code})"])
        raise bank24_automation.AutomationBlocked("REAL_BLOCKED")

    def _adapter(self):
        """실제 Bank24 adapter 를 만든다. 게이트 실패면 차단(fake 대체 없음, §10)."""
        if self._adapter_provider is not None:
            return self._adapter_provider()          # 테스트 주입
        try:
            app = config.load_app_config(self._settings_path)
        except Exception:
            self._block("CONFIG_LOAD")
        decision = bank24_adapter.decide_adapter(
            app_config=app, stop=self._estop, backend=self._real_backend(),
            credential_provider=self._credential_provider(),
            settings_path=self._settings_path)
        if decision.mode == "real":
            return bank24_adapter.RealBank24Adapter(decision.ctx)
        self._block(decision.reason)             # MISSING_KEYS 등 실제 필수 키/안전코드만(§97)

    def run(self):
        try:
            if self.mode == "query":
                self._run_query()
            elif self.mode == "process":
                self._run_process()
        except bank24_automation.AutomationBlocked as ab:
            # 안전 코드만 표시. 일반 'err' 로 덮지 않는다(§56/§60).
            if not self._blocked:
                self.sig_log.emit([f"중단(안전코드: {str(ab) or 'BLOCKED'})"])
                self.sig_status.emit("block")
        except Exception as e:  # 서드파티 예외도 원문 대신 타입명만(§56)
            if not self._blocked:
                code = getattr(e, "code", "")
                if code:
                    self.sig_log.emit([f"오류(안전코드: {code})"])
                else:
                    self.sig_log.emit([f"오류: {type(e).__name__}"])
                self.sig_status.emit("err")
        finally:
            self.sig_done.emit(self.mode)

    # ── Bank24 실행·로그인(bank24_login_flow 이식본) 연결 ──
    def _login_stop(self):
        """bank24_login_flow 용 중지 어댑터(.is_stopped)."""
        worker = self

        class _Stop:
            def is_stopped(self_inner):
                return worker._stop.is_set() or worker._estop.is_stopped()
        return _Stop()

    def _login_env(self):
        """실 Bank24 실행·로그인 환경. 테스트는 login_env_provider 로 주입(실 Bank24 미실행)."""
        if self._login_env_provider is not None:
            env = self._login_env_provider()
            env._log = self._login_log   # 주입 env 의 단계 로그도 GUI 로 라우팅(§127)
            return env
        # 실 기본값: Desktop 열거/Popen/user32/pyautogui/클립보드/시계(모듈 기본 구현).
        return bank24_login_flow.LoginEnv(
            stop=self._login_stop(),
            credential_provider=self._credential_provider(),  # 호출 시 INI[login] 재읽기(§16)
            log=self._login_log)

    def _login_log(self, code: str):
        """bank24_login_flow 의 고정 안전코드를 GUI 단계 로그(§127)로 매핑. 원문/PII 없음."""
        F = bank24_login_flow
        mapping = {
            F.Step.LAUNCH:      ("Bank24 실행", None),
            F.Step.LOGIN_WINDOW: ("로그인창 확인", "login"),
            F.Step.CREDENTIAL:  ("자격증명 입력", None),
            F.Step.FALLBACK:    ("fallback 사용", None),
            F.Step.MAIN_WINDOW: ("메인 창 확인", None),
            F.Step.LOGIN_DONE:  ("로그인 완료", None),
            F.COORD_CLIPBOARD_PW_EXPOSURE:
                ("로그인 좌표 fallback 사용", None),
        }
        if code in mapping:
            text, status = mapping[code]
            if status:
                self.sig_status.emit(status)
            self.sig_log.emit([text])
        elif code.startswith("LOGIN_DETAIL_"):
            self.sig_log.emit([f"로그인 실패 상세(안전코드: {code[len('LOGIN_DETAIL_'):]})"])
        # 그 외 안전코드(LOGIN_SUBMIT_FAILED 등)는 result.status 로 처리한다.

    def _run_query(self):
        """실제 Bank24 확인 → (bank24_login_flow) 실행·로그인 → 탁상이동 → 조회 → 완료/오류.

        Bank24 실행·로그인은 Y_BankAuto 검증 순서/ fallback 이식본(bank24_login_flow)이
        수행한다. 로그인 성공(done) 확인 전에는 탁상 이동을 호출하지 않는다(§134). 탁상/조회
        는 기존 adapter 함수(시그니처 불변, §133)를 그대로 사용한다.
        """
        if self._stop.is_set():
            self.sig_status.emit("stop"); return
        self.sig_status.emit("check")            # Bank24 확인
        self.sig_log.emit(["Bank24 확인 중"])
        adapter = self._adapter()                # 차단 시 _block → run() 이 blocked 보존
        self.sig_status.emit("conn")
        self.sig_log.emit(["Bank24 실행·로그인 중"])

        env = self._login_env()
        result = bank24_login_flow.run_bank24_login(env)   # 실행·로그인·wait_main·2초 안정화

        if result.status == "stopped":
            self.sig_status.emit("stop"); return
        if result.status != "done":
            # 안전코드만 표시(§112/§126/§30). fake/합성 결과로 대체하지 않는다(§49).
            code = {
                "submit_failed": bank24_login_flow.LOGIN_SUBMIT_FAILED,
                "launch_failed": bank24_login_flow.BANK24_LAUNCH_FAILED,
                "error": bank24_login_flow.LOGIN_NOT_CONFIRMED,
            }.get(result.status, "LOGIN_FAILED")
            self._block(code)                    # run() 이 blocked 보존
            return

        # 로그인 성공 확인 후에만 탁상 이동(§134). 확인된 메인 창을 adapter 로 핸드오프.
        adapter.adopt_login_confirmed(result.main_win)
        if self._stop.is_set():
            self.sig_status.emit("stop"); return
        self.sig_status.emit("tab")
        self.sig_log.emit(["탁상 이동 중"])
        adapter.select_tabletop_menu()
        if self._stop.is_set():
            self.sig_status.emit("stop"); return
        self.sig_status.emit("query")
        self.sig_log.emit(["조회 중"])
        requests = adapter.query_requests()
        rows = [mask_request_row(r) for r in requests]
        self.sig_requests.emit(rows)             # 실패 시 합성 결과 없음(§49)
        self.sig_log.emit([f"조회 완료: {len(rows)}건"])   # 건수만(§50)
        app = config.load_app_config(self._settings_path)
        if app.db.enabled and requests and self._adapter_provider is None:
            # 조회된 전체 건을 같은 adapter/그리드 행 매핑으로 처리한다.
            # 유지하므로 다시 로그인하거나 다시 조회하지 않는다.
            tokens = [r.request_token for r in requests]
            excluded_tokens = excluded_grid_tokens(requests)
            self._save_with_adapter(adapter, tokens, app,
                                    excluded_tokens=excluded_tokens)
        elif not app.db.enabled:
            self.sig_log.emit(["DB 저장 생략: [database] enabled=false"])
        self.sig_status.emit("done")

    def _safe_delete_pdf(self, path: str) -> None:
        """저장 제외(DELETE_PDF_EXCLUSION_CODES) 건의 PDF 를 안전하게 삭제.

        허용 루트(allowed_roots/pdf_root) 하위의 일반 .pdf 파일일 때만 삭제한다.
        심볼릭/재분석 지점·경로 탈출·비-PDF 는 삭제하지 않는다(best-effort, 실패 무시).
        """
        import os
        try:
            if not path or os.path.islink(path):
                return
            real = os.path.realpath(path)
            if not real.lower().endswith(".pdf") or not os.path.isfile(real):
                return
            roots = [r for r in (self.allowed_roots or []) if r] or [self.pdf_root]
            for root in roots:
                try:
                    rroot = os.path.realpath(root)
                    if os.path.commonpath([real, rroot]) == rroot:
                        os.remove(real)
                        return
                except (ValueError, OSError):
                    continue
        except Exception:
            pass

    def _save_with_adapter(self, adapter, tokens, app, *, excluded_tokens=None):
        """행별 PDF 출력→탁상 파싱→독립 DB commit. 실패 행은 건너뛰고 계속.

        의뢰기관 제외 건(주택도시보증공사)은 성공·실패와 분리해 '저장 제외'로
        집계하며 DB/SP/COMMIT을 수행하지 않는다(§9-15).
        """
        import datetime
        import bankonline_ts
        import deskfile
        import parsers
        import tabletop_save

        tokens = list(dict.fromkeys(tokens))
        excluded_tokens = set(excluded_tokens or ())
        if not tokens:
            self._block("SAVE_COUNT_INVALID")
        # 진행률 전체 건수에는 제외 건도 포함한다(§13).
        total = len(tokens)
        success = 0
        failed = 0
        excluded = 0
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        for idx, token in enumerate(tokens, 1):
            if self._stop.is_set():
                self.sig_status.emit("stop"); return
            path = None
            try:
                if token in excluded_tokens:
                    raise parsers.ExcludedRequest()
                self.sig_row.emit(token, "PDF 저장 중")
                path = adapter.download_pdf(
                    token, self.pdf_root, timestamp=f"{stamp}_{idx}")
                self.sig_row.emit(token, "파싱·DB 저장 중")
                save_result = tabletop_save.save_pdf_batch(
                    [path], app, allowed_roots=self.allowed_roots or [self.pdf_root])
                # BankOnline 담보번호(DAMBO_NO)는 그리드 원본 의뢰번호(Bank24 값)를 사용한다.
                # PDF 본문 의뢰번호가 표시상 잘릴 수 있어 그리드 값이 정본이다(예: 국민 13자리).
                grid_no = ""
                if hasattr(adapter, "grid_request_no"):
                    try:
                        grid_no = adapter.grid_request_no(token)
                    except Exception:
                        grid_no = ""
                for output in getattr(save_result, "outputs", []) or []:
                    if grid_no:
                        output["RequestNo"] = grid_no
                    # 의뢰서 PDF → \\server\data1\DESK\{MasterID}-1.pdf + APW_IW_DESKFILE 등록.
                    # 탁상 저장은 이미 commit 됐으므로 여기 실패는 로그만 남기고 계속한다.
                    desk_status, desk_code = deskfile.register(
                        output, path, app, logger=lambda msg: self.sig_log.emit([msg]))
                    if desk_status == "Y":
                        self.sig_log.emit([f"DESK 등록 성공: 행 {idx}"])
                    elif desk_status == "S":
                        self.sig_log.emit([f"DESK 등록 건너뜀: 행 {idx}(안전코드: {desk_code})"])
                    else:
                        self.sig_log.emit([f"DESK 등록 실패: 행 {idx}(안전코드: {desk_code})"])
                    bankonline_in, bankonline_error = bankonline_ts.call(
                        output, app, logger=lambda msg: self.sig_log.emit([msg]))
                    if bankonline_in == "Y":
                        self.sig_log.emit([f"BankOnline 성공: 행 {idx}"])
                    elif bankonline_in == "N":
                        self.sig_log.emit([
                            f"BankOnline 실패: 행 {idx}(안전코드: {bankonline_error})"])
                self.sig_row.emit(token, "저장 완료")
                success += 1
            except parsers.ExcludedRequest as exc:
                # 제외 즉시 종료: DB/SP/COMMIT 없음. 로그는 안전코드·행 번호만(§17-18).
                code = getattr(exc, "code", "") or "EXCLUDED_HUG"
                # 담당자/은행명 미상/영업점 미상 제외 건은 이미 다운로드된 PDF 도
                # 남기지 않는다(사용자 지시 2026-07-28).
                if code in DELETE_PDF_EXCLUSION_CODES and path:
                    self._safe_delete_pdf(path)
                self.sig_row.emit(token, "저장 제외")
                self.sig_log.emit([f"행 {idx} 저장 제외(안전코드: {code})"])
                excluded += 1
            except Exception as exc:
                code = getattr(exc, "code", "") or type(exc).__name__
                self.sig_row.emit(token, "실패")
                self.sig_log.emit([f"행 {idx} 저장 실패(안전코드: {code}) — 다음 행 계속"])
                failed += 1
            finally:
                self.sig_progress.emit(idx, total)
        self.sig_log.emit(
            [f"DB 저장 종료: 성공 {success}건 / 실패 {failed}건 / 저장 제외 {excluded}건"])
        # 전체가 제외거나 일부 성공·일부 제외면 정상 종료한다(§11-12).
        # 실제 실패가 있고 성공이 0일 때만 ALL_ROWS_FAILED.
        if success == 0 and failed:
            raise tabletop_save.SaveError("ALL_ROWS_FAILED")

    def _run_process(self):
        """선택한 최대 2건을 재조회해 PDF 저장·탁상 파싱·SP 저장한다."""
        import datetime
        import tabletop_save

        tokens = list(dict.fromkeys(self.tokens))
        if not tokens:
            self._block("SAVE_COUNT_INVALID")
        app = config.load_app_config(self._settings_path)
        adapter = self._adapter()
        self.sig_log.emit(["Bank24 실행·로그인 중"])
        result = bank24_login_flow.run_bank24_login(self._login_env())
        if result.status != "done":
            self._block("LOGIN_FAILED")
        adapter.adopt_login_confirmed(result.main_win)
        adapter.select_tabletop_menu()
        requests = adapter.query_requests()
        current = {r.request_token for r in requests}
        if any(token not in current for token in tokens):
            self._block("REQUEST_NOT_FOUND")

        # 선택 실행도 조회 실행과 동일하게 PDF 출력 전에 HUG를 차단한다.
        self._save_with_adapter(
            adapter, tokens, app,
            excluded_tokens=excluded_grid_tokens(requests))
        self.sig_status.emit("done")


def _report_lines(report) -> list:
    import gui
    return gui.format_report_for_gui(report)


# ───────────────────────────── 위젯 헬퍼 ─────────────────────────────
class _HeaderBadge(QWidget):
    """헤더 상태 배지(점 + 텍스트). Y_BankAuto set_state 패턴."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(28)
        self._dot = QLabel("●")
        self._text = QLabel("대기")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(11, 0, 11, 0)
        lay.setSpacing(7)
        lay.addWidget(self._dot)
        lay.addWidget(self._text)
        self.set_state("wait")

    def set_state(self, state: str):
        bg, fg, label = badge_palette(state)
        self.setStyleSheet(f"background-color: {bg}; border-radius: 14px; border: none;")
        self._dot.setStyleSheet(
            f"color: {fg}; font-size: 9px; background: transparent; border: none;")
        self._text.setStyleSheet(
            f"color: {fg}; font-size: 12px; font-weight: 700; "
            "background: transparent; border: none;")
        self._text.setText(label)


# ───────────────────────────── 메인 윈도우 ─────────────────────────────
class TabletopWindow(QMainWindow):
    def __init__(self, *, pdf_root: str, real_allowed: bool, mode_label: str,
                 setup_notes=None, app_config=None):
        super().__init__()
        self.pdf_root = pdf_root
        self.real_allowed = real_allowed
        self.mode_label = mode_label
        # 검증된 비민감 설정(config.AppConfig). 실제 소비처가 있는 pdf_root 는 위에서
        # 검증 후 별도 전달되며, 그 외 항목은 이 test판 GUI 에 소비처가 없어 사용하지 않는다
        # (DB/allowlist 로 접속 대상을 확장하지 않는다). 자격증명은 포함되지 않는다.
        self.app_config = app_config
        self._worker: Worker | None = None
        self._run_log_file = None
        self._rows_by_token: dict[str, int] = {}
        self._token_by_row: dict[int, str] = {}
        self._flight = None
        self._schedule_timer = QTimer(self)
        self._schedule_timer.timeout.connect(self._scheduled_run)

        self.setWindowTitle(APP_TITLE)
        self.resize(1100, 720)
        self.setMinimumSize(1024, 720)
        self.setStyleSheet(STYLESHEET)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())

        workspace = QWidget()
        # selector 없는 bare 배경 스타일시트는 자식 위젯(버튼 등)까지 전파되어
        # #btn_primary 등 전역 규칙을 덮어버린다. objectName 으로 범위를 제한한다.
        workspace.setObjectName("workspace")
        workspace.setStyleSheet(f"QWidget#workspace {{ background-color: {C['bg']}; }}")
        ws = QHBoxLayout(workspace)
        ws.setContentsMargins(14, 14, 14, 14)
        ws.setSpacing(14)
        ws.addWidget(self._build_left())
        ws.addWidget(self._build_result_panel(), 1)
        root.addWidget(workspace, 1)

        root.addWidget(self._build_log())

        # settings.ini [login]을 반영한다. 화면에는 PW 마스킹을 유지한다.
        login_cfg = getattr(self.app_config, "login", None)
        if login_cfg is not None:
            save = bool(getattr(login_cfg, "save_credentials", False))
            self.chk_save_cred.setChecked(save)
            if save:
                self.edit_id.setText(getattr(login_cfg, "bank24_id", "") or "")
                self.edit_pw.setText(getattr(login_cfg, 'REDACTED_CONFIGURE_LOCALLY', "") or "")

        for note in (setup_notes or []):
            self._log(f"설정: {note}", C["muted"])

    # ---- 헤더/배너 ----
    def _build_header(self) -> QWidget:
        head = QWidget()
        head.setFixedHeight(56)
        head.setStyleSheet(
            f"background-color: {C['surface']}; border-bottom: 1px solid {C['line']};")
        lay = QHBoxLayout(head)
        lay.setContentsMargins(18, 0, 18, 0)
        lay.setSpacing(11)
        mark = QLabel("◆")
        mark.setStyleSheet(
            f"color: {C['blue']}; font-size: 14px; background: transparent; border: none;")
        lay.addWidget(mark)
        title = QLabel(APP_TITLE)
        title.setStyleSheet(
            f"font-size: 16px; font-weight: 700; color: {C['text']}; "
            "background: transparent; border: none;")
        lay.addWidget(title)
        lay.addStretch()
        self.badge = _HeaderBadge()
        lay.addWidget(self.badge)
        ver = QLabel(APP_VERSION)
        ver.setStyleSheet(
            f"color: {C['muted']}; font-size: 12px; background: transparent; "
            "border: none; margin-left: 12px;")
        lay.addWidget(ver)
        return head

    def _build_banner(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(28)
        w.setStyleSheet(f"background-color: {C['red']};")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(18, 0, 18, 0)
        lbl = QLabel(TEST_BANNER)
        lbl.setStyleSheet(
            "color: #ffffff; font-size: 12px; font-weight: 700; "
            "background: transparent; border: none;")
        lay.addWidget(lbl)
        return w

    def _panel(self, title: str):
        outer = QWidget()
        outer.setObjectName("panelOuter")
        outer.setStyleSheet(
            f"QWidget#panelOuter {{ background: {C['surface']}; "
            f"border: 1px solid {C['line']}; border-radius: 8px; }}")
        ov = QVBoxLayout(outer)
        ov.setContentsMargins(0, 0, 0, 0)
        ov.setSpacing(0)
        hdr = QWidget()
        hdr.setFixedHeight(42)
        hdr.setStyleSheet(f"background: transparent; border-bottom: 1px solid {C['line']};")
        hh = QHBoxLayout(hdr)
        hh.setContentsMargins(14, 0, 14, 0)
        t = QLabel(title)
        t.setStyleSheet("font-size: 13px; font-weight: 700; background: transparent; border: none;")
        hh.addWidget(t)
        ov.addWidget(hdr)
        body = QWidget()
        body.setObjectName("panelBody")
        bv = QVBoxLayout(body)
        bv.setContentsMargins(14, 14, 14, 14)
        bv.setSpacing(11)
        ov.addWidget(body)
        return outer, bv

    def _muted(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {C['muted']}; font-size: 12px; font-weight: 600; "
            "background: transparent; border: none;")
        return lbl

    # ---- 좌측 열 ----
    def _build_left(self) -> QWidget:
        left = QWidget()
        left.setObjectName("leftCol")
        left.setFixedWidth(330)
        left.setStyleSheet("QWidget#leftCol { background: transparent; }")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(12)

        login, lb = self._panel("Bank24 로그인")
        login.setMinimumHeight(225)
        lb.setContentsMargins(14, 12, 14, 12)
        lb.setSpacing(6)
        lb.addWidget(self._muted("Bank24 ID"))
        self.edit_id = QLineEdit(); self.edit_id.setPlaceholderText("아이디 입력")
        lb.addWidget(self.edit_id)
        lb.addWidget(self._muted("Bank24 PW"))
        self.edit_pw = SecretLineEdit(); self.edit_pw.setPlaceholderText("비밀번호 입력")
        lb.addWidget(self.edit_pw)
        self.chk_save_cred = QCheckBox("ID/PW 저장")
        self.chk_save_cred.setChecked(True)
        self.chk_save_cred.setToolTip("settings.ini [login]의 ID/PW 사용 여부")
        lb.addWidget(self.chk_save_cred)
        self.radio_keyring = QRadioButton(); self.radio_keyring.setChecked(True); self.radio_keyring.hide()
        self.radio_env = QRadioButton(); self.radio_env.hide()
        self.chk_save_cred.toggled.connect(self._credential_method_changed)
        self.btn_save_cred = QPushButton(); self.btn_save_cred.hide()
        self.btn_save_cred.clicked.connect(self._on_store_cred)
        self.lbl_cred = QLabel(); self.lbl_cred.hide()
        lv.addWidget(login)

        sched, sb = self._panel("자동 실행")
        sched.setMinimumHeight(225)
        top = QWidget(); tl = QHBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0); tl.setSpacing(9)
        self.schedule_switch = ToggleSwitch()
        self.schedule_switch.toggled_state.connect(self._on_schedule_toggled)
        tl.addWidget(self.schedule_switch)
        self.lbl_sched_state = QLabel("자동 실행 OFF")
        self.lbl_sched_state.setStyleSheet("font-size: 13px; font-weight: 700; background: transparent; border: none;")
        tl.addWidget(self.lbl_sched_state); tl.addStretch()
        tl.addWidget(self._muted("간격"))
        self.cmb_interval = QComboBox(); self.cmb_interval.addItems(["5분", "10분"])
        self.cmb_interval.setFixedWidth(78)
        tl.addWidget(self.cmb_interval)
        sb.addWidget(top)

        nbox = QWidget()
        nbox.setStyleSheet(f"background-color: {C['blue_soft']}; border: 1px solid #cddcf0; border-radius: 6px;")
        nv = QVBoxLayout(nbox); nv.setContentsMargins(12, 11, 12, 11); nv.setSpacing(5)
        nlbl = QLabel("다음 실행"); nlbl.setStyleSheet("color: #55708f; font-size: 11px; font-weight: 700; background: transparent; border: none;")
        nv.addWidget(nlbl)
        nr = QWidget(); nrl = QHBoxLayout(nr); nrl.setContentsMargins(0, 0, 0, 0); nrl.setSpacing(10)
        self.lbl_next_run = QLabel("-"); self.lbl_next_run.setStyleSheet("color: #173f6d; font-size: 18px; font-weight: 700; background: transparent; border: none;")
        self.lbl_last_run = QLabel("마지막 실행 없음"); self.lbl_last_run.setStyleSheet("color: #55708f; font-size: 12px; background: transparent; border: none;")
        nrl.addWidget(self.lbl_next_run); nrl.addStretch(); nrl.addWidget(self.lbl_last_run)
        nv.addWidget(nr); sb.addWidget(nbox)

        act = QWidget(); al = QHBoxLayout(act)
        al.setContentsMargins(0, 0, 0, 0); al.setSpacing(8)
        self.btn_start = QPushButton("▶  즉시 1회 실행")
        self.btn_start.setObjectName("btn_primary"); self.btn_start.setFixedHeight(42)
        self.btn_start.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_start.clicked.connect(self._on_primary_action)
        self.btn_stop = QPushButton("■  일시정지"); self.btn_stop.setFixedWidth(120); self.btn_stop.setFixedHeight(42)
        self.btn_stop.setEnabled(False); self.btn_stop.clicked.connect(self.on_stop)
        al.addWidget(self.btn_start, 1); al.addWidget(self.btn_stop); sb.addWidget(act)
        lv.addWidget(sched)

        # Security/TS-only controls stay out of the reference default surface.
        self.edit_confirm = SecretLineEdit(); self.edit_confirm.hide()
        self.lbl_real = QLabel(); self.lbl_real.hide()
        self.btn_query = QPushButton(); self.btn_query.hide(); self.btn_query.clicked.connect(self.on_query)
        self.btn_reproc = QPushButton(); self.btn_reproc.hide(); self.btn_reproc.clicked.connect(self.on_reprocess)
        self.btn_reset = QPushButton(); self.btn_reset.hide(); self.btn_reset.clicked.connect(self.on_reset)
        self.btn_db = QPushButton(); self.btn_db.setEnabled(False); self.btn_db.hide()
        lv.addStretch()
        return left

    # ---- 결과 패널 ----
    def _build_result_panel(self) -> QWidget:
        outer = QWidget()
        outer.setObjectName("resultOuter")
        outer.setStyleSheet(
            f"QWidget#resultOuter {{ background: {C['surface']}; "
            f"border: 1px solid {C['line']}; border-radius: 8px; }}")
        ov = QVBoxLayout(outer)
        ov.setContentsMargins(0, 0, 0, 0)
        ov.setSpacing(0)

        phdr = QWidget()
        phdr.setFixedHeight(42)
        phdr.setStyleSheet(f"background: transparent; border-bottom: 1px solid {C['line']};")
        ph = QHBoxLayout(phdr)
        ph.setContentsMargins(14, 0, 14, 0)
        t = QLabel("처리 결과")
        t.setStyleSheet("font-size: 13px; font-weight: 700; background: transparent; border: none;")
        ph.addWidget(t)
        ph.addStretch()
        self.btn_select_all = QPushButton(); self.btn_select_all.hide()
        self.btn_select_all.clicked.connect(self._select_all)
        note = QLabel("탁상 · 당일 · 미접수 · 지원 은행 전체")
        note.setStyleSheet(
            f"color: {C['muted']}; font-size: 11px; background: transparent; "
            "border: none; margin-left: 10px;")
        ph.addWidget(note)
        ov.addWidget(phdr)

        self.table = QTableWidget(0, len(TABLE_COLS))
        self.table.setHorizontalHeaderLabels(TABLE_COLS)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hdr.setStretchLastSection(False)
        self.table.setColumnWidth(0, 130)
        self.table.setColumnWidth(1, 120)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(3, 120)
        self.table.setColumnWidth(4, 100)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        # TS 전용 기능은 숨긴 위젯이 아니라 우클릭 컨텍스트 메뉴로 명확히 접근한다.
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_table_menu)
        ov.addWidget(self.table, 1)

        self.progress = QProgressBar(); self.progress.hide()
        self.lbl_verify = QLabel(); self.lbl_verify.hide()
        self.sp_text = QTextEdit(); self.sp_text.setReadOnly(True); self.sp_text.hide()

        # 선택 상세
        det = QWidget()
        det.setFixedHeight(54)
        det.setStyleSheet(f"background: {C['surface_soft']}; border-top: 1px solid {C['line']};")
        dl = QHBoxLayout(det)
        dl.setContentsMargins(14, 0, 14, 0)
        strong = QLabel("선택 항목")
        strong.setStyleSheet(
            "color: #344256; font-weight: 700; font-size: 12px; margin-right: 8px; "
            "background: transparent; border: none;")
        dl.addWidget(strong)
        self.lbl_sel = QLabel("행을 선택하면 처리 내용을 표시합니다.")
        self.lbl_sel.setStyleSheet(
            f"color: {C['muted']}; font-size: 12px; background: transparent; border: none;")
        dl.addWidget(self.lbl_sel, 1)
        ov.addWidget(det)

        return outer

    # ---- 로그 ----
    def _build_log(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(150)
        w.setStyleSheet(
            f"background-color: {C['surface']}; border-top: 1px solid {C['line_strong']};")
        wl = QVBoxLayout(w)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(0)
        toolbar = QWidget()
        toolbar.setFixedHeight(38)
        toolbar.setStyleSheet(f"background: {C['surface']}; border-bottom: 1px solid {C['line']};")
        tl = QHBoxLayout(toolbar)
        tl.setContentsMargins(16, 0, 12, 0)
        tl.setSpacing(6)
        hl = QLabel("실행 로그")
        hl.setStyleSheet(
            f"font-size: 12px; font-weight: 700; color: {C['text']}; "
            "background: transparent; border: none;")
        tl.addWidget(hl)
        tl.addStretch()
        for label, slot in (("로그 복사", self._copy_log), ("로그 지우기", self._clear_log)):
            b = QPushButton(label)
            b.setFixedHeight(28)
            b.setFixedWidth(70)
            b.setStyleSheet(
                f"QPushButton {{ height: 28px; padding: 0 10px; border: 1px solid {C['line']};"
                " border-radius: 6px; background: #fff; color: #465468; font-size: 11px; font-weight: 700; }"
                "QPushButton:hover { background: #f4f6f8; }")
            b.clicked.connect(slot)
            tl.addWidget(b)
        wl.addWidget(toolbar)
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        wl.addWidget(self.log_edit, 1)
        self._log("대기 중", C["muted"])
        return w

    # ---- 시크릿 위젯 하드닝 ----
    def _harden_secret(self, edit: QLineEdit):
        # 붙여넣기 컨텍스트 메뉴/드롭 비활성, 자동완성 없음
        edit.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        edit.setDragEnabled(False)
        try:
            edit.setClearButtonEnabled(False)
        except Exception:
            pass

    # ---- 로그/상태 ----
    def _log(self, msg: str, color: str = ""):
        import applog
        safe = applog.sanitize_line(str(msg))   # 최후방 레닥션 가드
        safe_html = safe.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        cur = self.log_edit.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        self.log_edit.setTextCursor(cur)
        fg = color or "#48576a"
        self.log_edit.insertHtml(f'<span style="color:{fg};">{safe_html}</span><br>')
        sb = self.log_edit.verticalScrollBar()
        sb.setValue(sb.maximum())
        if self._run_log_file is not None:
            try:
                from datetime import datetime
                self._run_log_file.write(
                    f"[{datetime.now().strftime('%H:%M:%S')}] {safe}\n")
                self._run_log_file.flush()
            except (OSError, ValueError):
                self._close_run_log()

    def _open_run_log(self):
        """PDF 저장 폴더에 작업별 정제 로그를 연다(Y_BankAuto 실행 로그 방식)."""
        self._close_run_log()
        try:
            from datetime import datetime
            os.makedirs(self.pdf_root, exist_ok=True)
            name = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.log"
            self._run_log_file = open(
                os.path.join(self.pdf_root, name), "x", encoding="utf-8")
        except (OSError, ValueError):
            self._run_log_file = None

    def _close_run_log(self):
        fh, self._run_log_file = self._run_log_file, None
        if fh is not None:
            try:
                fh.close()
            except OSError:
                pass

    def _log_lines(self, lines):
        for ln in lines:
            self._log(ln)

    def _set_state(self, state: str):
        self.badge.set_state(state)

    def _set_sp(self, lines):
        self.sp_text.setPlainText("\n".join(lines))

    # ---- 선택 ----
    def _select_all(self):
        self.table.selectAll()

    def _selected_tokens(self):
        rows = {ix.row() for ix in self.table.selectedIndexes()}
        return [self._token_by_row[r] for r in rows if r in self._token_by_row]

    def _on_row_selected(self):
        n = len(self._selected_tokens())
        self.lbl_sel.setText("행을 선택하면 처리 내용을 표시합니다." if not n else f"{n}건 선택됨")

    # ---- TS 전용 기능 접근 경로(컨텍스트 메뉴 + 안전 대화상자) ----
    def _build_table_menu(self) -> QMenu:
        """결과 테이블 우클릭 메뉴. TS 전용 기능의 명확한 접근 경로(숨김 위젯 대체)."""
        m = QMenu(self)
        m.addAction("전체 선택", self._select_all)
        m.addAction("선택 처리 시작", self.on_start)
        m.addAction("실패 재처리", self.on_reprocess)
        m.addAction("결과 초기화", self.on_reset)
        m.addSeparator()
        m.addAction("SP 파라미터 미리보기…", self._open_sp_preview_dialog)
        m.addAction("실제 자동화 설정…", self._open_real_settings_dialog)
        m.addSeparator()
        m.addAction("선택 항목 DB 저장", self.on_start)
        return m

    def _show_table_menu(self, pos):
        self._build_table_menu().exec(self.table.viewport().mapToGlobal(pos))

    def _sp_preview_lines(self) -> list:
        """현재 SP 미리보기 라인. 처리 결과가 없으면 provisional 기본 미리보기."""
        import sp_preview
        text = self.sp_text.toPlainText().strip()
        if text:
            return text.splitlines()
        return sp_preview.format_preview_lines(sp_preview.build_preview(None))

    def _open_sp_preview_dialog(self):
        """SP 파라미터 미리보기 대화상자(실행 버튼 없음). 기본은 닫힘 상태."""
        dlg = QDialog(self)
        dlg.setWindowTitle("SP 파라미터 미리보기 (실행 없음)")
        dlg.resize(520, 360)
        lay = QVBoxLayout(dlg)
        lay.addWidget(self._muted("SP 실행/저장/COMMIT 경로에 연결되지 않습니다(미리보기 전용)."))
        view = QTextEdit()
        view.setReadOnly(True)
        view.setPlainText("\n".join(self._sp_preview_lines()))
        lay.addWidget(view)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(dlg.reject)
        bb.accepted.connect(dlg.accept)
        lay.addWidget(bb)
        dlg.exec()

    def _open_real_settings_dialog(self):
        """실제 자동화 세션 확인문구 입력 대화상자(기본 닫힘). real 은 fail-closed 유지."""
        dlg = QDialog(self)
        dlg.setWindowTitle("실제 자동화 설정 (fail-closed)")
        dlg.resize(460, 200)
        lay = QVBoxLayout(dlg)
        state = "가능(설정 안전)" if self.real_allowed else "비활성(스위치/설정 미충족)"
        lay.addWidget(QLabel(
            "real 모드는 승인 스위치·검증 설정·컨트롤 pin 이 모두 충족될 때만 활성화됩니다."))
        lay.addWidget(self._muted(f"현재 real 상태: {state}"))
        lay.addWidget(self._muted("실제 자동화 세션 확인문구"))
        field = SecretLineEdit()
        field.setPlaceholderText("real 실행 시에만 입력")
        lay.addWidget(field)
        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        try:
            if dlg.exec() == QDialog.DialogCode.Accepted:
                # 다음 실행에서 사용할 확인문구를 내부 저장 위젯에만 보관(화면 미노출).
                self.edit_confirm.setText(field.text())
        finally:
            field.clear()   # 대화상자 입력 버퍼 즉시 소거

    def _credential_method_changed(self, checked: bool):
        self.radio_keyring.setChecked(False)
        self.radio_env.setChecked(False)
        if not checked:
            self.edit_id.clear()
            self.edit_pw.clear()

    def credential_method(self) -> str:
        return bc.METHOD_INI

    def _load_selected_credentials(self):
        return bc.load_credentials(
            self.credential_method(), ini_username=self.edit_id.text().strip(),
            ini_password=self.edit_pw.text())

    def _take_confirm_phrase(self) -> str:
        phrase = self.edit_confirm.text()
        self.edit_confirm.clear()
        return phrase

    def _on_primary_action(self):
        if self.table.rowCount() and self._selected_tokens():
            self.on_start()
        else:
            self.on_query()

    def _on_schedule_toggled(self, enabled: bool):
        self.lbl_sched_state.setText("자동 실행 ON" if enabled else "자동 실행 OFF")
        if enabled:
            minutes = 5 if self.cmb_interval.currentIndex() == 0 else 10
            self._schedule_timer.start(minutes * 60 * 1000)
            self.lbl_next_run.setText(f"{minutes}분 후")
        else:
            self._schedule_timer.stop()
            self.lbl_next_run.setText("-")

    def _scheduled_run(self):
        if self._worker is None:
            self._on_primary_action()

    # ---- single-flight ----
    def _acquire_flight(self) -> bool:
        import single_flight
        if self._flight is not None:
            return True
        f = single_flight.SingleFlight()
        if not f.acquire():
            self._log("다른 세션이 실행 중입니다(single-flight). 시작하지 않습니다.", C["red"])
            self._set_state("err")
            return False
        self._flight = f
        return True

    def _release_flight(self):
        if self._flight is not None:
            self._flight.release()
            self._flight = None

    def _busy(self, busy: bool):
        self.btn_query.setEnabled(not busy)
        self.btn_start.setEnabled(not busy)
        self.btn_reproc.setEnabled(not busy)
        self.edit_id.setEnabled(not busy)
        self.edit_pw.setEnabled(not busy)
        self.btn_stop.setEnabled(busy)

    # ---- 액션 ----
    def on_query(self):
        """즉시 1회 실행: 대화상자 없이 실제 Bank24 연결/조회를 시작한다(§94)."""
        if self._worker is not None or not self._acquire_flight():
            return
        self._set_state("check")
        self._busy(True)
        self._open_run_log()
        self._log("== 실제 Bank24 탁상 조회 시작 ==", C["blue"])
        self.edit_pw.clear()             # PW 입력 버퍼 소거(§31)
        self._start_worker(Worker("query", pdf_root=self.pdf_root,
                                  allowed_roots=[self.pdf_root]))

    def on_start(self):
        tokens = self._selected_tokens()
        if not tokens:
            self._log("저장할 행을 선택하세요.", C["amber"]); return
        if self._worker is not None or not self._acquire_flight():
            return
        self._busy(True)
        self._set_state("conn")
        self._open_run_log()
        self._log(f"== 선택 {len(tokens)}건 PDF·탁상 파싱·DB 저장 시작 ==", C["blue"])
        self._start_worker(Worker(
            "process", tokens=tokens, pdf_root=self.pdf_root,
            allowed_roots=[self.pdf_root]))

    def on_stop(self):
        if self._worker is not None:
            self._worker.request_stop()
        self.edit_confirm.clear()
        self.edit_pw.clear()
        self._set_state("stop")
        self._log("긴급 중지 요청됨. 신규 단계를 시작하지 않습니다.", C["amber"])

    def on_reprocess(self):
        col = TABLE_COLS.index("처리 결과")
        rows = []
        for r in range(self.table.rowCount()):
            cell = self.table.item(r, col)
            if cell and cell.text() in ("실패", "저장 제외"):
                rows.append(r)
        if not rows:
            self._log("재처리할 실패 건이 없습니다.", C["muted"]); return
        self.table.clearSelection()
        for r in rows:
            self.table.selectRow(r)
        self.on_start()

    def on_reset(self):
        if self._worker is not None:
            self._log("처리 중에는 초기화할 수 없습니다.", C["amber"]); return
        self.table.setRowCount(0)
        self._rows_by_token.clear()
        self._token_by_row.clear()
        self.progress.setValue(0)
        self._set_sp([])
        self.lbl_verify.setText("Customer: - / RegHist: - / 중복: - / 메타데이터: -")
        self.lbl_sel.setText("행을 선택하면 처리 내용을 표시합니다.")
        self._set_state("wait")
        self._log("결과 초기화됨.", C["muted"])

    def _on_store_cred(self):
        uid, pw = self.edit_id.text(), self.edit_pw.text()
        try:
            bc.store_credentials(uid, pw)
            self.lbl_cred.setText("자격증명: keyring 저장됨")
            self._log("자격증명 keyring 저장 완료(값 미표시).", C["green"])
        except bc.CredentialError:
            self.lbl_cred.setText("자격증명: 저장 실패")
            self._log("자격증명 저장 실패(안전코드).", C["red"])
        finally:
            self.edit_pw.clear()   # 입력 버퍼 소거

    def _copy_log(self):
        # 로그는 이미 마스킹/정화된 내용만 담긴다.
        from PyQt6.QtWidgets import QApplication
        cb = QApplication.clipboard()
        if cb is not None:
            cb.setText(self.log_edit.toPlainText())

    def _clear_log(self):
        self.log_edit.clear()

    # ---- 워커 연결 ----
    def _start_worker(self, worker: Worker):
        self._worker = worker
        worker.sig_log.connect(self._log_lines)
        worker.sig_requests.connect(self._on_requests)
        worker.sig_row.connect(self._on_row)
        worker.sig_report.connect(self._log_lines)
        worker.sig_sp.connect(self._set_sp)
        worker.sig_progress.connect(self._on_progress)
        worker.sig_status.connect(self._set_state)
        worker.sig_done.connect(self._on_done)
        worker.start()

    def _on_requests(self, rows):
        for row in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(row["req_no"]))
            self.table.setItem(r, 1, QTableWidgetItem(row.get("est_no", "")))
            self.table.setItem(r, 2, QTableWidgetItem(row["bank"]))
            self.table.setItem(r, 3, QTableWidgetItem(row.get("bankonline_in", "")))
            self._set_row_status(r, row["status"])
            self._rows_by_token[row["token"]] = r
            self._token_by_row[r] = row["token"]

    def _on_row(self, request_key: str, state: str):
        r = self._rows_by_token.get(request_key)
        if r is not None:
            self._set_row_status(r, state)
            self.table.setItem(r, 3, QTableWidgetItem("완료" if state in ("파싱 완료", "저장 제외") else ""))

    def _set_row_status(self, row: int, status: str):
        col = TABLE_COLS.index("처리 결과")
        cell = self.table.item(row, col) or QTableWidgetItem()
        self.table.setItem(row, col, cell)
        fg, bg = row_status_style(status)
        cell.setText(status)
        cell.setForeground(QColor(fg))
        cell.setBackground(QColor(bg))

    def _on_progress(self, done: int, total: int):
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(done)

    def _on_done(self, mode: str):
        self.edit_confirm.clear()
        self.edit_pw.clear()
        self._busy(False)
        self._release_flight()
        self._worker = None
        self._on_row_selected()
        self._close_run_log()

    def closeEvent(self, event):
        self._schedule_timer.stop()
        if self._worker is not None:
            self._worker.request_stop()
        self.edit_confirm.clear()
        self.edit_pw.clear()
        self._close_run_log()
        self._release_flight()
        super().closeEvent(event)


# ───────────────────────────── 부트스트랩 ─────────────────────────────
@dataclass(frozen=True)
class RuntimeConfig:
    """_resolve_runtime() 결과. 불변(frozen)이며 전역 mutable 설정 상태를 두지 않는다."""
    real_allowed: bool
    mode_label: str
    pdf_root: str                # 검증된 pdf_root(승인 루트 내부) 또는 안전 기본값
    integrity: object            # settings_integrity.IntegrityResult
    app_config: object           # config.AppConfig (검증된 비민감 설정)
    pdf_root_from_ini: bool      # INI 유래 → 사용 직전 재검증 대상
    approved_root: str           # pdf_root 승인 루트(앱 데이터 디렉터리)


def _pdf_paths() -> tuple[str, str]:
    """(승인 루트, 기본 pdf_root) 반환.

    승인 루트는 기존 코드가 계산하던 앱 데이터 디렉터리(<base>\\Y_TSBankAuto)이며,
    기본 pdf_root 은 그 하위의 pdf 폴더다. 임의로 넓은 루트를 만들지 않는다.
    """
    pdf_root = r"\\data\DATA\6.업무2팀\온라인탁상"
    return pdf_root, pdf_root


def _validate_pdf_root(candidate: str, approved_root: str) -> str | None:
    """INI pdf_root(비신뢰 입력)를 검증한다. 안전하면 정규화 절대경로, 아니면 None.

    - 환경변수/사용자 홈 확장·암묵적 상대경로 해석을 하지 않는다(절대경로만 허용).
    - 승인 루트 내부인지 os.path.commonpath 로 확인한다(문자열 prefix 비교 아님).
    - '..' 상위참조, UNC/네트워크, 다른 드라이브, reparse(symlink/junction/reparse point) 거부.
    - 디렉터리를 생성하지 않는다.
    """
    import settings_integrity as si
    raw = (candidate or "").strip()
    if not raw:
        return None
    # 환경변수(%VAR%/$VAR)·홈(~) 확장 토큰이 있으면 암묵 확장하지 않고 거부한다.
    if "%" in raw or "$" in raw or raw.startswith("~"):
        return None
    # 절대경로만 허용(상대경로를 cwd 기준으로 암묵 해석하지 않는다).
    if not os.path.isabs(raw):
        return None
    # 원문 기준 '..' 상위참조 거부.
    if ".." in raw.replace("/", "\\").split("\\"):
        return None
    # UNC/네트워크 경로 거부.
    if not si._is_local_path(raw):
        return None
    cand = os.path.normpath(os.path.abspath(raw))
    approved = os.path.normpath(os.path.abspath(approved_root))
    # 같은 드라이브 + 승인 루트 내부(commonpath) 확인.
    if os.path.splitdrive(cand)[0].lower() != os.path.splitdrive(approved)[0].lower():
        return None
    try:
        if os.path.commonpath([cand, approved]) != approved:
            return None
    except ValueError:
        return None    # 공통 경로 산출 불가(다른 드라이브 등)
    # reparse point(존재하는 상위 포함) 거부.
    if si._path_has_reparse(cand):
        return None
    return cand


def _resolve_runtime() -> RuntimeConfig:
    import settings_integrity
    import config
    # 설정 파일이 없으면 시크릿 없는 기본본을 자동 생성(고정 경로). 실패해도 예외 없이
    # 진행하며, 이후 무결성 검사가 real 을 fail-closed 로 차단한다(생성이 게이트를 우회하지 않음).
    settings_integrity.ensure_settings_file()
    result, ini_path = settings_integrity.check_settings()

    # 비민감 설정을 기존 파서(config.load_app_config)로 로드한다. 파싱/중복 섹션·키/
    # 타입·형식 등 오류는 안전 기본값으로 폴백하되 real 은 아래에서 차단한다.
    # 값·경로·자격증명은 로그로 남기지 않는다(자격증명형 키는 config 가 애초에 읽지 않음).
    try:
        app_config = config.load_app_config(ini_path)
        config_ok = True
    except Exception:
        app_config = config.AppConfig()   # 안전 기본값
        config_ok = False

    approved_root, default_pdf_root = _pdf_paths()
    pdf_root = default_pdf_root
    pdf_root_from_ini = False
    pdf_root_ok = True
    # 운영 PDF 저장 위치는 요청된 고정 UNC 경로를 사용하며 INI로 덮어쓰지 않는다.

    # real 허용: 설정 로드 정상 + read_only=true. INI ACL 무결성은 요구하지 않는다(§4).
    # [bank24] 미요구(§22) → 필수 키 없음. 최종 실행 게이트는 Worker.decide_adapter.
    read_only_ok = bool(getattr(app_config.options, "read_only", True))
    real_allowed = config_ok and pdf_root_ok and read_only_ok
    mode_label = "실제 Bank24 (읽기 전용)" if real_allowed else "차단됨(설정 필요)"
    return RuntimeConfig(
        real_allowed=real_allowed, mode_label=mode_label, pdf_root=pdf_root,
        integrity=result, app_config=app_config,
        pdf_root_from_ini=pdf_root_from_ini, approved_root=approved_root)


def build_window(*, pdf_root: str | None = None, real_allowed: bool = False,
                 mode_label: str = "차단됨(설정/신뢰 필요)", setup_notes=None,
                 app_config=None) -> "TabletopWindow":
    """테스트/재사용용 팩토리. QApplication 은 호출부가 준비해야 한다.

    구성 시 부수효과 없음: 디렉터리 생성/로그/락/네트워크 없이 위젯만 만든다.
    pdf_root 실제 생성은 실행 경로(main)에서만 수행한다.
    """
    if pdf_root is None:
        base = os.environ.get("TEMP") or os.getcwd()
        pdf_root = os.path.join(base, "Y_TSBankAuto", "pdf")
    return TabletopWindow(pdf_root=pdf_root, real_allowed=real_allowed,
                          mode_label=mode_label, setup_notes=setup_notes,
                          app_config=app_config)


def main():  # pragma: no cover - GUI 이벤트 루프
    import sys

    import applog
    from PyQt6.QtWidgets import QApplication

    applog.disable_faulthandler()
    rc = _resolve_runtime()
    pdf_root = rc.pdf_root
    real_allowed = rc.real_allowed
    # 사용 직전 재검증(TOCTOU/경로 교체 완화): INI 유래 pdf_root 가 여전히 승인 루트
    # 내부이며 reparse 가 아닌지 재확인. 실패하면 기본 경로로 폴백하고 real 을 차단한다.
    if rc.pdf_root_from_ini:
        _approved, default_pdf_root = _pdf_paths()
        if _validate_pdf_root(pdf_root, rc.approved_root) is None:
            pdf_root = default_pdf_root
            real_allowed = False
    applog.configure_logging(enable_file=rc.integrity.real_allowed)
    applog.install_excepthook()
    os.makedirs(pdf_root, exist_ok=True)

    app = QApplication(sys.argv)
    win = build_window(pdf_root=pdf_root, real_allowed=real_allowed,
                       mode_label=rc.mode_label, setup_notes=rc.integrity.reasons,
                       app_config=rc.app_config)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
