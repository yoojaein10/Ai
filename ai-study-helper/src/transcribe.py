"""GPU STT 모듈: faster-whisper로 오디오 → 타임스탬프 텍스트.

핵심 설계:
- faster-whisper(CTranslate2)는 원본 Whisper 대비 4배 이상 빠르고 VRAM도 절반 이하.
  int8_float16 양자화로 large-v3도 8GB GPU에서 여유 있게 돌아간다.
- 세그먼트마다 시작/종료 시각(초)을 보존한다 — 4단계에서 슬라이드와 정렬하고,
  6단계 RAG에서 "근거: 12:34" 표시를 하는 데 필수.
- 체크포인트: 결과를 job 폴더의 transcript.json에 저장하고, 이미 있으면 건너뛴다
  (계획서 4장 — 실패 시 이어서 재시작의 기반).
- GPU 실패 시 CPU로 자동 폴백 — 느려지지만 어디서든 동작한다.

사용법: python -m src.transcribe <job_id 또는 오디오 경로>
"""

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from . import config

# 모델 크기는 환경변수로 교체 가능. large-v3가 한국어 인식률이 가장 좋다.
# 속도가 더 중요하면 WHISPER_MODEL=medium 으로 낮출 것.
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "large-v3")

# 구간 병렬(배치 추론) 크기 — VAD로 나눈 오디오 구간을 GPU에서 동시에 처리한다.
# 클수록 빠르지만 VRAM을 더 쓴다. 8GB GPU 기준 8이 안전선.
STT_BATCH_SIZE = int(os.getenv("WHISPER_BATCH_SIZE", "8"))


@dataclass
class TranscriptSegment:
    start: float  # 초 단위
    end: float
    text: str


@dataclass
class Transcript:
    language: str
    duration: float  # 오디오 전체 길이(초)
    model: str
    device: str  # 실제 사용된 장치 (cuda | cpu)
    elapsed_sec: float  # STT 소요 시간
    segments: list[TranscriptSegment]

    @property
    def full_text(self) -> str:
        return " ".join(s.text.strip() for s in self.segments)


def _ensure_cuda_dlls() -> None:
    """pip으로 설치한 NVIDIA 라이브러리(cuBLAS·cuDNN)의 DLL 경로를 등록한다.

    Windows에서는 이 DLL들이 PATH에 없으면 ctranslate2가 GPU 초기화에 실패한다.
    시스템에 CUDA Toolkit을 따로 설치하지 않아도 되게 하는 장치."""
    site_packages = Path(__file__).resolve().parent.parent / ".venv" / "Lib" / "site-packages"
    for sub in ("nvidia/cublas/bin", "nvidia/cudnn/bin"):
        dll_dir = site_packages / sub
        if dll_dir.is_dir():
            os.add_dll_directory(str(dll_dir))
            # ctranslate2는 add_dll_directory 검색 경로를 타지 않고 PATH로 DLL을
            # 찾는다 — PATH 앞쪽에도 넣어야 cublas64_12.dll 로드가 성공한다.
            os.environ["PATH"] = str(dll_dir) + os.pathsep + os.environ.get("PATH", "")


def load_model(model_size: str = WHISPER_MODEL):
    """Whisper 모델 로드. GPU 우선, 실패하면 CPU(int8)로 폴백.

    모델 다운로드를 장치 초기화와 분리한 이유: 다운로드 단계의 오류(네트워크,
    Windows 심볼릭 링크 권한 등)가 "GPU 실패"로 오인되어 불필요하게
    CPU 폴백(20배 이상 느림)되는 것을 막기 위해서다.
    """
    from faster_whisper import WhisperModel
    from faster_whisper.utils import download_model

    _ensure_cuda_dlls()
    model_path = download_model(model_size)  # 캐시에 있으면 즉시 반환
    try:
        model = WhisperModel(model_path, device="cuda", compute_type="int8_float16")
        return model, "cuda"
    except Exception as e:
        print(f"[경고] GPU 초기화 실패 → CPU로 폴백합니다 (훨씬 느림): {e}")
        model = WhisperModel(model_path, device="cpu", compute_type="int8")
        return model, "cpu"


def transcribe_audio(
    audio_path: str | Path,
    language: str | None = None,
    batch_size: int = STT_BATCH_SIZE,
    on_progress=None,
) -> Transcript:
    """오디오 파일을 타임스탬프 세그먼트로 변환한다.

    - language=None이면 첫 30초로 언어를 자동 감지한다.
    - vad_filter로 무음 구간을 건너뛰어 속도·환각(무음에서 반복 텍스트) 모두 개선.
    - batch_size > 1이면 구간 병렬(배치 추론): VAD로 나눈 오디오 구간들을
      GPU에서 동시에 처리해 긴 영상에서 수 배 빨라진다 (계획서 "구간 병렬").
    - on_progress(0.0~1.0): 진행률 콜백 — 비동기 파이프라인의 진행률 표시용.
    """
    model, device = load_model()
    started = time.monotonic()

    if batch_size > 1:
        from faster_whisper import BatchedInferencePipeline

        pipeline = BatchedInferencePipeline(model=model)
        segments_iter, info = pipeline.transcribe(
            str(audio_path), language=language, batch_size=batch_size
        )
    else:
        segments_iter, info = model.transcribe(
            str(audio_path),
            language=language,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )

    segments: list[TranscriptSegment] = []
    for s in segments_iter:  # 제너레이터 — 여기서 실제 STT가 실행된다
        segments.append(TranscriptSegment(start=round(s.start, 2), end=round(s.end, 2), text=s.text.strip()))
        if on_progress and info.duration:
            on_progress(min(s.end / info.duration, 1.0))
    elapsed = time.monotonic() - started

    return Transcript(
        language=info.language,
        duration=round(info.duration, 2),
        model=WHISPER_MODEL,
        device=device,
        elapsed_sec=round(elapsed, 1),
        segments=segments,
    )


def transcribe_job(job_id: str, language: str | None = None, on_progress=None) -> Transcript:
    """job의 오디오를 STT 처리한다. 이미 처리됐으면 저장된 결과 반환(체크포인트)."""
    job_dir = config.JOBS_DIR / job_id
    meta_path = job_dir / "meta.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"job을 찾을 수 없습니다: {job_id} (먼저 ingest를 실행하세요)")

    transcript_path = job_dir / "transcript.json"
    if transcript_path.exists():  # 체크포인트 적중
        data = json.loads(transcript_path.read_text(encoding="utf-8"))
        data["segments"] = [TranscriptSegment(**s) for s in data["segments"]]
        return Transcript(**data)

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if not meta.get("audio_path"):
        raise ValueError(f"이 job에는 오디오가 없습니다 (유형: {meta.get('source_type')})")

    transcript = transcribe_audio(meta["audio_path"], language=language, on_progress=on_progress)
    transcript_path.write_text(
        json.dumps(asdict(transcript), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (job_dir / "transcript.txt").write_text(format_transcript(transcript), encoding="utf-8")
    return transcript


def format_timestamp(seconds: float) -> str:
    """초 → "H:MM:SS" 또는 "MM:SS" 사람이 읽는 형식."""
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def format_transcript(transcript: Transcript) -> str:
    """사람이 읽기 좋은 텍스트 형식: [MM:SS] 문장."""
    lines = [
        f"# 언어: {transcript.language} | 길이: {format_timestamp(transcript.duration)}"
        f" | 모델: {transcript.model} ({transcript.device}) | 처리: {transcript.elapsed_sec}초",
        "",
    ]
    lines += [f"[{format_timestamp(s.start)}] {s.text}" for s in transcript.segments]
    return "\n".join(lines)


def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="GPU STT: 오디오 → 타임스탬프 텍스트")
    parser.add_argument("target", help="job_id 또는 오디오 파일 경로")
    parser.add_argument("--language", default=None, help="언어 코드 강제 지정 (예: ko). 기본: 자동 감지")
    args = parser.parse_args()

    if Path(args.target).exists():  # 오디오 파일 직접 지정 (job 없이 단독 테스트용)
        transcript = transcribe_audio(args.target, language=args.language)
    else:
        transcript = transcribe_job(args.target, language=args.language)

    print(format_transcript(transcript))
    speed = transcript.duration / transcript.elapsed_sec if transcript.elapsed_sec else 0
    print(f"\n세그먼트 {len(transcript.segments)}개, 실시간 대비 {speed:.1f}배 속도")


if __name__ == "__main__":
    _main()
