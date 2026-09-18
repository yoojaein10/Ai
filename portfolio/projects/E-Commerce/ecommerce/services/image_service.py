from utils.logger import logger


class ImageService:
    async def download_and_rehost(self, image_urls: list[str]) -> list[str]:
        """원본 이미지를 다운로드하고 리호스팅합니다. (Mock)"""
        logger.info(f"이미지 {len(image_urls)}건 처리 시작")

        # TODO: 실제 구현 - S3/클라우드 스토리지 업로드
        rehosted = [
            url.replace("img.1688.com", "cdn.myshop.kr") for url in image_urls
        ]

        logger.info(f"이미지 리호스팅 완료: {len(rehosted)}건")
        return rehosted


def get_image_service() -> ImageService:
    return ImageService()
