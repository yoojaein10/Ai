"""예상 소요 시간 추정 테스트 — 실측 계수 기반 추정기의 동작 고정."""

import json

import pytest

from src import status


@pytest.fixture()
def job(tmp_path, monkeypatch):
    monkeypatch.setattr(status.config, "JOBS_DIR", tmp_path)
    job_dir = tmp_path / "j1"
    job_dir.mkdir()
    # 22분(1320초) 강의 시뮬레이션 — transcript가 정확한 길이를 제공
    (job_dir / "transcript.json").write_text(
        json.dumps({"duration": 1320.0, "segments": []}), encoding="utf-8"
    )
    return "j1"


def _stages(**overrides):
    base = {name: {"status": "pending", "progress": 0.0} for name in status.PIPELINE_STAGES}
    for k, v in overrides.items():
        base[k] = v
    return {"stages": base}


def test_estimate_full_pending(job):
    remaining, total = status.estimate_remaining(job, _stages())
    assert remaining == pytest.approx(total)
    assert 120 < total < 3600  # 22분 강의: 수 분~1시간 사이의 상식적 추정


def test_estimate_decreases_with_progress(job):
    r_before, _ = status.estimate_remaining(job, _stages())
    r_after, _ = status.estimate_remaining(
        job, _stages(ingest={"status": "done", "progress": 1.0},
                     transcribe={"status": "running", "progress": 0.5})
    )
    assert r_after < r_before


def test_estimate_zero_when_all_done(job):
    done = {name: {"status": "done", "progress": 1.0} for name in status.PIPELINE_STAGES}
    remaining, _ = status.estimate_remaining(job, {"stages": done})
    assert remaining == 0


def test_estimate_skipped_slides_reduces_total(job):
    _, total_with = status.estimate_remaining(job, _stages())
    _, total_without = status.estimate_remaining(
        job, _stages(slides={"status": "skipped", "progress": 0.0})
    )
    assert total_without < total_with


def test_estimate_uses_actual_slide_count(job, tmp_path):
    """slides.json이 생기면 추정 대신 실제 장수로 비전 시간을 계산한다."""
    _, total_estimated = status.estimate_remaining(job, _stages())  # 추정 장수(~20장) 기준
    slides = [{"index": i, "start": 0, "end": 0, "image_path": "", "content": None} for i in range(100)]
    (tmp_path / "j1" / "slides.json").write_text(json.dumps(slides), encoding="utf-8")
    _, total_actual = status.estimate_remaining(job, _stages())
    # 실제 100장이 반영되면 총 예상이 커져야 한다 (장당 단가는 티어에 따라 다름)
    assert total_actual > total_estimated
    assert total_actual - total_estimated == pytest.approx(
        status._VISION_SEC_PER_SLIDE * (100 - 1320 * status._SLIDES_PER_SEC), rel=0.01
    )


def test_estimate_none_without_media(tmp_path, monkeypatch):
    """길이를 알 수 없으면(문서 등) None — UI는 표시를 생략한다."""
    monkeypatch.setattr(status.config, "JOBS_DIR", tmp_path)
    (tmp_path / "doc1").mkdir()
    assert status.estimate_remaining("doc1", _stages()) is None
