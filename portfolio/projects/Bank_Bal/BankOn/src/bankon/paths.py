"""실행 경로 — 소스 실행과 단일 exe(PyInstaller onefile) 실행을 한 곳에서 가른다(2026-08-31).

BUNDLE   읽기 전용 자원(recon/*.md 콤보 목록, delphi/gamexport.exe). exe 면 압축이 풀린 임시 폴더(sys._MEIPASS),
         소스 실행이면 저장소 루트(BankOn/).
APP_ROOT 쓰기 폴더 — .env, gui_settings.ini, work/, output/, reports/. exe 면 **exe 가 있는 폴더**, 소스 실행이면 저장소 루트.

배포 = BankOn.exe + .env + gui_settings.ini 세 파일. 업데이트는 exe 만 교체한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
_REPO = Path(__file__).resolve().parents[2]

BUNDLE = Path(getattr(sys, "_MEIPASS", _REPO)) if FROZEN else _REPO
APP_ROOT = Path(sys.executable).resolve().parent if FROZEN else _REPO

RECON_DIR = BUNDLE / "recon"
GAMEXPORT_EXE = BUNDLE / "delphi" / "delphi" / "gamexport.exe"
ENV_FILE = APP_ROOT / ".env"
REPORTS_DIR = APP_ROOT / "reports"
WORK_DIR = APP_ROOT / "work"
OUTPUT_DIR = APP_ROOT / "output"


def ensure_dirs() -> None:
    for d in (REPORTS_DIR, WORK_DIR, OUTPUT_DIR):
        d.mkdir(parents=True, exist_ok=True)
