from fastapi import Request
from fastapi.responses import JSONResponse
from utils.logger import logger


class AppException(Exception):
    def __init__(self, status_code: int = 500, detail: str = "서버 내부 오류"):
        self.status_code = status_code
        self.detail = detail


class CrawlerException(AppException):
    def __init__(self, detail: str = "크롤링 중 오류가 발생했습니다"):
        super().__init__(status_code=502, detail=detail)


class TranslationException(AppException):
    def __init__(self, detail: str = "번역 중 오류가 발생했습니다"):
        super().__init__(status_code=500, detail=detail)


class UploadException(AppException):
    def __init__(self, detail: str = "상품 업로드 중 오류가 발생했습니다"):
        super().__init__(status_code=500, detail=detail)


class CollectorException(AppException):
    def __init__(self, detail: str = "상품 수집 중 오류가 발생했습니다"):
        super().__init__(status_code=502, detail=detail)


async def app_exception_handler(request: Request, exc: AppException):
    logger.error(f"[{exc.status_code}] {request.method} {request.url} - {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail},
    )


async def generic_exception_handler(request: Request, exc: Exception):
    logger.error(f"[500] {request.method} {request.url} - {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "서버 내부 오류가 발생했습니다"},
    )
