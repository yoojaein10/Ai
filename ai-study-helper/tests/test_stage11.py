"""11단계 테스트: 문서 파이프라인(섹션 변환·위치 라벨), OCR 렌더링, 언리더블→폴백 판정.

Gemini 비전 OCR·외국어 노트 생성은 API가 필요해 수동 검증(보고서 참조)."""

import json

import pytest

from src.align import sections_from_document
from src.docparse import _render_pdf_pages, parse_document
from src.rag import Source, build_chunks


def _doc_segments():
    return [
        {"location": "p.1", "text": "1장 서론. 트랜스포머는 어텐션만으로 구성된 모델이다."},
        {"location": "p.2", "text": ""},  # 빈 페이지 — 건너뛰어야 함
        {"location": "p.3", "text": "2장 방법. 셀프 어텐션은 시퀀스 내 관계를 계산한다."},
    ]


# --- 문서 → 섹션 ---------------------------------------------------------------

def test_sections_from_document_skips_empty():
    sections = sections_from_document(_doc_segments())
    assert len(sections) == 2
    assert sections[0].location == "p.1"
    assert sections[1].location == "p.3"
    assert sections[1].slide_index == 2  # 빈 페이지 건너뛰어도 인덱스는 연속


def test_sections_from_document_no_time():
    sections = sections_from_document(_doc_segments())
    assert all(s.start == 0.0 and s.end == 0.0 for s in sections)
    assert all(s.slide_image == "" for s in sections)


# --- RAG 위치 라벨 --------------------------------------------------------------

def test_chunks_use_location_header():
    sections = [
        {
            "slide_index": 1, "start": 0.0, "end": 0.0, "slide_image": "",
            "slide_content": "트랜스포머는 어텐션만으로 구성된다.", "speech": [], "location": "p.1",
        }
    ]
    chunks = build_chunks(sections)
    assert chunks[0].location == "p.1"
    assert chunks[0].text.startswith("[p.1]")


def test_source_label_priority():
    assert Source(slide_index=1, start=0, text="", location="p.3").label == "p.3"
    assert Source(slide_index=2, start=94, text="", has_slide=True).label == "슬라이드 2, 01:34"
    assert Source(slide_index=3, start=94, text="", has_slide=False).label == "01:34"


# --- OCR 재료: PDF 페이지 렌더링 --------------------------------------------------

def test_render_pdf_pages(tmp_path):
    import fitz

    pdf_path = tmp_path / "doc.pdf"
    pdf = fitz.open()
    pdf.new_page()
    pdf.new_page()
    pdf.save(str(pdf_path))
    pdf.close()

    images = _render_pdf_pages(pdf_path, tmp_path / "imgs")
    assert len(images) == 2
    assert all(p.exists() and p.stat().st_size > 0 for p in images)


def test_scanned_pdf_detected_unreadable_without_fallback(tmp_path):
    """텍스트 레이어 없는 PDF는 (폴백 끄면) 언리더블로 표시돼야 한다."""
    import fitz

    pdf_path = tmp_path / "scanned.pdf"
    pdf = fitz.open()
    pdf.new_page()  # 빈 페이지 = 텍스트 레이어 없음
    pdf.save(str(pdf_path))
    pdf.close()

    doc = parse_document(pdf_path, ocr_fallback=False)
    assert not doc.is_readable
