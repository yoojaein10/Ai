"""8단계 테스트: 퀴즈 스키마·의미 검증·채점 — LLM 없이 도는 순수 로직."""

import pytest
from pydantic import ValidationError

from src.generate import Quiz, QuizQuestion, grade_answer, validate_quiz


def _mc(question="지도학습의 특징은 무엇인가?", options=None, answer="정답이 있는 데이터로 학습"):
    return QuizQuestion(
        type="multiple_choice",
        question=question,
        options=options or ["정답이 있는 데이터로 학습", "보상 기반 학습", "군집화 학습", "무작위 학습"],
        answer=answer,
        explanation="지도학습은 레이블이 있는 데이터로 모델을 학습시키는 방식이다.",
        source_slide=3,
    )


def _sa(answer="역전파"):
    return QuizQuestion(
        type="short_answer",
        question="오차를 뒤로 전파해 가중치를 갱신하는 알고리즘은?",
        options=[],
        answer=answer,
        explanation="역전파(backpropagation)는 신경망 학습의 핵심 알고리즘이다.",
    )


# --- 스키마 (Pydantic 1차 방어) ---------------------------------------------

def test_schema_rejects_wrong_type():
    with pytest.raises(ValidationError):
        QuizQuestion(type="essay", question="문제", options=[], answer="답", explanation="해설입니다")


def test_schema_rejects_empty_answer():
    with pytest.raises(ValidationError):
        _mc(answer="")


# --- 의미 검증 (2차 방어) ------------------------------------------------------

def test_validate_ok():
    assert validate_quiz(Quiz(questions=[_mc(), _sa()]), expected_count=2) == []


def test_validate_answer_not_in_options():
    quiz = Quiz(questions=[_mc(answer="보기에 없는 답")])
    problems = validate_quiz(quiz, expected_count=1)
    assert any("보기에 없음" in p for p in problems)


def test_validate_wrong_option_count():
    quiz = Quiz(questions=[_mc(options=["하나", "둘", "셋"], answer="하나")])
    assert any("4개가 아님" in p for p in validate_quiz(quiz, expected_count=1))


def test_validate_duplicate_options():
    quiz = Quiz(questions=[_mc(options=["같음", "같음", "다름", "또다름"], answer="다름")])
    assert any("중복" in p for p in validate_quiz(quiz, expected_count=1))


def test_validate_short_answer_with_options():
    q = _sa()
    q.options = ["이상한", "보기"]
    assert any("단답형인데" in p for p in validate_quiz(Quiz(questions=[q]), expected_count=1))


def test_validate_too_few_questions():
    assert any("문항 수 부족" in p for p in validate_quiz(Quiz(questions=[_mc()]), expected_count=10))


# --- 채점 --------------------------------------------------------------------

def test_grade_mc_by_text():
    assert grade_answer(_mc(), "정답이 있는 데이터로 학습")
    assert not grade_answer(_mc(), "보상 기반 학습")


def test_grade_mc_by_number():
    assert grade_answer(_mc(), "1")      # 1번 보기 = 정답
    assert not grade_answer(_mc(), "2")


def test_grade_short_answer_normalized():
    assert grade_answer(_sa(), "역전파")
    assert grade_answer(_sa(), " 역 전 파 ")   # 공백 무시
    assert grade_answer(_sa(answer="ReLU"), "relu")  # 대소문자 무시
    assert not grade_answer(_sa(), "순전파")
