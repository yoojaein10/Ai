"""확장 단계(계획서 10-1) 테스트: 언어 감지, 논문 판별, 용어집 검증, 도표 필터."""

import pytest
from pydantic import ValidationError

from src.docparse import detect_language, looks_like_paper
from src.generate import Glossary, GlossaryTerm, validate_glossary


# --- 언어 감지 ----------------------------------------------------------------

def test_detect_korean():
    assert detect_language("딥러닝은 데이터로부터 표현을 학습하는 방법이다. " * 5) == "ko"


def test_detect_english():
    assert detect_language("Deep learning learns representations from data. " * 5) == "en"


def test_detect_mixed_korean_wins():
    """한영 혼용 강의자료(영어 용어 다수)도 한국어 자료로 판별돼야 한다."""
    text = "딥러닝(deep learning)은 neural network 기반의 machine learning 방법으로 데이터에서 표현을 학습한다. " * 5
    assert detect_language(text) == "ko"


def test_detect_unknown_when_too_short():
    assert detect_language("123 !!") == "unknown"


# --- 논문 판별 ----------------------------------------------------------------

def test_paper_detected():
    text = "Abstract\n...\n1. Introduction\n...\n3. Method\n...\nReferences\n[1] ..."
    assert looks_like_paper(text)


def test_lecture_not_paper():
    assert not looks_like_paper("오늘은 유튜브 쇼츠 수익화 전략을 배웁니다. 바이럴 쇼츠가 최고입니다.")


# --- 용어집 -------------------------------------------------------------------

def _term(term="attention", korean="어텐션", definition="시퀀스 내 위치 간 관계를 계산하는 메커니즘."):
    return GlossaryTerm(term=term, korean=korean, definition=definition)


def test_glossary_schema_rejects_empty():
    with pytest.raises(ValidationError):
        GlossaryTerm(term="", korean="어텐션", definition="설명입니다")


def test_glossary_validate_ok():
    g = Glossary(terms=[_term(), _term(term="transformer", korean="트랜스포머")])
    assert validate_glossary(g, expected_count=2) == []


def test_glossary_validate_duplicates():
    g = Glossary(terms=[_term(), _term(korean="다른 표기", definition="다른 설명이지만 용어가 같다.")])
    assert any("중복" in p for p in validate_glossary(g, expected_count=2))


def test_glossary_validate_too_few():
    assert any("부족" in p for p in validate_glossary(Glossary(terms=[_term()]), expected_count=20))


# --- 도표 추출 필터 -------------------------------------------------------------

def test_extract_figures_skips_small_images(tmp_path):
    """아이콘 크기 이미지는 도표 후보에서 제외돼야 한다."""
    import fitz

    from src.docparse import _extract_pdf_figures

    # 50x50 픽스맵(아이콘 크기) 하나가 삽입된 PDF
    small = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 50, 50))
    small.clear_with(200)
    pdf_path = tmp_path / "doc.pdf"
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_image(fitz.Rect(10, 10, 60, 60), pixmap=small)
    pdf.save(str(pdf_path))
    pdf.close()

    figures = _extract_pdf_figures(pdf_path, tmp_path / "figs")
    assert figures == []
