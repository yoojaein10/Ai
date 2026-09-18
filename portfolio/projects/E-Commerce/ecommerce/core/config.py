from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "ecommerce-automation"
    APP_ENV: str = "development"
    DEBUG: bool = True
    DATABASE_URL: str = 'postgresql://ecommerce_user:REDACTED_CONFIGURE_LOCALLY@localhost:5432/ecommerce_db'
    TRANSLATION_API_KEY: str = ""
    COUPANG_ACCESS_KEY: str = ""
    COUPANG_SECRET_KEY: str = ""
    COUPANG_VENDOR_ID: str = ""
    SMARTSTORE_CLIENT_ID: str = ""
    SMARTSTORE_CLIENT_SECRET: str = ""
    GEMINI_API_KEY: str = ""
    NAVER_CLIENT_ID: str = ""
    NAVER_CLIENT_SECRET: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
