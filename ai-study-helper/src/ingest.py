"""입력 접수 모듈: 영상 파일 / 유튜브 링크 / 문서 → 후속 처리 준비.

핵심 설계 (계획서 4장):
- 영상은 ffmpeg로 오디오만 추출 → 처리 대상이 GB 단위에서 수십 MB로 줄어든다.
- 입력마다 내용 기반 job_id를 부여하고 data/jobs/{job_id}/ 에 결과를 저장.
  같은 파일을 다시 넣으면 같은 job_id가 나와 기존 결과를 재사용한다(캐싱).
- 유튜브는 파일 업로드 없이 yt-dlp로 오디오 스트림만 받는다(대용량 우회 경로).

사용법: python -m src.ingest <영상경로 | 유튜브URL | 문서경로>
"""

import hashlib
import json
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from . import config
from .docparse import SUPPORTED_EXTS as DOC_EXTS
from .docparse import parse_document

VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".wmv", ".ts"}
AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".aac"}
YOUTUBE_RE = re.compile(r"(youtube\.com/(watch|shorts|live)|youtu\.be/)")


def _run(cmd: list[str], fail_msg: str) -> subprocess.CompletedProcess:
    """외부 프로세스 실행 헬퍼. Windows에서 콘솔 인코딩(cp949)과 UTF-8이 섞여도
    출력 읽기가 깨지지 않도록 errors="replace"로 방어한다."""
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"{fail_msg}: {result.stderr.strip()}")
    return result


@dataclass
class IngestResult:
    job_id: str
    source: str
    source_type: str  # video | audio | youtube | document
    audio_path: str | None  # STT 입력 (video/audio/youtube일 때)
    video_path: str | None  # 슬라이드 분석 입력 (video일 때) — 3단계에서 사용
    doc_text: str | None  # 문서 파싱 결과 (document일 때)
    doc_readable: bool | None  # False면 OCR 폴백 대상
    job_dir: str
    doc_language: str | None = None  # 문서 언어 (ko/en/unknown) — 외국어 경로 분기용
    doc_is_paper: bool | None = None  # 논문 구조 판별 — 섹션별 요약 경로 분기용


def detect_source_type(source: str) -> str:
    if YOUTUBE_RE.search(source):
        return "youtube"
    ext = Path(source).suffix.lower()
    if ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in DOC_EXTS:
        return "document"
    raise ValueError(f"지원하지 않는 입력입니다: {source}")


def make_job_id(source: str, source_type: str) -> str:
    """내용 기반 job_id — 같은 입력이면 항상 같은 id가 나와 재처리를 방지한다.

    대용량 영상 전체를 해시하면 느리므로 앞/뒤 10MB + 파일 크기만 해시한다.
    유튜브는 URL 자체를 해시.
    """
    h = hashlib.sha256()
    if source_type == "youtube":
        h.update(source.encode())
    else:
        path = Path(source)
        size = path.stat().st_size
        h.update(str(size).encode())
        chunk = 10 * 1024 * 1024
        with open(path, "rb") as f:
            h.update(f.read(chunk))
            if size > chunk * 2:
                f.seek(-chunk, 2)
                h.update(f.read(chunk))
    return h.hexdigest()[:12]


def extract_audio(media_path: Path, out_path: Path) -> Path:
    """ffmpeg로 오디오만 추출해 16kHz 모노 WAV로 저장 (faster-whisper 표준 입력)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-i", str(media_path),
        "-vn",  # 비디오 스트림 제거 — 오디오만
        "-ac", str(config.AUDIO_CHANNELS),
        "-ar", str(config.AUDIO_SAMPLE_RATE),
        str(out_path),
    ]
    _run(cmd, "ffmpeg 오디오 추출 실패")
    return out_path


def download_youtube_audio(url: str, out_dir: Path) -> Path:
    """yt-dlp로 오디오 스트림만 다운로드한 뒤 표준 형식(16kHz 모노 WAV)으로 변환."""
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_template = str(out_dir / "yt_raw.%(ext)s")
    # yt-dlp를 PATH의 실행파일이 아니라 현재 인터프리터의 모듈로 호출한다 —
    # 가상환경만 있으면 동작하고, 시스템 PATH 상태에 의존하지 않는다.
    cmd = [sys.executable, "-m", "yt_dlp", "-f", "bestaudio", "-o", raw_template, "--no-playlist", url]
    _run(cmd, "유튜브 다운로드 실패")

    raw_files = list(out_dir.glob("yt_raw.*"))
    if not raw_files:
        raise RuntimeError("유튜브 다운로드 결과 파일을 찾을 수 없습니다.")
    audio_path = extract_audio(raw_files[0], out_dir / "audio.wav")
    raw_files[0].unlink()  # 변환 후 원본 스트림 삭제
    return audio_path


def download_youtube_video(url: str, out_dir: Path) -> Path:
    """yt-dlp로 영상(720p 이하)을 받아 슬라이드 분석까지 가능하게 한다.

    유튜브 강의도 PPT·칠판 화면이 정보의 절반이다 — 오디오만 받으면 멀티모달의
    핵심을 잃는다. 720p면 슬라이드 텍스트 인식에 충분하고 용량도 감당 가능."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "video.mp4"
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-f", "bv*[height<=720]+ba/b[height<=720]/b",  # 720p 영상+오디오, 폴백 포함
        "--merge-output-format", "mp4",
        "-o", str(out_path), "--no-playlist", url,
    ]
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:  # 영상+오디오 스트림 병합에 ffmpeg 필요 — 위치를 명시해 PATH 문제 회피
        cmd += ["--ffmpeg-location", ffmpeg]
    _run(cmd, "유튜브 영상 다운로드 실패")
    if not out_path.exists():
        raise RuntimeError("유튜브 영상 다운로드 결과 파일을 찾을 수 없습니다.")
    return out_path


def ingest(source: str, youtube_video: bool = True) -> IngestResult:
    """입력을 접수하고 job 디렉토리에 처리 준비물(오디오/텍스트)을 만든다.

    이미 처리된 입력이면 저장된 결과를 그대로 반환한다(캐싱).
    youtube_video=True면 유튜브도 영상을 받아 슬라이드 분석까지 수행한다
    (False면 오디오만 — 빠르지만 화면 정보를 잃는다).
    """
    source_type = detect_source_type(source)
    job_id = make_job_id(source, source_type)
    job_dir = config.JOBS_DIR / job_id
    meta_path = job_dir / "meta.json"

    if meta_path.exists():  # 캐시 적중 — 동일 입력 재처리 방지
        cached = IngestResult(**json.loads(meta_path.read_text(encoding="utf-8")))
        upgrade = source_type == "youtube" and youtube_video and not cached.video_path
        if not upgrade:
            return cached
        # 오디오 전용 → 영상 포함으로 업그레이드: 화면 정보가 없던 하위 산출물 무효화
        for stale in ("aligned.json", "aligned.md", "notes.md", "notes_chunks.json", "chapters.json"):
            (job_dir / stale).unlink(missing_ok=True)

    job_dir.mkdir(parents=True, exist_ok=True)
    audio_path: str | None = None
    video_path: str | None = None
    doc_text: str | None = None
    doc_readable: bool | None = None

    if source_type == "video":
        audio_path = str(extract_audio(Path(source), job_dir / "audio.wav"))
        video_path = str(Path(source).resolve())  # 원본은 3단계 슬라이드 분석에서 다시 읽는다
    elif source_type == "audio":
        audio_path = str(extract_audio(Path(source), job_dir / "audio.wav"))
    elif source_type == "youtube":
        if youtube_video:
            video = download_youtube_video(source, job_dir)
            audio_path = str(extract_audio(video, job_dir / "audio.wav"))
            video_path = str(video)
        else:
            audio_path = str(download_youtube_audio(source, job_dir))
    elif source_type == "document":
        parsed = parse_document(source)
        if Path(source).suffix.lower() == ".pdf" and parsed.is_readable:
            # 텍스트 PDF 안의 도표·수식 이미지를 비전으로 해석해 본문에 병합 (계획서 10-1)
            from .docparse import analyze_pdf_figures

            analyze_pdf_figures(Path(source), parsed)
        doc_text = parsed.full_text
        doc_readable = parsed.is_readable
        (job_dir / "document.txt").write_text(doc_text, encoding="utf-8")
        # 위치(페이지·슬라이드·시트)를 보존한 구조적 저장 — 정렬·RAG 근거 표시용
        (job_dir / "document.json").write_text(
            json.dumps(
                [{"location": s.location, "text": s.text} for s in parsed.segments],
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )

    doc_language = doc_is_paper = None
    if doc_text is not None:
        from .docparse import detect_language, looks_like_paper

        doc_language = detect_language(doc_text)
        doc_is_paper = looks_like_paper(doc_text)

    result = IngestResult(
        job_id=job_id,
        source=source,
        source_type=source_type,
        audio_path=audio_path,
        video_path=video_path,
        doc_text=doc_text,
        doc_readable=doc_readable,
        job_dir=str(job_dir),
        doc_language=doc_language,
        doc_is_paper=doc_is_paper,
    )
    meta_path.write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="입력 접수: 영상/유튜브/문서 → 처리 준비")
    parser.add_argument("source", help="영상 파일 경로, 유튜브 URL, 또는 문서 경로")
    parser.add_argument("--audio-only", action="store_true", help="유튜브: 오디오만 (빠름, 슬라이드 분석 생략)")
    args = parser.parse_args()

    result = ingest(args.source, youtube_video=not args.audio_only)
    print(f"job_id      : {result.job_id}")
    print(f"입력 유형   : {result.source_type}")
    print(f"작업 폴더   : {result.job_dir}")
    if result.audio_path:
        size_mb = Path(result.audio_path).stat().st_size / 1024 / 1024
        print(f"오디오      : {result.audio_path} ({size_mb:.1f} MB)")
    if result.doc_text is not None:
        print(f"문서 텍스트 : {len(result.doc_text):,}자 (읽기 가능: {result.doc_readable})")


if __name__ == "__main__":
    _main()
