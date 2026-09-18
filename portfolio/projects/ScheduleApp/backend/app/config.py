"""
Application configuration via pydantic-settings.
Reads from .env file or environment variables.
"""
import json
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    DB_SERVER: str = "localhost"
    DB_NAME: str = "apworksdw"
    DB_USER: str = "sa"
    DB_PASSWORD: str = ""
    DB_DRIVER: str = "ODBC Driver 17 for SQL Server"

    # CORS
    CORS_ORIGINS: str = "*"

    # Kakao
    KAKAO_REST_API_KEY: str = ""

    # Daou Office
    DAOU_CLIENT_ID: str = ""
    DAOU_CLIENT_SECRET: str = ""
    DAOU_TOKEN: str = ""
    DAOU_USERNAME: str = ""
    DAOU_PASSWORD: str = ""
    DAOU_LOGIN_URL: str = "https://gw.dhapp.co.kr/api/login"
    DAOU_SEND_URL: str = "https://gw.dhapp.co.kr/api/chat/pubsubs/external"

    @property
    def cors_origins_list(self) -> List[str]:
        if self.CORS_ORIGINS.strip() == "*":
            return ["*"]
        try:
            return json.loads(self.CORS_ORIGINS)
        except (json.JSONDecodeError, TypeError):
            return ["*"]

    @property
    def db_connection_string(self) -> str:
        return (
            f"DRIVER={{{self.DB_DRIVER}}};"
            f"SERVER={self.DB_SERVER};"
            f"DATABASE={self.DB_NAME};"
            f"UID={self.DB_USER};"
            f"PWD={self.DB_PASSWORD};"
            "TrustServerCertificate=yes;"
        )


settings = Settings()
