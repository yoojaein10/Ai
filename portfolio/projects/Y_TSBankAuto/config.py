# -*- coding: utf-8 -*-
"""설정 로딩 (S1, S5, S13).

- Bank24 ID/PW는 사용자 선택에 따라 settings.ini [login]에서 읽는다.
- DB 자격증명은 기존 keyring/전용 환경변수 방식과 fail-closed를 유지한다.
- 설정값은 로그/repr에 출력하지 않는다.
"""
from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, field

# 환경변수 이름 (시크릿)
ENV_DB_PASSWORD = "YTS_DB_PASSWORD"
ENV_DB_USER = "YTS_DB_USER"
ENV_BANK24_ID = "YTS_BANK24_ID"
ENV_BANK24_PASSWORD = "YTS_BANK24_PASSWORD"
ENV_ALLOW_COMMIT = "YTS_ALLOW_COMMIT"
# 비시크릿이지만 env 로도 덮어쓸 수 있는 것들
ENV_DB_SERVER = "YTS_DB_SERVER"
ENV_DB_PORT = "YTS_DB_PORT"
ENV_DB_NAME = "YTS_DB_NAME"
ENV_LOOKUP_DB_SERVER = "YTS_LOOKUP_DB_SERVER"

KEYRING_SERVICE = "Y_TSBankAuto"

COMMIT_MAGIC = "I_UNDERSTAND_PRODUCTION_WRITE"

# SP 고정 호출 상수
SP_OFFICE = "10"
SP_APP_CODE = "300611"


class ConfigError(Exception):
    """설정/시크릿 로딩 실패 (fail-closed)."""


class SecretProvider:
    """시크릿 조회 추상화. 기본 구현은 keyring→env. 테스트는 FakeSecretProvider 주입."""

    def get_secret(self, name: str) -> str | None:
        # 1) keyring 우선
        try:
            import keyring  # 선택 의존성
        except Exception:
            keyring = None
        if keyring is not None:
            try:
                val = keyring.get_password(KEYRING_SERVICE, name)
            except Exception:
                val = None
            if val:
                return val
        # 2) 전용 환경변수 (시크릿)
        val = os.environ.get(name)
        if val:
            return val
        return None


@dataclass
class DbConfig:
    enabled: bool = False
    server: str = ""
    port: str = "1433"
    database: str = ""
    driver: str = "ODBC Driver 18 for SQL Server"
    encrypt: str = ""
    trust_server_certificate: str = "true"
    username: str = field(default="", repr=False)
    password: str = field(default="", repr=False)
    lookup_server: str = ""

    def odbc_parts_nonsecret(self) -> dict:
        """비시크릿 ODBC 파트만. UID/PWD 는 포함하지 않는다."""
        parts = {
            "DRIVER": f"{{{self.driver}}}",
            "SERVER": f"{self.server},{self.port}" if self.port else self.server,
            "DATABASE": self.database,
            "TrustServerCertificate": (
                "yes" if str(self.trust_server_certificate).strip().lower()
                in ("1", "true", "yes", "on") else "no"),
        }
        if self.encrypt:
            parts["Encrypt"] = self.encrypt
        return parts


@dataclass
class Allowlist:
    servers: tuple[str, ...] = ()
    databases: tuple[str, ...] = ()

    def server_ok(self, name: str) -> bool:
        return name in self.servers

    def database_ok(self, name: str) -> bool:
        return name in self.databases


@dataclass
class Paths:
    pdf_root: str = ""
    log_dir: str = ""
    output_dir: str = ""
    retention_days: int = 90


@dataclass
class Safety:
    rollback_test: bool = True
    autocommit: bool = False
    allow_commit: bool = False


@dataclass
class Login:
    """settings.ini [login]에서 읽는 Bank24 로그인 설정."""
    save_credentials: bool = False
    bank24_id: str = ""
    bank24_pw: str = field(default="", repr=False)


@dataclass
class BankOnline:
    enabled: bool = False
    endpoint: str = ""
    method: str = "POST"
    request_format: str = "json"
    timeout_seconds: float = 10.0
    allow_http: bool = False
    authorization: str = field(default="", repr=False)
    token_endpoint: str = "https://authtoken.kapanet.or.kr/AuthServer"
    kapa_user_name: str = "\uc774\uc77c\uc6b0"
    success_field: str = "success"
    success_value: str = "true"


# Y_BankAuto 와 동일: Bank24 실행 경로/메인 창 클래스는 코드 상수로 고정한다(§1).
# INI [bank24] 에서 받지 않으며, INI 에 [bank24] 가 있어도 실행 경로·창 클래스 결정에
# 사용하지 않는다(§13). 값은 비민감(경로/클래스)이며 자격증명이 아니다.
BANK24_EXE_PATH = r"C:\KADC\X11\Bank24.exe"
BANK24_MAIN_WINDOW_CLASS = "TfrmMain"


@dataclass
class Bank24:
    """실제 Bank24 연결 설정. exe_path/main_window_class 는 코드 상수 기본값을 쓰고
    INI 에서 덮어쓰지 않는다(§1/§13). 기존 프로세스 재사용/미실행 시 실행은 항상 허용한다."""
    exe_path: str = BANK24_EXE_PATH
    main_window_class: str = BANK24_MAIN_WINDOW_CLASS
    attach_existing: bool = True
    launch_if_missing: bool = True


@dataclass
class Options:
    read_only: bool = True

    def __post_init__(self):
        tab = "".join(str(self.source_tab or "").split())
        if tab not in {"\ubbf8\uc811\uc218", "\uc791\uc131"}:
            self.source_tab = "\ubbf8\uc811\uc218"
    source_tab: str = "탁상"


# [bank24] 섹션을 요구하지 않는다(§2/§3). 실행 경로/창 클래스는 코드 상수이므로 필수 키 없음.
Options.source_tab = "\ubbf8\uc811\uc218"

REQUIRED_BANK24_KEYS = ()


@dataclass
class AppConfig:
    db: DbConfig = field(default_factory=DbConfig)
    allowlist: Allowlist = field(default_factory=Allowlist)
    paths: Paths = field(default_factory=Paths)
    safety: Safety = field(default_factory=Safety)
    login: Login = field(default_factory=Login)
    bank24: Bank24 = field(default_factory=Bank24)
    options: Options = field(default_factory=Options)
    bankonline: BankOnline = field(default_factory=BankOnline)
    office: str = SP_OFFICE
    app_code: str = SP_APP_CODE
    reghist_table: str = "APW_RegHist"


def _as_bool(v, default: bool = False) -> bool:
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _split_csv(v: str) -> tuple[str, ...]:
    return tuple(x.strip() for x in (v or "").split(",") if x.strip())


def load_app_config(ini_path: str) -> AppConfig:
    """settings.ini(비시크릿)에서 AppConfig 로드. 시크릿은 읽지 않는다."""
    cfg = configparser.ConfigParser()
    cfg.optionxform = str  # 키 대소문자 보존
    read = cfg.read(ini_path, encoding="utf-8")
    if not read:
        raise ConfigError(f"설정 파일을 읽을 수 없음: {ini_path}")

    app = AppConfig()

    if cfg.has_section("database"):
        d = cfg["database"]
        app.db = DbConfig(
            enabled=_as_bool(d.get("enabled"), False),
            server=os.environ.get(ENV_DB_SERVER) or d.get("server", ""),
            port=os.environ.get(ENV_DB_PORT) or d.get("port", "1433"),
            database=os.environ.get(ENV_DB_NAME) or d.get("database", ""),
            driver=d.get("driver", "ODBC Driver 18 for SQL Server"),
            encrypt=d.get("encrypt", ""),
            trust_server_certificate=d.get("trust_server_certificate", "true"),
            username=d.get("username", "").strip(),
            password=d.get("password", ""),
            lookup_server=os.environ.get(ENV_LOOKUP_DB_SERVER) or d.get("lookup_server", ""),
        )

    if cfg.has_section("allowlist"):
        a = cfg["allowlist"]
        app.allowlist = Allowlist(
            servers=_split_csv(a.get("servers", "")),
            databases=_split_csv(a.get("databases", "")),
        )

    if cfg.has_section("paths"):
        p = cfg["paths"]
        try:
            retention = int(p.get("retention_days", "90"))
        except ValueError:
            retention = 90
        app.paths = Paths(
            pdf_root=p.get("pdf_root", ""),
            log_dir=p.get("log_dir", ""),
            output_dir=p.get("output_dir", ""),
            retention_days=retention,
        )

    if cfg.has_section("safety"):
        s = cfg["safety"]
        app.safety = Safety(
            rollback_test=_as_bool(s.get("rollback_test"), True),
            autocommit=_as_bool(s.get("autocommit"), False),
            allow_commit=_as_bool(s.get("allow_commit"), False),
        )

    if cfg.has_section("login"):
        login = cfg["login"]
        app.login = Login(
            save_credentials=_as_bool(login.get("save_credentials"), False),
            bank24_id=login.get("bank24_id", "").strip(),
            bank24_pw=login.get('REDACTED_CONFIGURE_LOCALLY', ""),
        )

    if cfg.has_section("bankonline"):
        bo = cfg["bankonline"]
        try:
            timeout_seconds = float(bo.get("timeout_seconds", "10") or 10)
        except ValueError:
            timeout_seconds = 10.0
        app.bankonline = BankOnline(
            enabled=_as_bool(bo.get("enabled"), False),
            endpoint=bo.get("endpoint", "").strip(),
            method=bo.get("method", "POST").strip() or "POST",
            request_format=bo.get("request_format", "json").strip() or "json",
            timeout_seconds=timeout_seconds,
            allow_http=_as_bool(bo.get("allow_http"), False),
            authorization=bo.get("authorization", ""),
            token_endpoint=bo.get(
                "token_endpoint",
                "https://authtoken.kapanet.or.kr/AuthServer",
            ).strip() or "https://authtoken.kapanet.or.kr/AuthServer",
            kapa_user_name=bo.get("kapa_user_name", "\uc774\uc77c\uc6b0").strip() or "\uc774\uc77c\uc6b0",
            success_field=bo.get("success_field", "success").strip() or "success",
            success_value=bo.get("success_value", "true").strip() or "true",
        )

    # [bank24] 섹션은 실행 경로/창 클래스 결정에 사용하지 않는다(§13). 코드 상수를 쓰므로
    # 여기서 파싱하지 않는다. app.bank24 는 코드 상수 기본값을 유지한다.

    if cfg.has_section("options"):
        o = cfg["options"]
        app.options = Options(
            read_only=_as_bool(o.get("read_only"), True),
            source_tab=o.get("source_tab", "탁상").strip() or "탁상",
        )

    if cfg.has_section("sp"):
        sp = cfg["sp"]
        app.office = sp.get("office", SP_OFFICE)
        app.app_code = sp.get("app_code", SP_APP_CODE)

    if cfg.has_section("reghist"):
        app.reghist_table = cfg["reghist"].get("table", "APW_RegHist")

    return app


def missing_bank24_keys(app: "AppConfig") -> list[str]:
    """실제 실행에 필요한 [bank24] 필수값 중 빈 것의 키 이름만 반환(§8). 값은 미포함."""
    b = app.bank24
    missing = []
    for key in REQUIRED_BANK24_KEYS:
        val = getattr(b, key, "")
        if not val:                       # "" 또는 빈 튜플
            missing.append(key)
    return missing


def require_db_credentials(provider: SecretProvider) -> tuple[str, str]:
    """DB UID/PWD 를 시크릿 제공자에서 조회. 없으면 fail-closed(ConfigError).

    빈 비밀번호/익명 접속 금지. 반환값은 호출 즉시 사용하고 보관하지 않는다.
    """
    user = provider.get_secret(ENV_DB_USER)
    pwd = provider.get_secret(ENV_DB_PASSWORD)
    if not user:
        raise ConfigError("DB 사용자 시크릿이 없음 (fail-closed)")
    if not pwd:
        raise ConfigError("DB 비밀번호 시크릿이 없음 (빈 비밀번호/익명 금지, fail-closed)")
    return user, pwd


def commit_env_ok() -> bool:
    """YTS_ALLOW_COMMIT 환경변수가 정확한 매직값인지."""
    return os.environ.get(ENV_ALLOW_COMMIT, "") == COMMIT_MAGIC
