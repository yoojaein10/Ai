"""FastAPI 백엔드: 청크 업로드(resumable) + 파이프라인 실행·조회 API.

청크 업로드 프로토콜 (계획서 4장 — 대용량 핵심):
1. POST /upload/init {filename, total_size} → {upload_id, chunk_size, total_chunks}
2. PUT  /upload/{upload_id}/chunk/{index}  (본문 = 원시 바이트) — 순서 무관, 재전송 무해
3. GET  /upload/{upload_id} → {received: [...], missing: [...]}  ← 중단 후 이어올리기의 근거
4. POST /upload/{upload_id}/complete → 조각 검증·조립 → {path}

이후 POST /ingest {source: path 또는 유튜브 URL} → Celery 파이프라인 → job_id.
클라이언트는 GET /status/{job_id} 폴링 → 완료 후 GET /notes, POST /ask.

실행: .venv\\Scripts\\uvicorn api.main:app --port 8000
"""

import json
import sys
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config, status

app = FastAPI(title="AI 학습 도우미 API", version="0.7.0")

UPLOADS_DIR = config.DATA_DIR / "uploads"
DEFAULT_CHUNK_SIZE = 8 * 1024 * 1024  # 8MB — 실패 시 재전송 부담과 요청 수의 균형


# ---------- 청크 업로드 (resumable) ----------

class UploadInit(BaseModel):
    filename: str
    total_size: int
    chunk_size: int = DEFAULT_CHUNK_SIZE


def _manifest_path(upload_id: str) -> Path:
    return UPLOADS_DIR / upload_id / "manifest.json"


def _load_manifest(upload_id: str) -> dict:
    path = _manifest_path(upload_id)
    if not path.exists():
        raise HTTPException(404, f"업로드 세션이 없습니다: {upload_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def _received_indices(upload_id: str) -> set[int]:
    return {
        int(p.stem.split("_")[1])
        for p in (UPLOADS_DIR / upload_id).glob("part_*.bin")
    }


@app.post("/upload/init")
def upload_init(body: UploadInit) -> dict:
    if body.total_size <= 0:
        raise HTTPException(400, "total_size는 양수여야 합니다")
    upload_id = uuid.uuid4().hex[:12]
    total_chunks = -(-body.total_size // body.chunk_size)  # 올림 나눗셈
    (UPLOADS_DIR / upload_id).mkdir(parents=True, exist_ok=True)
    manifest = {
        "upload_id": upload_id,
        "filename": Path(body.filename).name,  # 경로 조작 방지 — 파일명만
        "total_size": body.total_size,
        "chunk_size": body.chunk_size,
        "total_chunks": total_chunks,
    }
    _manifest_path(upload_id).write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return manifest


@app.put("/upload/{upload_id}/chunk/{index}")
async def upload_chunk(upload_id: str, index: int, request: Request) -> dict:
    manifest = _load_manifest(upload_id)
    if not 0 <= index < manifest["total_chunks"]:
        raise HTTPException(400, f"청크 번호 범위 초과: {index} (0~{manifest['total_chunks'] - 1})")
    data = await request.body()
    if not data:
        raise HTTPException(400, "빈 청크입니다")
    # 같은 청크 재전송은 덮어쓰기 — 재시도가 안전하다(멱등)
    (UPLOADS_DIR / upload_id / f"part_{index:05d}.bin").write_bytes(data)
    return {"received_count": len(_received_indices(upload_id)), "total_chunks": manifest["total_chunks"]}


@app.get("/upload/{upload_id}")
def upload_status(upload_id: str) -> dict:
    manifest = _load_manifest(upload_id)
    received = _received_indices(upload_id)
    missing = sorted(set(range(manifest["total_chunks"])) - received)
    return {**manifest, "received": sorted(received), "missing": missing, "complete": not missing}


@app.post("/upload/{upload_id}/complete")
def upload_complete(upload_id: str) -> dict:
    manifest = _load_manifest(upload_id)
    received = _received_indices(upload_id)
    missing = sorted(set(range(manifest["total_chunks"])) - received)
    if missing:
        raise HTTPException(409, f"누락된 청크가 있습니다: {missing[:10]}{'...' if len(missing) > 10 else ''}")

    upload_dir = UPLOADS_DIR / upload_id
    out_path = upload_dir / manifest["filename"]
    with open(out_path, "wb") as out:
        for i in range(manifest["total_chunks"]):
            part = upload_dir / f"part_{i:05d}.bin"
            out.write(part.read_bytes())
    actual_size = out_path.stat().st_size
    if actual_size != manifest["total_size"]:
        out_path.unlink()
        raise HTTPException(409, f"크기 불일치: 기대 {manifest['total_size']}, 실제 {actual_size}")
    for part in upload_dir.glob("part_*.bin"):
        part.unlink()  # 조립 후 조각 정리
    return {"path": str(out_path), "size": actual_size}


# ---------- 파이프라인 ----------

class IngestRequest(BaseModel):
    source: str  # 파일 경로(업로드 완료 응답의 path) 또는 유튜브 URL
    detail: str = "중"
    youtube_video: bool = True  # 유튜브: 영상까지 받아 슬라이드 분석 (False면 오디오만)


@app.post("/ingest")
def ingest_endpoint(body: IngestRequest) -> dict:
    from worker.tasks import enqueue_pipeline

    try:
        job_id = enqueue_pipeline(body.source, detail=body.detail, youtube_video=body.youtube_video)
    except ValueError as e:  # 지원하지 않는 입력
        raise HTTPException(400, str(e))
    return {"job_id": job_id}


@app.get("/status/{job_id}")
def status_endpoint(job_id: str) -> dict:
    data = status.read_status(job_id)
    if data is None:
        raise HTTPException(404, f"job이 없습니다: {job_id}")
    return {**data, "overall_progress": status.overall_progress(data)}


@app.get("/notes/{job_id}")
def notes_endpoint(job_id: str) -> dict:
    job_dir = config.JOBS_DIR / job_id
    notes_path = job_dir / "notes.md"
    chapters_path = job_dir / "chapters.json"
    if not notes_path.exists():
        raise HTTPException(404, "노트가 아직 없습니다 — /status 로 진행 상태를 확인하세요")
    chapters = json.loads(chapters_path.read_text(encoding="utf-8")) if chapters_path.exists() else {}
    return {
        "job_id": job_id,
        "summary": chapters.get("summary", ""),
        "chapters": chapters.get("chapters", []),
        "notes_md": notes_path.read_text(encoding="utf-8"),
    }


class AskRequest(BaseModel):
    job_id: str
    question: str


@app.post("/ask")
def ask_endpoint(body: AskRequest) -> dict:
    from src.rag import ask

    if not (config.JOBS_DIR / body.job_id / "aligned.json").exists():
        raise HTTPException(404, "이 job은 아직 질문 가능한 상태가 아닙니다 — /status 를 확인하세요")
    answer = ask(body.job_id, body.question)
    return {
        "question": answer.question,
        "answer": answer.text,
        "sources": [
            {"label": s.label, "slide_index": s.slide_index, "start": s.start}
            for s in answer.sources
        ],
    }
