from utils.logger import logger


class TranslationService:
    # Mock 번역 사전
    _mock_dict: dict[str, str] = {
        "高品质无线蓝牙耳机 降噪运动耳机": "고품질 무선 블루투스 이어폰 노이즈캔슬링 스포츠 이어폰",
        "白色": "화이트",
        "黑色": "블랙",
        "粉色": "핑크",
        "高品质无线蓝牙耳机，支持主动降噪，适合运动使用。电池续航长达8小时。": (
            "고품질 무선 블루투스 이어폰, 액티브 노이즈캔슬링 지원, 운동 시 사용에 적합합니다. "
            "배터리 지속시간 최대 8시간."
        ),
    }

    async def translate(self, text: str) -> str:
        """중국어 텍스트를 한국어로 번역합니다. (Mock)"""
        logger.debug(f"번역 요청: {text[:30]}...")

        # TODO: 실제 번역 API 연동 (Papago / DeepL / Google Translate)
        translated = self._mock_dict.get(text, f"[번역됨] {text}")
        return translated

    async def translate_product(self, raw: dict) -> dict:
        """크롤링된 상품 데이터 전체를 한국어로 번역합니다."""
        logger.info("상품 데이터 번역 시작")

        title_ko = await self.translate(raw["title"])
        desc_ko = await self.translate(raw["description"])
        options_ko = [await self.translate(opt) for opt in raw["options"]]

        # 위안 -> 원 환산 (Mock: 1위안 ≈ 190원)
        price_krw = int(raw["price"] * 190)

        result = {
            "title": title_ko,
            "price": price_krw,
            "price_cny": float(raw["price"]),
            "images": raw["images"],
            "options": options_ko,
            "description": desc_ko,
        }

        logger.info(f"번역 완료: {title_ko}")
        return result


def get_translation_service() -> TranslationService:
    return TranslationService()
