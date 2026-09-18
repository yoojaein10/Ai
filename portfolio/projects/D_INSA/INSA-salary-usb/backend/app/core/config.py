from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "INSA"
    API_V1_PREFIX: str = "/api/v1"

    # MSSQL - 인사 DB
    DB_HOST: str = "localhost"
    DB_PORT: int = 1433
    DB_NAME: str = "insa"
    DB_USER: str = "sa"
    DB_PASSWORD: str = ""
    DB_DRIVER: str = "ODBC Driver 17 for SQL Server"

    @property
    def database_url(self) -> str:
        return (
            f"mssql+pyodbc://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
            f"?driver={self.DB_DRIVER.replace(' ', '+')}"
        )

    # MSSQL - 근태 DB (ACSDB, read-only 연동)
    ATT_DB_HOST: str = ""
    ATT_DB_PORT: int = 1433
    ATT_DB_NAME: str = ""
    ATT_DB_USER: str = ""
    ATT_DB_PASSWORD: str = ""
    ATT_DB_DRIVER: str = "ODBC Driver 17 for SQL Server"

    @property
    def attendance_database_url(self) -> str:
        return (
            f"mssql+pyodbc://{self.ATT_DB_USER}:{self.ATT_DB_PASSWORD}"
            f"@{self.ATT_DB_HOST}:{self.ATT_DB_PORT}/{self.ATT_DB_NAME}"
            f"?driver={self.ATT_DB_DRIVER.replace(' ', '+')}"
        )

    # MSSQL - 업무시스템 DB (apworksdw: 연차/출장, read-only 연동)
    APW_DB_HOST: str = ""
    APW_DB_PORT: int = 1433
    APW_DB_NAME: str = ""
    APW_DB_USER: str = ""
    APW_DB_PASSWORD: str = ""
    APW_DB_DRIVER: str = "ODBC Driver 17 for SQL Server"
    # 연봉 금고 좌석 IP 규칙: 담당자 PC IP = SALARY_SEAT_IP_PREFIX + SEAT_USERINFO.UID
    SALARY_SEAT_IP_PREFIX: str = "10.40.0."
    # 서버 자신의 LAN IP(비우면 자동 감지). 루프백 접속을 이 IP로 본다.
    SERVER_LAN_IP: str = ""

    @property
    def apworks_database_url(self) -> str:
        return (
            f"mssql+pyodbc://{self.APW_DB_USER}:{self.APW_DB_PASSWORD}"
            f"@{self.APW_DB_HOST}:{self.APW_DB_PORT}/{self.APW_DB_NAME}"
            f"?driver={self.APW_DB_DRIVER.replace(' ', '+')}"
        )

    # JWT
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:5173"]

    # Encryption (AES-256 for bank accounts)
    AES_KEY: str = ""

    # Scheduler (PHASE 14: leave accrual + yearly reset)
    SCHEDULER_ENABLED: bool = False
    SCHEDULER_TIMEZONE: str = "Asia/Seoul"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
