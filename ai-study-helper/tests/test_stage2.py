"""2단계 테스트: 타임스탬프 형식, 트랜스크립트 직렬화·체크포인트.

실제 GPU STT는 모델 다운로드·GPU가 필요해 단위 테스트에서 제외하고
(수동 검증: python -m src.transcribe <job_id>), 순수 로직만 검증한다.
"""

import json

import pytest

from src.transcribe import (
    Transcript,
    TranscriptSegment,
    format_timestamp,
    format_transcript,
)


@pytest.mark.parametrize(
    "seconds, expected",
    [
        (0, "00:00"),
        (59.4, "00:59"),
        (60, "01:00"),
        (754.5, "12:34"),
        (3600, "1:00:00"),
        (7325, "2:02:05"),
    ],
)
def test_format_timestamp(seconds, expected):
    assert format_timestamp(seconds) == expected


def _sample_transcript() -> Transcript:
    return Transcript(
        language="ko",
        duration=125.0,
        model="large-v3",
        device="cuda",
        elapsed_sec=10.5,
        segments=[
            TranscriptSegment(start=0.0, end=4.2, text="안녕하세요, 오늘은 지도학습을 배웁니다."),
            TranscriptSegment(start=4.2, end=9.8, text="먼저 회귀와 분류의 차이부터 보겠습니다."),
        ],
    )


def test_format_transcript_readable():
    out = format_transcript(_sample_transcript())
    assert "[00:00] 안녕하세요, 오늘은 지도학습을 배웁니다." in out
    assert "[00:04] 먼저 회귀와 분류의 차이부터 보겠습니다." in out
    assert "ko" in out


def test_full_text_joins_segments():
    t = _sample_transcript()
    assert t.full_text == "안녕하세요, 오늘은 지도학습을 배웁니다. 먼저 회귀와 분류의 차이부터 보겠습니다."


def test_transcript_json_roundtrip(tmp_path):
    """저장(체크포인트) 형식이 손실 없이 복원되는지 — transcribe_job 캐시 경로와 동일한 로직."""
    from dataclasses import asdict

    t = _sample_transcript()
    p = tmp_path / "transcript.json"
    p.write_text(json.dumps(asdict(t), ensure_ascii=False), encoding="utf-8")

    data = json.loads(p.read_text(encoding="utf-8"))
    data["segments"] = [TranscriptSegment(**s) for s in data["segments"]]
    restored = Transcript(**data)

    assert restored == t


def test_transcribe_job_missing_raises():
    from src.transcribe import transcribe_job

    with pytest.raises(FileNotFoundError):
        transcribe_job("존재하지않는job")
