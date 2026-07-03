"""프로젝트 공통 설정: 경로, 환경변수, 상수."""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
JOBS_DIR = DATA_DIR / "jobs"  # 작업(job)별 중간 결과 저장소 — 체크포인트·캐싱의 기반

load_dotenv(BASE_DIR / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Celery 브로커·결과 저장소 (로컬 Redis)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# faster-whisper는 16kHz 모노 입력이 표준 — 미리 이 형식으로 추출해두면
# STT 단계에서 재변환이 없고, 원본 영상 대비 용량이 크게 줄어든다.
AUDIO_SAMPLE_RATE = 16000
AUDIO_CHANNELS = 1

# 문서에서 추출된 텍스트가 페이지당 이 글자 수보다 적으면
# 스캔본/이미지 문서("언리더블")로 판별한다. → 3단계 이후 OCR 폴백 대상
MIN_CHARS_PER_PAGE = 20
