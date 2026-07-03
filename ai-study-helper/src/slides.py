"""슬라이드 분석 (멀티모달 1순위 기능):
영상에서 슬라이드 전환 감지 → 프레임 캡처 → Gemini 비전으로 내용 추출.

핵심 설계:
- 전환 순간만 캡처한다 — 22분 영상 4만 프레임 중 수십 장만 비전 호출.
  "전체 프레임이 아니라 전환점만"이 멀티모달 비용을 감당 가능하게 만드는 열쇠.
- 캡처 시점은 장면 시작 + 0.5초 — 전환 애니메이션이 끝난 안정된 화면을 잡기 위해.
- 지각 해시(aHash)로 직전 캡처와 중복 판정 — 웹캠·마우스 움직임 같은
  사소한 변화로 감지된 가짜 전환을 비전 호출 전에 걸러낸다.
- 슬라이드 하나 분석할 때마다 slides.json 저장(체크포인트) —
  중간에 한도 초과로 끊겨도 다음 실행이 이어서 진행한다.

사용법: python -m src.slides <job_id> [--threshold 27] [--detect-only]
"""

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from . import config

# 전환 감지 민감도. 낮을수록 민감(전환을 더 많이 잡음). PySceneDetect 기본은 27이지만,
# 강의 녹화는 슬라이드가 화면의 일부(60~70%)라 변화량이 희석된다 — 실측 결과
# 27은 전환의 절반을 놓쳤고(21/45장) 15가 적절했다. 가짜 전환은 지각 해시가 걸러준다.
DETECT_THRESHOLD = 15.0
MIN_SCENE_LEN_SEC = 3.0  # 이보다 짧은 장면은 무시 — 슬라이드 안 삽입영상의 잦은 컷 대응
CAPTURE_OFFSET_SEC = 0.5  # 전환 애니메이션 회피
DUP_HASH_DISTANCE = 5  # aHash 해밍 거리가 이 이하면 같은 슬라이드로 간주

VISION_PROMPT = """이 이미지는 PPT 강의 영상의 한 장면입니다.
화면 중앙의 슬라이드 내용만 추출하세요. 주변 UI(툴바, 하단 썸네일 목록, 웹캠, 채팅창)는 무시하세요.

다음 형식으로 추출:
- 첫 줄: 슬라이드 제목 (없으면 핵심 주제를 한 줄로)
- 본문: 슬라이드의 텍스트 내용 그대로 (불릿 구조 유지)
- 표가 있으면: 마크다운 표로
- 차트/그래프가 있으면: [차트] 로 시작해 축·수치·의미를 설명
- 코드가 있으면: 코드블록으로
- 사진/그림만 있으면: [그림] 으로 시작해 한 줄 설명

슬라이드가 아닌 화면(전체화면 영상 재생, 웹사이트 시연 등)이면 [화면] 으로 시작해 무엇이 보이는지 2~3문장으로 설명하세요.
한국어로 답하세요."""


@dataclass
class Slide:
    index: int
    start: float  # 이 슬라이드가 화면에 나타난 시각(초)
    end: float
    image_path: str
    content: str | None = None  # Gemini 비전 추출 결과 (None이면 아직 미분석)


def detect_transitions(video_path: str | Path, threshold: float = DETECT_THRESHOLD) -> list[tuple[float, float]]:
    """PySceneDetect ContentDetector로 장면(슬라이드) 구간 [(시작, 끝), ...] 감지."""
    from scenedetect import ContentDetector, detect

    scenes = detect(
        str(video_path),
        ContentDetector(threshold=threshold, min_scene_len=int(MIN_SCENE_LEN_SEC * 30)),
        show_progress=False,
    )
    return [(s[0].seconds, s[1].seconds) for s in scenes]


def _ahash(image) -> int:
    """평균 해시(aHash): 8x8 그레이스케일로 줄여 평균보다 밝으면 1.
    슬라이드가 같으면 웹캠·마우스가 움직여도 해시가 거의 같다."""
    import cv2

    small = cv2.resize(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), (8, 8))
    avg = small.mean()
    bits = 0
    for px in small.flatten():
        bits = (bits << 1) | (1 if px > avg else 0)
    return bits


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def capture_slides(video_path: str | Path, scenes: list[tuple[float, float]], out_dir: Path) -> list[Slide]:
    """각 장면의 대표 프레임을 캡처하고, 직전 슬라이드와 중복이면 건너뛴다."""
    import cv2

    out_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video_path))
    slides: list[Slide] = []
    prev_hash: int | None = None
    skipped = 0

    for start, end in scenes:
        t = min(start + CAPTURE_OFFSET_SEC, (start + end) / 2)
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            continue

        h = _ahash(frame)
        if prev_hash is not None and _hamming(h, prev_hash) <= DUP_HASH_DISTANCE:
            # 가짜 전환(웹캠·포인터 움직임) — 직전 슬라이드의 노출 시간만 연장
            slides[-1].end = end
            skipped += 1
            continue
        prev_hash = h

        index = len(slides) + 1
        image_path = out_dir / f"slide_{index:03d}.jpg"
        # cv2.imwrite는 Windows에서 한글 경로에 조용히 실패한다 —
        # 메모리에서 JPEG로 인코딩한 뒤 파이썬 파일 IO로 저장해 우회.
        ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            raise RuntimeError(f"프레임 JPEG 인코딩 실패 (t={t:.1f}s)")
        image_path.write_bytes(encoded.tobytes())
        slides.append(Slide(index=index, start=round(start, 2), end=round(end, 2), image_path=str(image_path)))

    cap.release()
    if skipped:
        print(f"중복 프레임 {skipped}개 건너뜀 (지각 해시 중복 판정)")
    return slides


def _save(slides: list[Slide], path: Path) -> None:
    path.write_text(json.dumps([asdict(s) for s in slides], ensure_ascii=False, indent=2), encoding="utf-8")


def _load(path: Path) -> list[Slide]:
    return [Slide(**s) for s in json.loads(path.read_text(encoding="utf-8"))]


def analyze_job(
    job_id: str,
    threshold: float = DETECT_THRESHOLD,
    detect_only: bool = False,
    on_progress=None,
) -> list[Slide]:
    """job의 영상에서 슬라이드를 감지·캡처하고 Gemini 비전으로 내용을 추출한다.

    단계별 체크포인트:
    1. slides.json이 없으면 → 전환 감지 + 캡처 후 저장 (content=None)
    2. content가 None인 슬라이드만 비전 분석, 한 장 끝날 때마다 저장
    → 도중에 실패해도 재실행하면 이어서 진행된다.
    """
    job_dir = config.JOBS_DIR / job_id
    meta_path = job_dir / "meta.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"job을 찾을 수 없습니다: {job_id} (먼저 ingest를 실행하세요)")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    video_path = meta.get("video_path")
    if not video_path:
        raise ValueError(f"이 job에는 영상이 없습니다 (유형: {meta.get('source_type')})")

    notify = on_progress or (lambda f: None)

    slides_path = job_dir / "slides.json"
    if slides_path.exists():
        slides = _load(slides_path)
        print(f"체크포인트 발견: 슬라이드 {len(slides)}장 (분석 완료 {sum(1 for s in slides if s.content)}장)")
    else:
        print("1/2 슬라이드 전환 감지 중...")
        notify(0.05)  # 감지는 내부 진행률을 알 수 없어 시작·종료 시점만 보고
        scenes = detect_transitions(video_path, threshold=threshold)
        print(f"장면 {len(scenes)}개 감지 → 프레임 캡처·중복 제거 중...")
        slides = capture_slides(video_path, scenes, job_dir / "slides")
        _save(slides, slides_path)
        print(f"슬라이드 {len(slides)}장 확정")

    notify(0.3)  # 감지·캡처 완료 = 30% (이후 70%는 비전 — 실측상 비전이 더 오래 걸린다)

    if detect_only:
        return slides

    pending = [s for s in slides if s.content is None]
    if pending:
        import threading
        from concurrent.futures import ThreadPoolExecutor

        from .llm import MIN_CALL_INTERVAL_SEC, get_client

        client = get_client()
        # 유료 티어(간격 0)면 병렬 8, 무료 티어면 순차 — 간격 제한과 병렬은 무의미한 조합
        workers = 8 if MIN_CALL_INTERVAL_SEC <= 0 else 1
        print(f"2/2 Gemini 비전 분석: {len(pending)}장 (동시 {workers}장)")

        lock = threading.Lock()
        state = {"done": 0, "failed": 0}

        def analyze_one(slide: Slide) -> None:
            try:
                # fast=True: 텍스트 추출에 thinking 불필요 — 빈 응답 방지 + 속도
                content = client.generate(VISION_PROMPT, images=[slide.image_path], fast=True)
            except Exception as e:
                # 한 장의 실패가 전체 분석을 막으면 안 된다 — 표시하고 계속
                content = "[분석 실패]"
                print(f"  slide_{slide.index:03d} 실패: {str(e)[:80]}")
            with lock:  # 체크포인트 저장·진행률은 직렬화 (파일 쓰기 경합 방지)
                slide.content = content
                state["done"] += 1
                state["failed"] += content == "[분석 실패]"
                _save(slides, slides_path)  # 한 장마다 저장 — 중단돼도 이어서 재시작
                notify(0.3 + 0.7 * state["done"] / len(pending))

        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(analyze_one, pending))
        print(f"비전 분석 완료 (Gemini 호출 {client.call_count}회, 실패 {state['failed']}장)")
    return slides


def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="슬라이드 감지 + Gemini 비전 분석")
    parser.add_argument("job_id")
    parser.add_argument("--threshold", type=float, default=DETECT_THRESHOLD, help="전환 감지 민감도 (기본 27, 낮을수록 민감)")
    parser.add_argument("--detect-only", action="store_true", help="감지·캡처만 하고 비전 분석은 생략 (감지 품질 확인용)")
    args = parser.parse_args()

    slides = analyze_job(args.job_id, threshold=args.threshold, detect_only=args.detect_only)
    for s in slides:
        from .transcribe import format_timestamp

        status = "분석됨" if s.content else "미분석"
        title = (s.content or "").split("\n")[0][:50]
        print(f"[{format_timestamp(s.start)}~{format_timestamp(s.end)}] slide_{s.index:03d} ({status}) {title}")


if __name__ == "__main__":
    _main()
