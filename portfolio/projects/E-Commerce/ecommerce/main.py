import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가 (상대 import 해결)
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI

from core.config import settings
from core.exceptions import AppException, app_exception_handler, generic_exception_handler
from database.session import Base, engine
from utils.logger import logger

# 모든 모델 import → metadata에 등록
from models.product import Product  # noqa: F401
from models.order import Order  # noqa: F401

# DB 테이블 자동 생성
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.APP_NAME,
    description="도매매/오너클랜 위탁판매 자동화 ERP API",
    version="0.2.0",
)

# 전역 예외 핸들러
app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)

# 라우터 등록
from routers import health, crawler, image, upload, collector

app.include_router(health.router)
app.include_router(crawler.router)
app.include_router(image.router)
app.include_router(upload.router)
app.include_router(collector.router)


@app.get("/")
async def root():
    return {"message": "ecommerce automation server running"}


@app.on_event("startup")
async def startup():
    logger.info(f"{settings.APP_NAME} 서버 시작 (env={settings.APP_ENV})")
    logger.info("DB 테이블 자동 생성 완료")


@app.on_event("shutdown")
async def shutdown():
    logger.info("서버 종료")
