"""9단계 테스트: 플래시카드 스키마·의미 검증."""

import pytest
from pydantic import ValidationError

from src.generate import Flashcard, FlashcardDeck, validate_flashcards


def _card(front="역전파란?", back="오차를 출력에서 입력 방향으로 전파해 가중치를 갱신하는 알고리즘.", slide=3):
    return Flashcard(front=front, back=back, source_slide=slide)


def test_schema_rejects_empty_front():
    with pytest.raises(ValidationError):
        Flashcard(front="", back="설명")


def test_validate_ok():
    deck = FlashcardDeck(cards=[_card(), _card(front="지도학습이란?", back="정답 레이블이 있는 데이터로 학습하는 방식.")])
    assert validate_flashcards(deck, expected_count=2) == []


def test_validate_duplicate_front():
    deck = FlashcardDeck(cards=[_card(), _card(back="다른 설명이지만 앞면이 같다.")])
    problems = validate_flashcards(deck, expected_count=2)
    assert any("중복된 앞면" in p for p in problems)


def test_validate_duplicate_front_ignores_whitespace_case():
    deck = FlashcardDeck(cards=[_card(front="ReLU 함수란?"), _card(front="relu  함수란?", back="다른 설명.")])
    assert any("중복된 앞면" in p for p in validate_flashcards(deck, expected_count=2))


def test_validate_front_equals_back():
    deck = FlashcardDeck(cards=[_card(front="역전파", back="역전파")])
    assert any("동일" in p for p in validate_flashcards(deck, expected_count=1))


def test_validate_too_few_cards():
    deck = FlashcardDeck(cards=[_card()])
    assert any("카드 수 부족" in p for p in validate_flashcards(deck, expected_count=15))


def test_validate_truncated_back():
    """조사로 끝나는 뒷면 = 문장 절단 (실전에서 발견된 케이스)."""
    deck = FlashcardDeck(cards=[_card(back="AI에 오타 수정을 명령할 때의 핵심 원칙은")])
    assert any("잘림" in p for p in validate_flashcards(deck, expected_count=1))


def test_validate_normal_endings_not_flagged():
    for back in ["가중치를 갱신하는 알고리즘입니다.", "평균 25% 더 높다", "학습 방식이에요"]:
        deck = FlashcardDeck(cards=[_card(back=back)])
        assert not any("잘림" in p for p in validate_flashcards(deck, expected_count=1)), back
