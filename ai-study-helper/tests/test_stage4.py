"""4단계 테스트: 음성·슬라이드 정렬 로직."""

import pytest

from src.align import AlignedSection, SpeechLine, align, format_aligned_markdown


def _slide(index, start, end, content="내용"):
    return {"index": index, "start": start, "end": end, "image_path": f"slide_{index:03d}.jpg", "content": content}


def _seg(start, end, text):
    return {"start": start, "end": end, "text": text}


def test_align_basic_assignment():
    slides = [_slide(1, 0, 60), _slide(2, 60, 120)]
    segments = [_seg(0, 5, "첫 슬라이드 발화"), _seg(70, 75, "둘째 슬라이드 발화")]

    sections = align(segments, slides)

    assert len(sections) == 2
    assert sections[0].speech[0].text == "첫 슬라이드 발화"
    assert sections[1].speech[0].text == "둘째 슬라이드 발화"


def test_align_boundary_segment_goes_to_midpoint_side():
    """슬라이드 전환(60초)에 걸친 발화: 중간 시점이 속한 쪽으로 배정."""
    slides = [_slide(1, 0, 60), _slide(2, 60, 120)]
    # 58~64초 발화 → 중간 61초 → 슬라이드 2
    # 55~63초 발화 → 중간 59초 → 슬라이드 1
    sections = align([_seg(58, 64, "뒤쪽"), _seg(55, 63, "앞쪽")], slides)

    assert [l.text for l in sections[0].speech] == ["앞쪽"]
    assert [l.text for l in sections[1].speech] == ["뒤쪽"]


def test_align_speech_after_last_slide():
    """마지막 슬라이드 종료 후 발화(경계 오차)는 마지막 섹션에 붙인다 — 유실 금지."""
    slides = [_slide(1, 0, 60)]
    sections = align([_seg(61, 65, "마무리 인사")], slides)

    assert sections[0].speech[0].text == "마무리 인사"


def test_align_silent_slide():
    """발화 없는 슬라이드도 섹션은 생성돼야 한다 (화면 정보만으로도 가치 있음)."""
    slides = [_slide(1, 0, 60), _slide(2, 60, 120)]
    sections = align([_seg(0, 5, "발화")], slides)

    assert len(sections) == 2
    assert sections[1].speech == []


def test_align_segments_stay_ordered():
    slides = [_slide(1, 0, 100)]
    sections = align([_seg(50, 55, "나중"), _seg(0, 5, "먼저")], slides)

    assert [l.text for l in sections[0].speech] == ["먼저", "나중"]


def test_align_empty_slides_returns_empty():
    assert align([_seg(0, 5, "발화")], []) == []


def test_speech_text_joins():
    sec = AlignedSection(
        slide_index=1, start=0, end=60, slide_image="s.jpg", slide_content="c",
        speech=[SpeechLine(0, 5, "안녕하세요."), SpeechLine(5, 9, "시작합니다.")],
    )
    assert sec.speech_text == "안녕하세요. 시작합니다."


def test_format_markdown_contains_both_modalities():
    slides = [_slide(1, 0, 60, content="# 지도학습\n- 정답이 있는 데이터")]
    md = format_aligned_markdown(align([_seg(0, 5, "오늘은 지도학습입니다.")], slides))

    assert "## 슬라이드 1 [00:00~01:00]" in md
    assert "# 지도학습" in md          # 화면(비전) 내용
    assert "오늘은 지도학습입니다." in md  # 발화(STT) 내용


def test_format_markdown_silent_slide():
    md = format_aligned_markdown(align([], [_slide(1, 0, 60)]))
    assert "(발화 없음)" in md
