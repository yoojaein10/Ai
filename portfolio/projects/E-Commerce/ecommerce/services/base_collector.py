from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class CollectedProduct:
    """도매처에서 수집한 원시 상품 데이터 (DB 저장 전 정규화용)"""
    source: str            # DOMEME | OWNERCLAN
    origin_code: str       # 도매처 고유 상품번호
    title: str             # 상품명
    cost_price: float      # 도매 원가 (원)
    stock: int             # 재고 수량 (-1: 확인불가)
    images: list[str]      # 이미지 URL 리스트
    category_code: str     # 카테고리 코드 (없으면 빈 문자열)
    detail_url: str        # 상품 상세 페이지 URL


class BaseCollector(ABC):
    """도매처 수집기 공통 인터페이스"""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """도매처 식별자 (DOMEME / OWNERCLAN)"""
        ...

    @abstractmethod
    async def collect(self, item_no: str) -> CollectedProduct:
        """상품번호로 상품 정보를 수집합니다.

        Args:
            item_no: 도매처 상품 고유번호

        Returns:
            CollectedProduct: 정규화된 상품 데이터

        Raises:
            CollectorException: 수집 실패 시
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """도매처 사이트 접근 가능 여부를 확인합니다."""
        ...
