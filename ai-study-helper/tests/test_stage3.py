"""3단계 테스트: 지각 해시 중복 판정, 슬라이드 직렬화(체크포인트).

실제 전환 감지·Gemini 비전은 영상·API가 필요해 수동 검증
(python -m src.slides <job_id>)으로 하고, 순수 로직만 검증한다.
"""

import numpy as np
import pytest

from src.slides import Slide, _ahash, _hamming, _load, _save


def _solid_frame(value: int):
    """단색 프레임 (BGR)."""
    return np.full((100, 160, 3), value, dtype=np.uint8)


def _slide_like_frame(text_rows: list[int]):
    """슬라이드 흉내: 흰 배경에 특정 행만 검은 줄."""
    frame = np.full((100, 160, 3), 255, dtype=np.uint8)
    for row in text_rows:
        frame[row : row + 5, 20:140] = 0
    return frame


def test_ahash_same_frame_is_identical():
    f = _slide_like_frame([10, 30, 50])
    assert _ahash(f) == _ahash(f)


def test_ahash_small_change_is_close():
    """웹캠·마우스 수준의 작은 변화(구석 5% 영역)는 해밍 거리가 작아야 한다."""
    f1 = _slide_like_frame([10, 30, 50])
    f2 = f1.copy()
    f2[0:10, 150:160] = 128  # 우상단 구석만 변경 (웹캠 흉내)
    assert _hamming(_ahash(f1), _ahash(f2)) <= 5


def test_ahash_different_slides_are_far():
    """슬라이드가 바뀌면(내용 배치가 다르면) 해밍 거리가 커야 한다."""
    f1 = _slide_like_frame([10, 30, 50])
    f2 = _slide_like_frame([60, 80])
    assert _hamming(_ahash(f1), _ahash(f2)) > 5


def test_hamming_basics():
    assert _hamming(0b1010, 0b1010) == 0
    assert _hamming(0b1010, 0b0101) == 4


def test_slides_json_roundtrip(tmp_path):
    """체크포인트 저장·복원이 손실 없어야 한다 (content=None 미분석 상태 포함)."""
    slides = [
        Slide(index=1, start=0.0, end=65.2, image_path="slides/slide_001.jpg", content="# 1장 지도학습"),
        Slide(index=2, start=65.2, end=120.0, image_path="slides/slide_002.jpg", content=None),
    ]
    p = tmp_path / "slides.json"
    _save(slides, p)
    restored = _load(p)
    assert restored == slides
    assert restored[1].content is None
