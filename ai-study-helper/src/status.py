"""job 진행 상태 기록·조회.

Celery worker가 쓰고(update) FastAPI가 읽는(read) 파일 기반 상태 저장소.
Redis에 넣을 수도 있지만 파일로 두면 job 폴더 하나에 그 job의 모든 것
(입력·중간 결과·상태)이 모여 디버깅·백업이 단순해진다.
"""

import json
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
