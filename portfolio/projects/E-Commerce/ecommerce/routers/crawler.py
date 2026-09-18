from fastapi import APIRouter, Depends

from schemas.product_schema import CrawlRequest, CrawlResponse
from services.crawler_service import CrawlerService, get_crawler_service
from services.translation_service import TranslationService, get_translation_service

router = APIRouter(prefix="/crawler", tags=["Crawler"])


@router.post("/1688", response_model=CrawlResponse)
async def crawl_1688(
    request: CrawlRequest,
    crawler: CrawlerService = Depends(get_crawler_service),
    translator: TranslationService = Depends(get_translation_service),
):
    raw_data = await crawler.crawl_1688(request.url)
    translated = await translator.translate_product(raw_data)
    return translated
