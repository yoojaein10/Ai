"""job 진행 상태 기록·조회.

Celery worker가 쓰고(update) FastAPI가 읽는(read) 파일 기반 상태 저장소.
Redis에 넣을 수도 있지만 파일로 두면 job 폴더 하나에 그 job의 모든 것
(입력·중간 결과·상태)이 모여 디버깅·백업이 단순해진다.
"""

import json
import os
import time
from pathlib import Path

from . import config

# 파이프라인 단계 순서 — worker와 API가 공유하는 계약
PIPELINE_STAGES = ["ingest", "transcribe", "slides", "align", "notes", "index"]


def _path(job_id: str) -> Path:
    return config.JOBS_DIR / job_id / "status.json"


def _write(job_id: str, data: dict) -> None:
    data["updated_at"] = time.time()
    path = _path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    # 임시 파일 → 교체: API가 쓰다 만 JSON을 읽는 일이 없게 한다
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def init_status(job_id: str, source: str) -> dict:
    data = {
        "job_id": job_id,
        "source": source,
        "state": "queued",  # queued | running | done | error
        "current_stage": None,
        "error": None,
        "stages": {name: {"status": "pending", "progress": 0.0} for name in PIPELINE_STAGES},
    }
    _write(job_id, data)
    return data


def read_status(job_id: str) -> dict | None:
    path = _path(job_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def update_stage(job_id: str, stage: str, progress: float, done: bool = False, skipped: bool = False) -> None:
    data = read_status(job_id) or init_status(job_id, source="")
    data["state"] = "running"
    data["current_stage"] = stage
    entry = data["stages"].setdefault(stage, {})
    entry["progress"] = round(min(max(progress, 0.0), 1.0), 3)
    entry["status"] = "skipped" if skipped else ("done" if done else "running")
    _write(job_id, data)


def finish(job_id: str) -> None:
    data = read_status(job_id)
    if data:
        data["state"] = "done"
        data["current_stage"] = None
        _write(job_id, data)


def fail(job_id: str, stage: str, error: str) -> None:
    data = read_status(job_id)
    if data:
        data["state"] = "error"
        data["current_stage"] = stage
        data["error"] = f"[{stage}] {error}"
        data["stages"].setdefault(stage, {})["status"] = "error"
        _write(job_id, data)


# ---------- 예상 소요 시간 ----------
# 계수는 실측에서 도출 (RTX 5060 Ti, 2시간·9.1GB 영상 + 22분 영상 기준):
# 추출 89s/7200s≈0.013, STT(배치) 148s/7200s≈0.021, 전환 감지 613s/7200s≈0.085,
# 비전 슬라이드당 ~7s(호출 간격 지배), 노트 390s/7200s≈0.055.
_RATE = {"ingest": 0.013, "transcribe": 0.021, "detect": 0.085, "notes": 0.055}
_SLIDES_PER_SEC = 1 / 65  # 감지 전 슬라이드 수 추정: 65초당 1장 (실측 평균)
_INDEX_SEC = 30.0
_MIN_STAGE_SEC = 8.0

# 유료 티어(호출 간격 0)에서는 비전 8병렬·노트 map 병렬 — 단가가 크게 다르다
_FAST_MODE = float(os.getenv("GEMINI_MIN_INTERVAL", "6")) <= 0
_VISION_SEC_PER_SLIDE = 1.2 if _FAST_MODE else 7.0
_NOTES_RATE = 0.02 if _FAST_MODE else _RATE["notes"]


def _media_duration(job_id: str) -> float | None:
    """영상·오디오 길이(초). transcript가 있으면 정확값, 없으면 WAV 크기로 추정
    (16kHz 모노 16bit PCM = 32,000 bytes/sec)."""
    job_dir = config.JOBS_DIR / job_id
    t = job_dir / "transcript.json"
    if t.exists():
        try:
            return float(json.loads(t.read_text(encoding="utf-8"))["duration"])
        except (json.JSONDecodeError, KeyError, ValueError):
            pass
    wav = job_dir / "audio.wav"
    if wav.exists():
        return max(wav.stat().st_size - 44, 0) / 32000
    return None


def _slides_counts(job_id: str) -> tuple[int | None, int]:
    """(전체 슬라이드 수 | 미확정 None, 비전 분석 완료 수)."""
    path = config.JOBS_DIR / job_id / "slides.json"
    if not path.exists():
        return None, 0
    try:
        slides = json.loads(path.read_text(encoding="utf-8"))
        return len(slides), sum(1 for s in slides if s.get("content"))
    except json.JSONDecodeError:
        return None, 0


def estimate_remaining(job_id: str, data: dict) -> tuple[float, float] | None:
    """(남은 초, 총 예상 초) 추정. 문서 등 길이를 모르면 None (표시 생략).

    단계별 예상치 × (1 - 진행률)의 합 — 진행률은 worker가 쓰는 status 기준.
    '예상'이므로 UI에서는 반드시 '약 ~' 으로 표기할 것.
    """
    duration = _media_duration(job_id)
    if not duration:
        return None
    total_slides, _ = _slides_counts(job_id)
    est_slides = total_slides if total_slides is not None else max(duration * _SLIDES_PER_SEC, 3)

    stages = data.get("stages", {})
    slides_skipped = stages.get("slides", {}).get("status") == "skipped"
    est = {
        "ingest": max(duration * _RATE["ingest"], _MIN_STAGE_SEC),
        "transcribe": max(duration * _RATE["transcribe"], _MIN_STAGE_SEC),
        "slides": 0.0 if slides_skipped
        else duration * _RATE["detect"] + est_slides * _VISION_SEC_PER_SLIDE,
        "align": 2.0,
        "notes": max(duration * _NOTES_RATE, 45.0),
        "index": _INDEX_SEC,
    }
    remaining = 0.0
    for name, stage_est in est.items():
        entry = stages.get(name, {})
        if entry.get("status") in ("done", "skipped"):
            continue
        progress = entry.get("progress", 0.0) if entry.get("status") == "running" else 0.0
        remaining += stage_est * (1 - progress)
    return remaining, sum(est.values())


def overall_progress(data: dict) -> float:
    """전체 진행률: 단계별 진행률의 평균 (skipped는 완료로 계산)."""
    stages = data.get("stages", {})
    if not stages:
        return 0.0
    total = 0.0
    for entry in stages.values():
        if entry.get("status") in ("done", "skipped"):
            total += 1.0
        else:
            total += entry.get("progress", 0.0)
    return round(total / len(stages), 3)
