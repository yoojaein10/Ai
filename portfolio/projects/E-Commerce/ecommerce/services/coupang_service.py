"""
쿠팡 Wing API 연동 서비스

- HMAC-SHA256 서명 인증
- API 키 미설정 시 Mock 모드 자동 전환
- 상품 등록 / 수정 / 삭제 지원
"""

import asyncio
import hashlib
import hmac
import os
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlencode, urlparse

import httpx

from utils.logger import logger

# ──────────────────────────────────────────────
# 환경변수 기본값
# ──────────────────────────────────────────────
COUPANG_BASE_URL = "https://api-gateway.coupang.com"
PRODUCT_API_PATH = "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products"


class CoupangService:
    """쿠팡 Wing API 클라이언트"""

    def __init__(self) -> None:
        self._access_key: str = os.getenv("COUPANG_ACCESS_KEY", "")
        self._secret_key: str = os.getenv("COUPANG_SECRET_KEY", "")
        self._vendor_id: str = os.getenv("COUPANG_VENDOR_ID", "")
        self._base_url: str = COUPANG_BASE_URL
        self._timeout: float = 30.0

        if self.is_mock_mode:
            logger.warning("[CoupangService] API 키 미설정 - Mock 모드로 동작합니다.")
        else:
            logger.info("[CoupangService] 실제 API 모드로 초기화되었습니다.")

    # ──────────────────────────────────────────
    # Mock 모드 판별
    # ──────────────────────────────────────────
    @property
    def is_mock_mode(self) -> bool:
        """API 키가 하나라도 비어 있으면 Mock 모드"""
        return not all([self._access_key, self._secret_key, self._vendor_id])

    # ──────────────────────────────────────────
    # HMAC-SHA256 서명 생성
    # ──────────────────────────────────────────
    def _generate_signature(
        self,
        method: str,
        path: str,
        query_params: dict | None = None,
    ) -> dict[str, str]:
        """쿠팡 Wing API 표준 HMAC-SHA256 서명 헤더 생성"""
        datetime_now = datetime.now(timezone.utc).strftime("%y%m%dT%H%M%SZ")
        # 쿠팡 서명 포맷: {datetime}\n{method}\n{path}\n{query}
        query_string = urlencode(query_params) if query_params else ""
        message = f"{datetime_now}\n{method.upper()}\n{path}\n{query_string}"

        signature = hmac.new(
            self._secret_key.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        authorization = (
            f"CEA algorithm=HmacSHA256, "
            f"access-key={self._access_key}, "
            f"signed-date={datetime_now}, "
            f"signature={signature}"
        )

        return {
            "Authorization": authorization,
            "Content-Type": "application/json;charset=UTF-8",
            "X-Requested-By": self._vendor_id,
        }

    # ──────────────────────────────────────────
    # 내부 HTTP 요청
    # ──────────────────────────────────────────
    async def _request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        query_params: dict | None = None,
    ) -> dict:
        """서명 포함 API 요청 실행"""
        headers = self._generate_signature(method, path, query_params)
        url = f"{self._base_url}{path}"

        if query_params:
            url = f"{url}?{urlencode(query_params)}"

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.request(
                    method=method.upper(),
                    url=url,
                    headers=headers,
                    json=body,
                )
                response.raise_for_status()
                return response.json()

        except httpx.HTTPStatusError as e:
            logger.error(
                f"[CoupangService] HTTP {e.response.status_code}: "
                f"{e.response.text[:500]}"
            )
            raise
        except httpx.RequestError as e:
            logger.error(f"[CoupangService] 요청 실패: {e}")
            raise

    # ──────────────────────────────────────────
    # 상품 등록 / 수정 / 삭제 payload 변환
    # ──────────────────────────────────────────
    def _build_product_payload(self, product_data: dict) -> dict:
        """내부 product_data를 쿠팡 Wing API 형식으로 변환"""
        return {
            "displayCategoryCode": product_data.get("category", "0"),
            "sellerProductName": product_data["title"],
            "vendorId": self._vendor_id,
            "saleStartedAt": datetime.now(timezone.utc).isoformat(),
            "saleEndedAt": "2099-12-31T23:59:59",
            "displayProductName": product_data["title"],
            "brand": "",
            "generalProductName": product_data["title"],
            "productGroup": "",
            "deliveryMethod": "SEQUENCIAL",
            "deliveryCompanyCode": "KGB",
            "deliveryChargeType": "FREE",
            "returnCenterCode": "",
            "returnChargeName": "",
            "companyContactNumber": "",
            "returnCharge": 5000,
            "returnChargeVendor": "VENDOR",
            "afterServiceInformation": "",
            "afterServiceContactNumber": "",
            "outboundShippingPlaceCode": "",
            "vendorUserId": "",
            "requested": False,
            "items": [
                {
                    "itemName": product_data["title"],
                    "originalPrice": int(product_data.get("cost_price", 0)),
                    "salePrice": int(product_data["sale_price"]),
                    "maximumBuyCount": 999,
                    "maximumBuyForPerson": 0,
                    "outboundShippingTimeDay": 2,
                    "unitCount": 1,
                    "adultOnly": "EVERYONE",
                    "taxType": "TAX",
                    "parallelImported": "NOT_PARALLEL_IMPORTED",
                    "overseasPurchased": "NOT_OVERSEAS_PURCHASED",
                    "pccNeeded": False,
                    "images": [
                        {
                            "imageOrder": 0,
                            "imageType": "REPRESENTATION",
                            "vendorPath": product_data.get("image_url", ""),
                        }
                    ],
                    "notices": [],
                    "attributes": [],
                    "contents": [
                        {
                            "contentsType": "HTML",
                            "contentDetails": [
                                {
                                    "content": product_data.get("description", ""),
                                    "detailType": "TEXT",
                                }
                            ],
                        }
                    ],
                    "offerCondition": "NEW",
                    "offerDescription": "",
                    "inventoryQuantity": product_data.get("stock", 0),
                }
            ],
        }

    # ──────────────────────────────────────────
    # Mock 응답 생성
    # ──────────────────────────────────────────
    async def _mock_delay(self) -> None:
        """Mock 모드 지연 시뮬레이션 (0.5초)"""
        await asyncio.sleep(0.5)

    def _mock_product_id(self) -> str:
        """Mock 상품 ID 생성"""
        return f"MOCK-{uuid.uuid4().hex[:8].upper()}"

    # ──────────────────────────────────────────
    # 상품 등록
    # ──────────────────────────────────────────
    async def register_product(self, product_data: dict) -> dict:
        """
        상품 등록

        Args:
            product_data: title, cost_price, sale_price, category,
                          description, image_url, stock

        Returns:
            {status, platform_product_id, url, message}
        """
        title = product_data.get("title", "")
        logger.info(f"[CoupangService] 상품 등록 시작: {title}")

        # ── Mock 모드 ──
        if self.is_mock_mode:
            await self._mock_delay()
            mock_id = self._mock_product_id()
            logger.info(f"[CoupangService] Mock 등록 완료: {mock_id}")
            return {
                "status": "success",
                "platform_product_id": mock_id,
                "url": f"https://www.coupang.com/vp/products/{mock_id}",
                "message": f"Mock 모드 상품 등록 완료 - {title}",
            }

        # ── 실제 API 호출 ──
        try:
            payload = self._build_product_payload(product_data)
            result = await self._request("POST", PRODUCT_API_PATH, body=payload)

            product_id = str(result.get("data", {}).get("sellerProductId", ""))
            logger.info(f"[CoupangService] 상품 등록 성공: {product_id}")

            return {
                "status": "success",
                "platform_product_id": product_id,
                "url": f"https://www.coupang.com/vp/products/{product_id}",
                "message": f"쿠팡 상품 등록 완료 - {title}",
            }

        except Exception as e:
            logger.error(f"[CoupangService] 상품 등록 실패: {e}")
            return {
                "status": "error",
                "platform_product_id": "",
                "url": "",
                "message": f"상품 등록 실패: {str(e)}",
            }

    # ──────────────────────────────────────────
    # 상품 수정
    # ──────────────────────────────────────────
    async def update_product(
        self, platform_product_id: str, product_data: dict
    ) -> dict:
        """
        상품 수정

        Args:
            platform_product_id: 쿠팡 상품 ID
            product_data: 수정할 상품 정보

        Returns:
            {status, platform_product_id, url, message}
        """
        title = product_data.get("title", "")
        logger.info(
            f"[CoupangService] 상품 수정 시작: {platform_product_id} / {title}"
        )

        # ── Mock 모드 ──
        if self.is_mock_mode:
            await self._mock_delay()
            logger.info(
                f"[CoupangService] Mock 수정 완료: {platform_product_id}"
            )
            return {
                "status": "success",
                "platform_product_id": platform_product_id,
                "url": f"https://www.coupang.com/vp/products/{platform_product_id}",
                "message": f"Mock 모드 상품 수정 완료 - {title}",
            }

        # ── 실제 API 호출 ──
        try:
            payload = self._build_product_payload(product_data)
            payload["sellerProductId"] = int(platform_product_id)
            path = PRODUCT_API_PATH
            result = await self._request("PUT", path, body=payload)

            logger.info(
                f"[CoupangService] 상품 수정 성공: {platform_product_id}"
            )
            return {
                "status": "success",
                "platform_product_id": platform_product_id,
                "url": f"https://www.coupang.com/vp/products/{platform_product_id}",
                "message": f"쿠팡 상품 수정 완료 - {title}",
            }

        except Exception as e:
            logger.error(f"[CoupangService] 상품 수정 실패: {e}")
            return {
                "status": "error",
                "platform_product_id": platform_product_id,
                "url": "",
                "message": f"상품 수정 실패: {str(e)}",
            }

    # ──────────────────────────────────────────
    # 상품 삭제
    # ──────────────────────────────────────────
    async def delete_product(self, platform_product_id: str) -> dict:
        """
        상품 삭제 (판매 중지)

        Args:
            platform_product_id: 쿠팡 상품 ID

        Returns:
            {status, platform_product_id, url, message}
        """
        logger.info(
            f"[CoupangService] 상품 삭제 시작: {platform_product_id}"
        )

        # ── Mock 모드 ──
        if self.is_mock_mode:
            await self._mock_delay()
            logger.info(
                f"[CoupangService] Mock 삭제 완료: {platform_product_id}"
            )
            return {
                "status": "success",
                "platform_product_id": platform_product_id,
                "url": "",
                "message": f"Mock 모드 상품 삭제 완료 - {platform_product_id}",
            }

        # ── 실제 API 호출 ──
        try:
            path = f"{PRODUCT_API_PATH}/{platform_product_id}"
            await self._request("DELETE", path)

            logger.info(
                f"[CoupangService] 상품 삭제 성공: {platform_product_id}"
            )
            return {
                "status": "success",
                "platform_product_id": platform_product_id,
                "url": "",
                "message": f"쿠팡 상품 삭제 완료 - {platform_product_id}",
            }

        except Exception as e:
            logger.error(f"[CoupangService] 상품 삭제 실패: {e}")
            return {
                "status": "error",
                "platform_product_id": platform_product_id,
                "url": "",
                "message": f"상품 삭제 실패: {str(e)}",
            }


# ──────────────────────────────────────────────
# 싱글턴 팩토리
# ──────────────────────────────────────────────
_instance: CoupangService | None = None


def get_coupang_service() -> CoupangService:
    """CoupangService 싱글턴 반환"""
    global _instance
    if _instance is None:
        _instance = CoupangService()
    return _instance
