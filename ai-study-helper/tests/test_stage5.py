"""5단계 테스트: 청킹, JSON 추출, 챕터 검증 — LLM 없이 도는 순수 로직."""

import pytest

from src.notes import _validate_chapters, chunk_sections, extract_json


def _sec(index, content_len=1000, speech_len=1000):
    return {
        "slide_index": index,
        "start": index * 60.0,
        "end": (index + 1) * 60.0,
        "slide_image": f"slide_{index:03d}.jpg",
        "slide_content": "가" * content_len,
        "speech": [{"start": index * 60.0, "end": index * 60 + 5.0, "text": "나" * speech_len}],
    }


# --- 청킹 ---------------------------------------------------------------

def test_chunk_respects_budget():
    sections = [_sec(i) for i in range(1, 11)]  # 섹션당 2000자
    chunks = chunk_sections(sections, budget=5000)
    assert all(len(c) <= 3 for c in chunks)  # 5000/2000 → 최대 2~3개씩
    assert sum(len(c) for c in chunks) == 10  # 유실 없음


def test_chunk_preserves_order():
    chunks = chunk_sections([_sec(i) for i in range(1, 8)], budget=5000)
    flat = [s["slide_index"] for c in chunks for s in c]
    assert flat == list(range(1, 8))


def test_chunk_oversized_section_not_split():
    """예산을 초과하는 단일 섹션도 통째로 한 청크가 된다 (화면+발화를 찢지 않음)."""
    chunks = chunk_sections([_sec(1, content_len=9000)], budget=5000)
    assert len(chunks) == 1


def test_chunk_empty():
    assert chunk_sections([]) == []


# --- JSON 추출 (LLM 응답 방어) -------------------------------------------

def test_extract_json_plain():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_with_fence():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_with_surrounding_text():
    assert extract_json('네, 요청하신 JSON입니다:\n{"a": 1}\n도움이 되셨나요?') == {"a": 1}


def test_extract_json_missing_raises():
    with pytest.raises(ValueError):
        extract_json("JSON이 없는 그냥 텍스트")


# --- 챕터 검증 ------------------------------------------------------------

def _valid_chapter(**over):
    ch = {"title": "1장", "start": 0, "end": 120, "slides": [1, 2]}
    ch.update(over)
    return ch


def test_validate_chapters_ok():
    data = {"chapters": [_valid_chapter()]}
    assert _validate_chapters(data, max_slide=45)[0]["title"] == "1장"


def test_validate_chapters_filters_bad_slide_numbers():
    """범위 밖(환각) 슬라이드 번호는 조용히 제거 — 전체 거부보다 낫다."""
    data = {"chapters": [_valid_chapter(slides=[1, 99, -3, 2])]}
    assert _validate_chapters(data, max_slide=45)[0]["slides"] == [1, 2]


@pytest.mark.parametrize(
    "bad",
    [
        {},                                              # chapters 없음
        {"chapters": []},                                # 빈 목록
        {"chapters": [_valid_chapter(title="")]},        # 제목 없음
        {"chapters": [_valid_chapter(start="10분")]},    # 시간이 문자열
    ],
)
def test_validate_chapters_rejects(bad):
    with pytest.raises(ValueError):
        _validate_chapters(bad, max_slide=45)
