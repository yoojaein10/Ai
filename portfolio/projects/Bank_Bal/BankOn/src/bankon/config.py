"""실행 설정 로딩.

FTP/SQL 자격증명과 경로는 소스에 하드코딩하지 않고 `.env` 에서 읽는다.
필수 값이 없으면 즉시 예외를 던진다(시스템 경계 검증).

GamJun 과 달리 적재용 DB(target_sql)가 없다. BankOn 은 읽어서 화면에 넣을 뿐
어디에도 저장하지 않는다. `appraisal` DB 는 등기번호 보완용이라 선택 항목이다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

from . import paths


class ConfigError(Exception):
    """필수 설정 누락."""


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"환경변수 {name} 가 설정되지 않았습니다(.env 확인).")
    return value


def _optional(name: str) -> str | None:
    return os.environ.get(name, "").strip() or None


@dataclass(frozen=True)
class SqlConfig:
    server: str
    database: str
    user: str
    password: str
    driver: str = "ODBC Driver 17 for SQL Server"

    def connection_string(self, *, readonly: bool = False) -> str:
        parts = [
            f"DRIVER={{{self.driver}}}",
            f"SERVER={self.server}",
            f"DATABASE={self.database}",
            f"UID={self.user}",
            f"PWD={self.password}",
            "Encrypt=no",
        ]
        if readonly:
            parts.append("ApplicationIntent=ReadOnly")
        return ";".join(parts)


@dataclass(frozen=True)
class FtpConfig:
    host: str
    user: str
    password: str
    passive: bool = True
    remote_root: str = "/Gam"


@dataclass(frozen=True)
class AppConfig:
    """BankOn 실행 설정."""

    source_sql: SqlConfig            # apworksdw (읽기 전용)
    ftp: FtpConfig                   # 감정서 파일 FTP
    gamexport_exe: str               # EasyTable 익스포터 CLI 경로
    work_dir: str                    # 다운로드 임시 폴더
    output_dir: str                  # gamexport 출력 폴더
    business_number: str             # 사업등록번호(본사 고정값)
    loader_cmd: str                  # BANK24 실행 명령(KadcLoader.exe Bank24 -e)
    bankon_user: str                 # 뱅크온라인 로그인 아이디
    bankon_password: str             # 뱅크온라인 로그인 비밀번호
    scan_sql: SqlConfig | None = None  # appraisal DB — 등기번호 보완(없으면 건너뜀)
    dw_sql: SqlConfig | None = None    # GamJun DW — 검증용(FTP 없이 대조)
    keep_source_files: bool = False   # 1=처리 후 원본 유지(디버깅용)
    auto_submit: bool = True          # 1=입력 후 '저 장' 버튼까지 누름(발송 아님)


def load_config(env_path: str | None = None) -> AppConfig:
    """`.env` 를 읽어 설정을 구성한다. 기본 위치는 exe(또는 저장소) 옆 `.env`(paths.ENV_FILE)."""
    load_dotenv(dotenv_path=env_path or (str(paths.ENV_FILE) if paths.ENV_FILE.exists() else None), override=False)
    paths.ensure_dirs()

    dw_database = _optional("TARGET_SQL_DATABASE")
    dw_sql = None
    if dw_database:
        dw_sql = SqlConfig(
            server=_require("TARGET_SQL_SERVER"),
            database=dw_database,
            user=_require("TARGET_SQL_USER"),
            password=_require("TARGET_SQL_PASSWORD"),
        )

    scan_database = _optional("SCAN_SQL_DATABASE")
    scan_sql = None
    if scan_database:
        scan_sql = SqlConfig(
            server=_require("SCAN_SQL_SERVER"),
            database=scan_database,
            user=_require("SCAN_SQL_USER"),
            password=_require("SCAN_SQL_PASSWORD"),
        )

    return AppConfig(
        source_sql=SqlConfig(
            server=_require("SOURCE_SQL_SERVER"),
            database=_require("SOURCE_SQL_DATABASE"),
            user=_require("SOURCE_SQL_USER"),
            password=_require("SOURCE_SQL_PASSWORD"),
        ),
        ftp=FtpConfig(
            host=_require("FTP_HOST"),
            user=_require("FTP_USER"),
            password=_require("FTP_PASSWORD"),
        ),
        # 단일 exe 배포: 비워 두면 번들된 gamexport.exe 와 exe 옆 work/·output/ 을 쓴다(2026-08-31)
        gamexport_exe=_optional("GAMEXPORT_EXE") or str(paths.GAMEXPORT_EXE),
        work_dir=_optional("WORK_DIR") or str(paths.WORK_DIR),
        output_dir=_optional("OUTPUT_DIR") or str(paths.OUTPUT_DIR),
        business_number=_require("BUSINESS_NUMBER"),
        loader_cmd=_require("BANKON_LOADER_CMD"),
        bankon_user=_require("BANKON_USER"),
        bankon_password=_require("BANKON_PASSWORD"),
        scan_sql=scan_sql,
        dw_sql=dw_sql,
        keep_source_files=os.environ.get("KEEP_SOURCE_FILES", "0").strip() == "1",
        auto_submit=os.environ.get("AUTO_SUBMIT", "1").strip() == "1",
    )
