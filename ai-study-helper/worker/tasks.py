"""Celery 비동기 파이프라인: 단계별 태스크 체인 + 진행률 기록.

왜 비동기인가 (계획서 4장): 2시간 영상은 STT만 십수 분 — HTTP 요청 안에서
처리할 수 없다. 업로드 즉시 job_id를 돌려주고, 백그라운드 worker가 단계를
진행하며 status.json에 진행률을 쓴다. 클라이언트는 GET /status/{job_id} 폴링.

설계:
- 단계별 태스크를 체인으로 연결: ingest → transcribe → slides → align → notes → index.
  각 태스크는 job_id를 받아 job_id를 반환한다 — 체인의 배관이 단순해진다.
- 각 단계 모듈은 자체 체크포인트가 있으므로 태스크는 자연히 멱등(idempotent):
  실패한 job을 같은 체인으로 다시 넣으면 완료된 단계는 즉시 통과한다.
- 무거운 import(faster-whisper 등)는 태스크 함수 안에서 — API 서버가
  이 모듈을 import해도 GPU 라이브러리가 로드되지 않는다.

실행 (Windows는 prefork 미지원 → solo 풀):
  .venv\\Scripts\\celery -A worker.tasks worker --pool=solo --loglevel=info
"""

import sys
from pathlib import Path

from celery import Celery, chain

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # src 패키지 경로

from src import config, status

celery_app = Celery(
    "ai_study_helper",
    broker=f"{config.REDIS_URL}/0",
    backend=f"{config.REDIS_URL}/1",
)
celery_app.conf.update(
    task_track_started=True,
    task_acks_late=False,
    broker_connection_retry_on_startup=True,
    # Windows용 Redis(5.x)는 RESP3(HELLO 명령)를 모른다 — RESP2로 고정
    broker_transport_options={"protocol": 2},
    result_backend_transport_options={"protocol": 2},
    redis_backend_use_ssl=False,
)


def _stage(job_id: str, name: str, fn, *, skipped_if=None) -> None:
    """단계 실행 공통 래퍼: 진행률 기록 + 실패 시 status에 오류 남기고 전파."""
    if skipped_if:
        status.update_stage(job_id, name, 1.0, done=True, skipped=True)
        return
    status.update_stage(job_id, name, 0.0)
    try:
        fn()
    except Exception as e:
        status.fail(job_id, name, str(e))
        raise
    status.update_stage(job_id, name, 1.0, done=True)


@celery_app.task(name="pipeline.ingest")
def t_ingest(source: str, youtube_video: bool = True) -> str:
    from src.ingest import detect_source_type, ingest, make_job_id

    job_id = make_job_id(source, detect_source_type(source))
    _stage(job_id, "ingest", lambda: ingest(source, youtube_video=youtube_video))
    return job_id


@celery_app.task(name="pipeline.transcribe")
def t_transcribe(job_id: str) -> str:
    import json

    from src.transcribe import transcribe_job

    meta = json.loads((config.JOBS_DIR / job_id / "meta.json").read_text(encoding="utf-8"))
    _stage(
        job_id,
        "transcribe",
        lambda: transcribe_job(
            job_id, on_progress=lambda f: status.update_stage(job_id, "transcribe", f)
        ),
        skipped_if=meta.get("source_type") == "document",  # 문서는 음성이 없다
    )
    return job_id


@celery_app.task(name="pipeline.slides")
def t_slides(job_id: str) -> str:
    import json

    from src.slides import analyze_job

    meta = json.loads((config.JOBS_DIR / job_id / "meta.json").read_text(encoding="utf-8"))
    _stage(
        job_id,
        "slides",
        lambda: analyze_job(
            job_id, on_progress=lambda f: status.update_stage(job_id, "slides", f)
        ),
        skipped_if=not meta.get("video_path"),
    )
    return job_id


@celery_app.task(name="pipeline.align")
def t_align(job_id: str) -> str:
    from src.align import align_job

    _stage(job_id, "align", lambda: align_job(job_id))
    return job_id


@celery_app.task(name="pipeline.notes")
def t_notes(job_id: str, detail: str = "중") -> str:
    from src.notes import generate_notes

    notes_done = (config.JOBS_DIR / job_id / "notes.md").exists()
    _stage(job_id, "notes", lambda: generate_notes(job_id, detail=detail), skipped_if=notes_done)
    return job_id


@celery_app.task(name="pipeline.index")
def t_index(job_id: str) -> str:
    from src.rag import build_index

    _stage(job_id, "index", lambda: build_index(job_id))
    status.finish(job_id)
    return job_id


def enqueue_pipeline(source: str, detail: str = "중", youtube_video: bool = True) -> str:
    """파이프라인 전체를 큐에 넣고 job_id를 즉시 반환한다 (API에서 호출).

    job_id를 여기서 미리 계산하는 이유: 클라이언트가 큐 등록 직후부터
    상태를 폴링할 수 있어야 하기 때문 (worker 시작을 기다리면 늦다).
    """
    from src.ingest import detect_source_type, make_job_id

    job_id = make_job_id(source, detect_source_type(source))
    status.init_status(job_id, source=source)
    chain(
        t_ingest.s(source, youtube_video=youtube_video),
        t_transcribe.s(),
        t_slides.s(),
        t_align.s(),
        t_notes.s(detail=detail),
        t_index.s(),
    ).apply_async()
    return job_id
