"""통합 상품 업로드 서비스 — 쿠팡/스마트스토어 연동 통합 관리"""

from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from services.coupang_service import get_coupang_service
from services.smartstore_service import get_smartstore_service
from utils.logger import logger


class UploadService:
    """플랫폼별 서비스를 통합하여 상품 등록/수정/삭제를 처리"""

    def __init__(self):
        self._coupang = get_coupang_service()
        self._smartstore = get_smartstore_service()

    @property
    def coupang_mock(self) -> bool:
        return self._coupang.is_mock_mode

    @property
    def smartstore_mock(self) -> bool:
        return self._smartstore.is_mock_mode

    def status_summary(self) -> dict:
        """각 플랫폼 연동 상태 반환"""
        return {
            "coupang": "Mock" if self.coupang_mock else "Live",
            "smartstore": "Mock" if self.smartstore_mock else "Live",
        }

    async def register(self, platform: str, product_data: dict, db: Session, product_id: int) -> dict:
        """상품 등록 후 등록 이력을 DB에 저장"""
        if platform == "coupang":
            result = await self._coupang.register_product(product_data)
        elif platform == "smartstore":
            result = await self._smartstore.register_product(product_data)
        else:
            return {"status": "error", "message": f"지원하지 않는 플랫폼: {platform}"}

        # 등록 이력 DB 저장
        status = "REGISTERED" if result["status"] == "success" else "FAILED"
        db.execute(
            text(
                "INSERT INTO product_registrations "
                "(product_id, platform, status, platform_product_id, platform_url, "
                "error_message, registered_at, created_at) "
                "VALUES (:pid, :plat, :st, :ppid, :url, :err, :rat, NOW())"
            ),
            {
                "pid": product_id,
                "plat": platform.upper(),
                "st": status,
                "ppid": result.get("platform_product_id") or "",
                "url": result.get("url") or "",
                "err": result.get("message") if status == "FAILED" else None,
                "rat": datetime.now(timezone.utc) if status == "REGISTERED" else None,
            },
        )
        db.commit()

        logger.info(
            f"[UploadService] {platform} 등록 {'성공' if status == 'REGISTERED' else '실패'}: "
            f"product_id={product_id}"
        )
        return result

    async def delete(self, platform: str, platform_product_id: str, db: Session, registration_id: int) -> dict:
        """상품 삭제 후 등록 이력 업데이트"""
        if platform == "coupang":
            result = await self._coupang.delete_product(platform_product_id)
        elif platform == "smartstore":
            result = await self._smartstore.delete_product(platform_product_id)
        else:
            return {"status": "error", "message": f"지원하지 않는 플랫폼: {platform}"}

        if result["status"] == "success":
            db.execute(
                text("UPDATE product_registrations SET status = 'DELETED' WHERE id = :id"),
                {"id": registration_id},
            )
            db.commit()

        return result


def get_upload_service() -> UploadService:
    return UploadService()
