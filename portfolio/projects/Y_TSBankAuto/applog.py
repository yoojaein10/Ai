# -*- coding: utf-8 -*-
"""로그·예외 위생 (지시 §15, §11-b, §11-c).

- 모든 로그 라인은 최후방 레닥션 가드를 거친다: 자격증명/경로/PII 후보 패턴 마스킹.
- CR/LF/NUL/제어문자/ANSI escape 제거, 한 이벤트 = 한 줄 정규화(로그 인젝션 방지).
- 파일 로그는 안전한 설정일 때만, 사용자 전용 로컬 경로 + rotation(크기·개수 상한)으로만.
- 공용 TEMP/네트워크 경로에 로그를 쓰지 않는다.
- 최상위 예외 훅은 원문 traceback 대신 안전 코드만 표면화한다.
- faulthandler 는 기본 비활성. 시스템 WER 정책은 읽기 전용 확인만(변경하지 않음).

sanitize_line() 은 tkinter/파일시스템 없이 단위 테스트 가능한 순수 함수다.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import re
import stat as _stat
import sys

import security

# ── 정화 정규식 ──
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")   # CSI 등 ANSI escape
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")             # CR/LF/NUL/제어문자
# PII/경로 후보 (defense-in-depth: 코드가 이미 안 남기더라도 최후방 차단)
_WINPATH_RE = re.compile(r"(?:[A-Za-z]:\\|\\\\)[^\s\"']*")   # C:\... 또는 \\UNC
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE_RE = re.compile(r"\b0\d{1,2}[-\s]?\d{3,4}[-\s]?\d{4}\b")

# 로그 파일 rotation 기본값
LOG_MAX_BYTES = 512 * 1024
LOG_BACKUP_COUNT = 3


def sanitize_line(text: str) -> str:
    """단일 로그 라인 정화: 시크릿/경로/PII 레닥션 + 제어문자·ANSI 제거 + 1줄 정규화."""
    s = "" if text is None else str(text)
    # 1) 시크릿/접속문자열 (security 재사용)
    s = security.mask_connection_string(s)
    # 2) 경로/이메일/전화 후보
    s = _WINPATH_RE.sub("[path]", s)
    s = _EMAIL_RE.sub("[email]", s)
    s = _PHONE_RE.sub("[phone]", s)
    # 3) ANSI escape 제거 → 그 다음 제어문자 제거(개행 포함) → 한 줄
    s = _ANSI_RE.sub("", s)
    s = _CTRL_RE.sub(" ", s)
    return s.strip()


class _SafeFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        return sanitize_line(base)


# ───────────────────────────── 경로 안전 ─────────────────────────────
def _is_reparse(path: str) -> bool:
    try:
        st = os.lstat(path)
    except OSError:
        return False
    attr = getattr(st, "st_file_attributes", 0)
    flag = getattr(_stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attr & flag)


def default_log_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or os.getcwd()
    return os.path.join(base, "Y_TSBankAuto", "logs")


def _log_dir_safe(d: str) -> bool:
    """사용자 전용 로컬 경로만 허용. UNC/네트워크/reparse 금지."""
    ap = os.path.abspath(d)
    if ap.startswith("\\\\"):
        return False
    parent = os.path.dirname(ap)
    if os.path.isdir(ap) and _is_reparse(ap):
        return False
    if os.path.isdir(parent) and _is_reparse(parent):
        return False
    return True


# ───────────────────────────── 로거 구성 ─────────────────────────────
_LOGGER_NAME = "ytsbank"


def get_logger() -> logging.Logger:
    return logging.getLogger(_LOGGER_NAME)


def configure_logging(*, enable_file: bool = False, log_dir: str | None = None,
                      level: int = logging.INFO) -> logging.Logger:
    """로거 구성. enable_file 은 '안전한 설정일 때만' True 로 호출한다.

    파일 로그 경로가 안전하지 않으면 파일 핸들러를 붙이지 않고 콘솔만 사용한다.
    """
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False
    for h in list(logger.handlers):
        logger.removeHandler(h)

    fmt = _SafeFormatter("%(asctime)s [%(levelname)s] %(message)s")

    # 콘솔(있을 때만; windowed EXE 에서는 stderr 가 None 일 수 있음)
    if sys.stderr is not None:
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        logger.addHandler(ch)

    if enable_file:
        d = log_dir or default_log_dir()
        if _log_dir_safe(d):
            try:
                os.makedirs(d, exist_ok=True)
                fh = logging.handlers.RotatingFileHandler(
                    os.path.join(d, "ytsbank.log"),
                    maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT,
                    encoding="utf-8")
                fh.setFormatter(fmt)
                logger.addHandler(fh)
            except OSError:
                pass   # 파일 로그 불가 시 콘솔만
    return logger


def install_excepthook() -> None:
    """최상위 예외를 안전 코드로만 표면화(원문 traceback 미노출)."""
    logger = get_logger()

    def _hook(exc_type, exc, tb):
        try:
            logger.error("unhandled_exception code=%s", exc_type.__name__)
        except Exception:
            pass

    sys.excepthook = _hook


def disable_faulthandler() -> None:
    """faulthandler 를 기본 비활성으로 보장(자동 활성화되었으면 해제)."""
    try:
        import faulthandler
        if faulthandler.is_enabled():
            faulthandler.disable()
    except Exception:
        pass


def wer_policy_note() -> str:
    """시스템 WER 정책을 읽기 전용으로만 확인해 잔여 위험 메모를 반환(변경하지 않음)."""
    try:
        import winreg
        key = r"SOFTWARE\Microsoft\Windows\Windows Error Reporting\LocalDumps"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key):
            return "WER LocalDumps 정책 존재(크래시 덤프 가능) — 앱은 변경하지 않음"
    except FileNotFoundError:
        return "WER LocalDumps 정책 없음(전역 덤프 미구성)"
    except Exception:
        return "WER 정책 확인 불가(읽기 전용)"
