from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from notice_app.sms import normalize_sender_phone


@dataclass(frozen=True)
class AppConfig:
    root: Path
    db_server: str
    db_name: str
    db_user: str
    db_password: str
    odbc_driver: str
    db_encrypt: str
    db_trust_server_certificate: str
    call_from: str
    recipient_db_name: str
    message_path: Path
    subject_path: Path
    calendar_overrides_path: Path
    state_db_path: Path
    log_path: Path
    connection_timeout_seconds: int
    query_timeout_seconds: int

    @classmethod
    def load(
        cls,
        root: Path,
        *,
        require_recipients: bool = True,
        require_credentials: bool = True,
    ) -> "AppConfig":
        config_path = root / "config.json"
        if not config_path.exists():
            config_path = root / "config.example.json"
        raw = json.loads(config_path.read_text(encoding="utf-8"))

        required_env = {
            "db_server": "SMS_DB_SERVER",
            "db_name": "SMS_DB_NAME",
            "db_user": "SMS_DB_USER",
            "db_password": "SMS_DB_PASSWORD",
            "call_from": "SMS_CALL_FROM",
        }
        values: dict[str, str] = {}
        missing: list[str] = []
        for field, env_name in required_env.items():
            value = os.environ.get(env_name, "").strip()
            if not value:
                missing.append(env_name)
            values[field] = value
        if require_credentials and missing:
            raise ValueError("필수 환경변수가 없습니다: " + ", ".join(missing))
        if values["call_from"]:
            values["call_from"] = normalize_sender_phone(values["call_from"])

        recipient_db_name = os.environ.get("SMS_RECIPIENT_DB_NAME", "").strip()
        if require_recipients and not recipient_db_name:
            raise ValueError("필수 환경변수가 없습니다: SMS_RECIPIENT_DB_NAME")
        if recipient_db_name and not recipient_db_name.replace("_", "").isalnum():
            raise ValueError("SMS_RECIPIENT_DB_NAME 설정이 올바르지 않습니다.")

        encrypt = os.environ.get("SMS_DB_ENCRYPT", "yes").strip().lower()
        trust = os.environ.get("SMS_DB_TRUST_SERVER_CERTIFICATE", "no").strip().lower()
        if encrypt not in ("yes", "no", "mandatory", "optional", "strict"):
            raise ValueError("SMS_DB_ENCRYPT 설정이 올바르지 않습니다.")
        if trust not in ("yes", "no"):
            raise ValueError("SMS_DB_TRUST_SERVER_CERTIFICATE 설정이 올바르지 않습니다.")

        def resolve(key: str) -> Path:
            value = Path(str(raw[key]))
            return value if value.is_absolute() else root / value

        return cls(
            root=root,
            recipient_db_name=recipient_db_name,
            message_path=resolve("message_path"),
            subject_path=resolve("subject_path"),
            calendar_overrides_path=resolve("calendar_overrides_path"),
            state_db_path=resolve("state_db_path"),
            log_path=resolve("log_path"),
            connection_timeout_seconds=int(raw.get("connection_timeout_seconds", 10)),
            query_timeout_seconds=int(raw.get("query_timeout_seconds", 30)),
            odbc_driver=os.environ.get("SMS_ODBC_DRIVER", "ODBC Driver 18 for SQL Server").strip(),
            db_encrypt=encrypt,
            db_trust_server_certificate=trust,
            **values,
        )
