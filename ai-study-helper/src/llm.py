"""Gemini API 래퍼: 텍스트 생성 + 이미지 이해(비전).

무료 티어 보호 장치 (계획서 12장 "비용·한도"):
- 호출 간 최소 간격(rate limit) — 분당 요청 한도 초과 방지
- 429(한도 초과)·일시 오류 시 지수 백오프 재시도
- 호출 수 카운팅·로깅 — 하루 한도 관리

이후 단계(노트·퀴즈·RAG)도 전부 이 래퍼를 거친다. LLM 호출을 한 곳으로
모아야 캐싱·로깅·모델 교체가 한 번에 된다.
"""

import os
import threading
import time
from pathlib import Path

from . import config

# 모델은 환경변수로 교체 가능. 2.5 flash가 무료 티어 한도·속도·비전 품질의 균형점.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# 무료 티어 분당 요청 한도(RPM) 보호 — 기본 6초 간격(10 RPM). 유료 키면 0으로.
MIN_CALL_INTERVAL_SEC = float(os.getenv("GEMINI_MIN_INTERVAL", "6"))

# 임베딩 모델 — 한 번에 여러 텍스트를 배치로 처리 가능
EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
EMBED_BATCH_SIZE = 100

_RETRY_WAITS = [15, 30, 60]  # 429/일시 오류 시 대기(초) — 지수 백오프


class GeminiClient:
    def __init__(self, model: str = GEMINI_MODEL):
        if not config.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY가 없습니다. .env 파일을 확인하세요.")
        from google import genai

        self._client = genai.Client(api_key=config.GEMINI_API_KEY)
        self.model = model
        self.call_count = 0
        self._last_call_at = 0.0
        self._lock = threading.Lock()  # 병렬 호출(유료 티어) 시 간격·카운트 보호

    def _throttle(self) -> None:
        """호출 간 최소 간격을 지켜 분당 한도 초과를 예방한다 (스레드 안전).

        유료 티어(GEMINI_MIN_INTERVAL=0)에서는 no-op — 병렬 호출이 자유롭다."""
        if MIN_CALL_INTERVAL_SEC <= 0:
            return
        with self._lock:
            wait = MIN_CALL_INTERVAL_SEC - (time.monotonic() - self._last_call_at)
            self._last_call_at = time.monotonic() + max(wait, 0.0)
        if wait > 0:
            time.sleep(wait)

    def _count(self) -> None:
        with self._lock:
            self.call_count += 1

    def generate(self, prompt: str, images: list[str | Path] | None = None, fast: bool = False) -> str:
        """텍스트(+선택적 이미지) 프롬프트 → 응답 텍스트.

        - images를 주면 멀티모달 호출이 된다(슬라이드 분석·OCR 폴백에서 사용).
        - fast=True면 thinking을 끈다(thinking_budget=0). 슬라이드 텍스트 추출처럼
          추론이 불필요한 작업에서 속도·비용 개선 + "thinking만 하다 빈 응답으로
          종료"(2.5-flash 실측 사례, thoughts 1,929토큰에 본문 0)를 방지한다.
        """
        from google.genai import types

        contents: list = []
        for img in images or []:
            data = Path(img).read_bytes()
            contents.append(types.Part.from_bytes(data=data, mime_type="image/jpeg"))
        contents.append(prompt)

        gen_config = None
        if fast:
            gen_config = types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_budget=0)
            )

        last_error: Exception | None = None
        for attempt, retry_wait in enumerate([0] + _RETRY_WAITS):
            if retry_wait:
                print(f"[재시도 {attempt}/{len(_RETRY_WAITS)}] {retry_wait}초 대기 후 재호출...")
                time.sleep(retry_wait)
            self._throttle()
            try:
                response = self._client.models.generate_content(
                    model=self.model, contents=contents, config=gen_config
                )
                self._count()
                if not response.text:
                    raise RuntimeError("Gemini가 빈 응답을 반환했습니다 (thinking 소진 추정)")
                return response.text
            except Exception as e:
                last_error = e
                # 재시도 가치가 있는 것: 429(한도)·5xx(서버 오류)·빈 응답(확률적).
                # 인증 오류(401)나 잘못된 요청(400)은 재시도해도 같은 결과.
                msg = str(e)
                retryable = ("429", "RESOURCE_EXHAUSTED", "500", "503", "UNAVAILABLE", "빈 응답")
                if not any(code in msg for code in retryable):
                    raise
        raise RuntimeError(f"Gemini 호출이 재시도 후에도 실패했습니다: {last_error}")


    def generate_structured(self, prompt: str, schema, max_retries: int = 2):
        """스키마가 강제된 JSON 생성 (구조화 출력 — 계획서 핵심 기술 포인트).

        3중 방어:
        1. Gemini 네이티브 구조화 출력 — response_schema로 모델 단에서 형식 강제
        2. Pydantic 검증 — 응답을 타입 검사하며 파싱 (response.parsed)
        3. 검증 실패 시 오류 내용을 프롬프트에 되먹여 재시도

        schema: pydantic BaseModel 서브클래스. 반환: 검증된 schema 인스턴스.
        """
        from google.genai import types

        last_error: Exception | None = None
        current_prompt = prompt
        for attempt in range(max_retries + 1):
            self._throttle()
            try:
                response = self._client.models.generate_content(
                    model=self.model,
                    contents=current_prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=schema,
                    ),
                )
                self._count()
                parsed = response.parsed
                if parsed is None:
                    raise ValueError(f"스키마 파싱 실패: {response.text[:300]}")
                return parsed
            except Exception as e:
                last_error = e
                msg = str(e)
                if any(code in msg for code in ("429", "RESOURCE_EXHAUSTED", "500", "503", "UNAVAILABLE")):
                    time.sleep(_RETRY_WAITS[min(attempt, len(_RETRY_WAITS) - 1)])
                else:
                    # 형식 문제 — 오류를 되먹여 스스로 고치게 한다
                    current_prompt = f"{prompt}\n\n직전 응답은 이 문제로 거부되었습니다: {e}\n스키마에 맞는 JSON만 출력하세요."
        raise RuntimeError(f"구조화 출력이 {max_retries + 1}회 시도 후에도 실패: {last_error}")

    def embed(self, texts: list[str], for_query: bool = False) -> list[list[float]]:
        """텍스트들을 임베딩 벡터로 변환 (배치 처리).

        task_type을 문서/질문으로 구분하는 이유: Gemini 임베딩은 "검색될 문서"와
        "검색하는 질문"을 다른 공간에 최적화한다 — 구분해야 검색 품질이 오른다.
        """
        from google.genai import types

        task_type = "RETRIEVAL_QUERY" if for_query else "RETRIEVAL_DOCUMENT"
        vectors: list[list[float]] = []
        for i in range(0, len(texts), EMBED_BATCH_SIZE):
            batch = texts[i : i + EMBED_BATCH_SIZE]
            self._throttle()
            response = self._client.models.embed_content(
                model=EMBEDDING_MODEL,
                contents=batch,
                config=types.EmbedContentConfig(task_type=task_type),
            )
            self._count()
            vectors.extend([e.values for e in response.embeddings])
        return vectors


_default_client: GeminiClient | None = None


def get_client() -> GeminiClient:
    """모듈 전역 클라이언트 — 호출 수·간격 관리가 프로세스 전체에서 공유되게 한다."""
    global _default_client
    if _default_client is None:
        _default_client = GeminiClient()
    return _default_client
