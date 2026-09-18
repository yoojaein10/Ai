"""
네이버 스마트스토어 커머스 API 연동 서비스

OAuth2 클라이언트 인증 기반으로 상품 등록/수정/삭제를 처리한다.
API 키가 없으면 Mock 모드로 자동 전환되어 개발/테스트 환경을 지원한다.
"""

import asyncio
import os
import time
import uuid
from typing import Optional

import httpx

from utils.logger import logger

# --- 환경변수 기반 설정 ---
SMARTSTORE_CLIENT_ID = os.getenv("SMARTSTORE_CLIENT_ID", "")
SMARTSTORE_CLIENT_SECRET = os.getenv("SMARTSTORE_CLIENT_SECRET", "")

# --- 네이버 커머스 API 엔드포인트 ---
AUTH_URL = "https://api.commerce.naver.com/external/v1/oauth2/token"
PRODUCTS_URL = "https://api.commerce.naver.com/external/v2/products"

# --- 토큰 캐시 유효 시간 (초) ---
TOKEN_EXPIRY_BUFFER = 60  # 만료 60초 전에 갱신


class SmartStoreService:
    """네이버 스마트스토어 커머스 API 서비스"""

    def __init__(self):
        self._client_id: str = SMARTSTORE_CLIENT_ID
        self._client_secret: str = SMARTSTORE_CLIENT_SECRET
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self._mock_counter: int = 0  # Mock 모드 상품 ID 순번

    # ------------------------------------------------------------------ #
    #  모드 판별
    # ------------------------------------------------------------------ #

    @property
    def is_mock_mode(self) -> bool:
        """API 키가 비어 있으면 Mock 모드로 동작한다."""
        return not self._client_id or not self._client_secret

    # ------------------------------------------------------------------ #
    #  OAuth2 토큰 관리
    # ------------------------------------------------------------------ #

    async def _get_access_token(self) -> str:
        """
        OAuth2 client_credentials 방식으로 액세스 토큰을 발급받는다.
        캐시된 토큰이 유효하면 재사용하고, 만료 임박 시 자동 갱신한다.
        """
        # 캐시된 토큰이 아직 유효한 경우
        if self._access_token and time.time() < self._token_expires_at:
            return self._access_token

        logger.info("스마트스토어 OAuth2 토큰 발급 요청")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    AUTH_URL,
                    data={
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "grant_type": "client_credentials",
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                response.raise_for_status()
                token_data = response.json()

            self._access_token = token_data["access_token"]
            # expires_in(초) 기준으로 만료 시각 계산 (버퍼 적용)
            expires_in = token_data.get("expires_in", 3600)
            self._token_expires_at = time.time() + expires_in - TOKEN_EXPIRY_BUFFER

            logger.info(
                f"스마트스토어 토큰 발급 완료 (유효: {expires_in}초)"
            )
            return self._access_token

        except httpx.HTTPStatusError as e:
            logger.error(f"스마트스토어 토큰 발급 실패: HTTP {e.response.status_code}")
            raise
        except Exception as e:
            logger.error(f"스마트스토어 토큰 발급 중 오류: {e}")
            raise

    # ------------------------------------------------------------------ #
    #  상품 등록
    # ------------------------------------------------------------------ #

    async def register_product(self, product_data: dict) -> dict:
        """
        상품을 스마트스토어에 등록한다.

        Args:
            product_data: title, cost_price, sale_price, category,
                          description, image_url, stock 필드를 포함하는 dict

        Returns:
            status, platform_product_id, url, message 를 담은 dict
        """
        title = product_data.get("title", "")
        logger.info(f"스마트스토어 상품 등록 시작: {title}")

        if self.is_mock_mode:
            return await self._mock_register(product_data)

        try:
            token = await self._get_access_token()
            payload = self._build_product_payload(product_data)

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    PRODUCTS_URL,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                )
                response.raise_for_status()
                result = response.json()

            product_id = str(result.get("smartstoreChannelProductNo", ""))
            logger.info(f"스마트스토어 상품 등록 완료: {product_id}")

            return {
                "status": "success",
                "platform_product_id": product_id,
                "url": f"https://smartstore.naver.com/products/{product_id}",
                "message": "스마트스토어 상품 등록 완료",
            }

        except httpx.HTTPStatusError as e:
            error_msg = f"상품 등록 실패: HTTP {e.response.status_code}"
            logger.error(f"스마트스토어 {error_msg} - {e.response.text}")
            return {
                "status": "error",
                "platform_product_id": None,
                "url": None,
                "message": error_msg,
            }
        except Exception as e:
            logger.error(f"스마트스토어 상품 등록 중 오류: {e}")
            return {
                "status": "error",
                "platform_product_id": None,
                "url": None,
                "message": str(e),
            }

    # ------------------------------------------------------------------ #
    #  상품 수정
    # ------------------------------------------------------------------ #

    async def update_product(
        self, platform_product_id: str, product_data: dict
    ) -> dict:
        """
        등록된 상품 정보를 수정한다.

        Args:
            platform_product_id: 스마트스토어 상품 번호
            product_data: 수정할 필드를 포함하는 dict

        Returns:
            status, platform_product_id, url, message 를 담은 dict
        """
        logger.info(f"스마트스토어 상품 수정 시작: {platform_product_id}")

        if self.is_mock_mode:
            return await self._mock_update(platform_product_id, product_data)

        try:
            token = await self._get_access_token()
            payload = self._build_product_payload(product_data)

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.put(
                    f"{PRODUCTS_URL}/{platform_product_id}",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                )
                response.raise_for_status()

            logger.info(f"스마트스토어 상품 수정 완료: {platform_product_id}")

            return {
                "status": "success",
                "platform_product_id": platform_product_id,
                "url": f"https://smartstore.naver.com/products/{platform_product_id}",
                "message": "스마트스토어 상품 수정 완료",
            }

        except httpx.HTTPStatusError as e:
            error_msg = f"상품 수정 실패: HTTP {e.response.status_code}"
            logger.error(f"스마트스토어 {error_msg} - {e.response.text}")
            return {
                "status": "error",
                "platform_product_id": platform_product_id,
                "url": None,
                "message": error_msg,
            }
        except Exception as e:
            logger.error(f"스마트스토어 상품 수정 중 오류: {e}")
            return {
                "status": "error",
                "platform_product_id": platform_product_id,
                "url": None,
                "message": str(e),
            }

    # ------------------------------------------------------------------ #
    #  상품 삭제
    # ------------------------------------------------------------------ #

    async def delete_product(self, platform_product_id: str) -> dict:
        """
        등록된 상품을 삭제(비활성화)한다.

        Args:
            platform_product_id: 스마트스토어 상품 번호

        Returns:
            status, platform_product_id, url, message 를 담은 dict
        """
        logger.info(f"스마트스토어 상품 삭제 시작: {platform_product_id}")

        if self.is_mock_mode:
            return await self._mock_delete(platform_product_id)

        try:
            token = await self._get_access_token()

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.delete(
                    f"{PRODUCTS_URL}/{platform_product_id}",
                    headers={
                        "Authorization": f"Bearer {token}",
                    },
                )
                response.raise_for_status()

            logger.info(f"스마트스토어 상품 삭제 완료: {platform_product_id}")

            return {
                "status": "success",
                "platform_product_id": platform_product_id,
                "url": None,
                "message": "스마트스토어 상품 삭제 완료",
            }

        except httpx.HTTPStatusError as e:
            error_msg = f"상품 삭제 실패: HTTP {e.response.status_code}"
            logger.error(f"스마트스토어 {error_msg} - {e.response.text}")
            return {
                "status": "error",
                "platform_product_id": platform_product_id,
                "url": None,
                "message": error_msg,
            }
        except Exception as e:
            logger.error(f"스마트스토어 상품 삭제 중 오류: {e}")
            return {
                "status": "error",
                "platform_product_id": platform_product_id,
                "url": None,
                "message": str(e),
            }

    # ------------------------------------------------------------------ #
    #  페이로드 빌드
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_product_payload(product_data: dict) -> dict:
        """
        product_data를 네이버 커머스 API v2 형식으로 변환한다.

        네이버 API 스펙에 맞춰 originProduct 구조를 생성한다.
        실제 운영 시 카테고리 매핑, 옵션, 배송 정보 등 확장이 필요하다.
        """
        return {
            "originProduct": {
                "statusType": "SALE",
                "name": product_data.get("title", ""),
                "detailContent": product_data.get("description", ""),
                "images": {
                    "representativeImage": {
                        "url": product_data.get("image_url", ""),
                    },
                },
                "salePrice": int(product_data.get("sale_price", 0)),
                "stockQuantity": int(product_data.get("stock", 0)),
                "leafCategoryId": product_data.get("category", ""),
                "detailAttribute": {
                    "purchaseQuantityInfo": {
                        "minPurchaseQuantity": 1,
                        "maxPurchaseQuantity": 999,
                    },
                },
            },
            "smartstoreChannelProduct": {
                "channelProductName": product_data.get("title", ""),
            },
        }

    # ------------------------------------------------------------------ #
    #  Mock 모드 핸들러
    # ------------------------------------------------------------------ #

    async def _mock_register(self, product_data: dict) -> dict:
        """Mock 상품 등록 - 개발/테스트용 가짜 응답"""
        await asyncio.sleep(0.5)  # 네트워크 지연 시뮬레이션

        self._mock_counter += 1
        mock_id = f"MOCK-NSS-{self._mock_counter:04d}"
        title = product_data.get("title", "")

        logger.info(f"[Mock] 스마트스토어 상품 등록 완료: {mock_id} ({title})")

        return {
            "status": "success",
            "platform_product_id": mock_id,
            "url": f"https://smartstore.naver.com/products/{mock_id}",
            "message": f"스마트스토어 상품 등록 완료 (Mock) - {title}",
        }

    async def _mock_update(
        self, platform_product_id: str, product_data: dict
    ) -> dict:
        """Mock 상품 수정 - 개발/테스트용 가짜 응답"""
        await asyncio.sleep(0.5)

        title = product_data.get("title", "")
        logger.info(
            f"[Mock] 스마트스토어 상품 수정 완료: {platform_product_id} ({title})"
        )

        return {
            "status": "success",
            "platform_product_id": platform_product_id,
            "url": f"https://smartstore.naver.com/products/{platform_product_id}",
            "message": f"스마트스토어 상품 수정 완료 (Mock) - {platform_product_id}",
        }

    async def _mock_delete(self, platform_product_id: str) -> dict:
        """Mock 상품 삭제 - 개발/테스트용 가짜 응답"""
        await asyncio.sleep(0.5)

        logger.info(
            f"[Mock] 스마트스토어 상품 삭제 완료: {platform_product_id}"
        )

        return {
            "status": "success",
            "platform_product_id": platform_product_id,
            "url": None,
            "message": f"스마트스토어 상품 삭제 완료 (Mock) - {platform_product_id}",
        }


# ------------------------------------------------------------------ #
#  팩토리 함수
# ------------------------------------------------------------------ #


def get_smartstore_service() -> SmartStoreService:
    """SmartStoreService 인스턴스를 생성하여 반환한다."""
    service = SmartStoreService()
    mode = "Mock" if service.is_mock_mode else "Live"
    logger.info(f"SmartStoreService 초기화 완료 (모드: {mode})")
    return service
