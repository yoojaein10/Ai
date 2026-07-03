"""7단계 테스트: 청크 업로드 프로토콜(순서 무관·누락 감지·이어올리기·조립),
진행률 상태, 오디오 전용 폴백. Celery 실행은 통합 테스트에서 수동 검증."""

import io
import json

import pytest
from fastapi.testclient import TestClient

from api.main import app
from src import status
from src.align import pseudo_sections_from_transcript

client = TestClient(app)


# ---------- 청크 업로드 ----------

def _init_upload(data: bytes, chunk_size: int = 1024) -> dict:
    r = client.post(
        "/upload/init",
        json={"filename": "test.mp4", "total_size": len(data), "chunk_size": chunk_size},
    )
    assert r.status_code == 200
    return r.json()


def _chunks(data: bytes, size: int):
    return [data[i : i + size] for i in range(0, len(data), size)]


def test_upload_full_flow_out_of_order():
    """청크를 뒤죽박죽 순서로 올려도 조립 결과가 원본과 같아야 한다."""
    data = bytes(range(256)) * 20  # 5120 bytes → 5 chunks
    m = _init_upload(data)
    parts = _chunks(data, m["chunk_size"])

    for i in reversed(range(len(parts))):  # 역순 업로드
        r = client.put(f"/upload/{m['upload_id']}/chunk/{i}", content=parts[i])
        assert r.status_code == 200

    r = client.post(f"/upload/{m['upload_id']}/complete")
    assert r.status_code == 200
    from pathlib import Path

    assert Path(r.json()["path"]).read_bytes() == data


def test_upload_resume_after_interruption():
    """중단(청크 누락) → 상태 조회로 누락 확인 → 그것만 올려 재개 — resumable의 핵심."""
    data = b"x" * 5000
    m = _init_upload(data)
    parts = _chunks(data, m["chunk_size"])

    # 청크 2를 빼고 업로드 (전송 중단 시뮬레이션)
    for i in [0, 1, 3, 4]:
        client.put(f"/upload/{m['upload_id']}/chunk/{i}", content=parts[i])

    # 조립 시도 → 409 + 상태 조회로 누락 확인
    assert client.post(f"/upload/{m['upload_id']}/complete").status_code == 409
    st = client.get(f"/upload/{m['upload_id']}").json()
    assert st["missing"] == [2]

    # 누락분만 올리고 재시도 → 성공
    client.put(f"/upload/{m['upload_id']}/chunk/2", content=parts[2])
    r = client.post(f"/upload/{m['upload_id']}/complete")
    assert r.status_code == 200
    from pathlib import Path

    assert Path(r.json()["path"]).read_bytes() == data


def test_upload_rechunk_is_idempotent():
    data = b"y" * 2000
    m = _init_upload(data)
    parts = _chunks(data, m["chunk_size"])
    for _ in range(3):  # 같은 청크 반복 전송
        client.put(f"/upload/{m['upload_id']}/chunk/0", content=parts[0])
    client.put(f"/upload/{m['upload_id']}/chunk/1", content=parts[1])
    r = client.post(f"/upload/{m['upload_id']}/complete")
    assert r.status_code == 200


def test_upload_bad_index_rejected():
    m = _init_upload(b"z" * 100)
    assert client.put(f"/upload/{m['upload_id']}/chunk/99", content=b"a").status_code == 400


def test_upload_unknown_session_404():
    assert client.get("/upload/doesnotexist").status_code == 404


# ---------- 상태 관리 ----------

def test_status_lifecycle(monkeypatch, tmp_path):
    monkeypatch.setattr(status.config, "JOBS_DIR", tmp_path)
    status.init_status("j1", source="test.mp4")
    status.update_stage("j1", "transcribe", 0.5)
    data = status.read_status("j1")
    assert data["state"] == "running"
    assert data["stages"]["transcribe"]["progress"] == 0.5

    status.update_stage("j1", "slides", 1.0, done=True, skipped=True)
    status.finish("j1")
    data = status.read_status("j1")
    assert data["state"] == "done"
    assert data["stages"]["slides"]["status"] == "skipped"


def test_status_failure_recorded(monkeypatch, tmp_path):
    monkeypatch.setattr(status.config, "JOBS_DIR", tmp_path)
    status.init_status("j2", source="bad.mp4")
    status.fail("j2", "transcribe", "GPU 폭발")
    data = status.read_status("j2")
    assert data["state"] == "error"
    assert "GPU 폭발" in data["error"]


def test_overall_progress():
    data = {
        "stages": {
            "a": {"status": "done", "progress": 1.0},
            "b": {"status": "skipped", "progress": 0.0},  # skipped = 완료 취급
            "c": {"status": "running", "progress": 0.5},
            "d": {"status": "pending", "progress": 0.0},
        }
    }
    assert status.overall_progress(data) == pytest.approx(0.625)


# ---------- 오디오 전용 폴백 ----------

def test_pseudo_sections_group_by_window():
    segments = [{"start": float(t), "end": t + 5.0, "text": f"발화{t}"} for t in range(0, 300, 30)]
    sections = pseudo_sections_from_transcript(segments, window_sec=90.0)

    assert len(sections) >= 3
    assert all(s.slide_image == "" for s in sections)  # 슬라이드 없음 표시
    total = sum(len(s.speech) for s in sections)
    assert total == len(segments)  # 유실 없음


def test_pseudo_sections_indices_sequential():
    segments = [{"start": 0.0, "end": 5.0, "text": "a"}, {"start": 200.0, "end": 205.0, "text": "b"}]
    sections = pseudo_sections_from_transcript(segments, window_sec=90.0)
    assert [s.slide_index for s in sections] == [1, 2]


def test_source_label_without_slide():
    from src.rag import Source

    assert Source(slide_index=3, start=94.0, text="...", has_slide=False).label == "01:34"
