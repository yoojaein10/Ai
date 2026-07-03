"""음성·슬라이드 정렬: STT 세그먼트와 슬라이드를 시간축으로 결합해 통합 스크립트 생성.

"이 슬라이드가 떠 있는 동안 강사가 무슨 말을 했나"를 만드는 단계.
멀티모달 파이프라인의 허리로, 이후 모든 단계가 이 결과물을 먹는다:
- 5단계 노트·요약: 섹션(슬라이드+발화) 단위로 map-reduce
- 6단계 RAG: 섹션 단위 청킹 + "근거: 슬라이드 N, 12:34" 표시

정렬 규칙: 발화 세그먼트의 중간 시점(midpoint)이 속한 슬라이드 구간에 배정한다.
경계에 걸친 세그먼트(말하는 도중 슬라이드 전환)는 발화의 무게중심이 있는 쪽으로
가는 것이 자연스럽기 때문이다.

사용법: python -m src.align <job_id>
"""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import config
from .transcribe import format_timestamp


@dataclass
class SpeechLine:
    start: float
    end: float
    text: str


@dataclass
class AlignedSection:
    """섹션 = 슬라이드 1장 + 발화들, 또는 문서의 한 위치(페이지·시트) 분량.

    location: 문서 job에서 "p.3" 같은 위치 라벨 (영상 job은 빈 문자열 —
    슬라이드 번호·타임스탬프가 그 역할을 한다)."""

    slide_index: int
    start: float
    end: float
    slide_image: str
    slide_content: str
    speech: list[SpeechLine] = field(default_factory=list)
    location: str = ""

    @property
    def speech_text(self) -> str:
        return " ".join(line.text for line in self.speech)


def align(segments: list[dict], slides: list[dict]) -> list[AlignedSection]:
    """STT 세그먼트를 중간 시점 기준으로 슬라이드 구간에 배정한다.

    segments/slides는 transcript.json/slides.json의 dict 그대로 받는다 —
    두 모듈의 산출물(파일)이 인터페이스이고, 이 함수는 파일 간 결합만 담당.
    """
    sections = [
        AlignedSection(
            slide_index=s["index"],
            start=s["start"],
            end=s["end"],
            slide_image=s["image_path"],
            slide_content=s["content"] or "",
        )
        for s in sorted(slides, key=lambda s: s["start"])
    ]
    if not sections:
        return []

    for seg in sorted(segments, key=lambda x: x["start"]):
        midpoint = (seg["start"] + seg["end"]) / 2
        target = sections[-1]  # 마지막 슬라이드 종료 후 발화는 마지막 섹션으로
        for sec in sections:
            if sec.start <= midpoint < sec.end:
                target = sec
                break
        target.speech.append(SpeechLine(start=seg["start"], end=seg["end"], text=seg["text"]))
    return sections


def format_aligned_markdown(sections: list[AlignedSection]) -> str:
    """사람이 검토하기 좋은 마크다운: 슬라이드 내용 + 그 구간의 발화."""
    lines: list[str] = []
    for sec in sections:
        lines.append(f"## 슬라이드 {sec.slide_index} [{format_timestamp(sec.start)}~{format_timestamp(sec.end)}]")
        lines.append("")
        lines.append("### 화면")
        lines.append(sec.slide_content.strip() or "(내용 없음)")
        lines.append("")
        lines.append("### 발화")
        if sec.speech:
            lines.append(" ".join(line.text for line in sec.speech))
        else:
            lines.append("(발화 없음)")
        lines.append("")
    return "\n".join(lines)


def pseudo_sections_from_transcript(segments: list[dict], window_sec: float = 90.0) -> list[AlignedSection]:
    """슬라이드가 없는 입력(유튜브 오디오·음성 파일)용 유사 섹션 생성.

    발화를 시간 창 단위로 묶어 슬라이드 없는 섹션을 만든다 — 이후 단계(노트·RAG)가
    영상 job과 동일한 인터페이스(aligned.json)로 동작하게 하는 어댑터.
    slide_image=""가 "슬라이드 없음" 표시다.
    """
    sections: list[AlignedSection] = []
    for seg in sorted(segments, key=lambda x: x["start"]):
        if not sections or seg["start"] >= sections[-1].start + window_sec:
            sections.append(
                AlignedSection(
                    slide_index=len(sections) + 1,
                    start=seg["start"],
                    end=seg["end"],
                    slide_image="",
                    slide_content="",
                )
            )
        sections[-1].speech.append(SpeechLine(start=seg["start"], end=seg["end"], text=seg["text"]))
        sections[-1].end = seg["end"]
    return sections


def sections_from_document(doc_segments: list[dict]) -> list[AlignedSection]:
    """문서 세그먼트(위치+텍스트) → 섹션. 문서는 시간이 없으므로 start/end는 0,
    위치 라벨(p.3 등)이 근거 표시를 담당한다."""
    sections: list[AlignedSection] = []
    for seg in doc_segments:
        if not seg["text"].strip():
            continue
        sections.append(
            AlignedSection(
                slide_index=len(sections) + 1,
                start=0.0,
                end=0.0,
                slide_image="",
                slide_content=seg["text"],
                location=seg["location"],
            )
        )
    return sections


def align_job(job_id: str) -> list[AlignedSection]:
    """job의 transcript + slides를 정렬한다. 이미 있으면 저장된 결과 반환(체크포인트).

    입력 유형별 경로: 영상=음성·슬라이드 정렬 / 오디오=시간 창 유사 섹션 /
    문서=위치 기반 섹션. 셋 다 같은 aligned.json 인터페이스로 수렴한다."""
    job_dir = config.JOBS_DIR / job_id
    aligned_path = job_dir / "aligned.json"
    if aligned_path.exists():
        data = json.loads(aligned_path.read_text(encoding="utf-8"))
        return [
            AlignedSection(**{**d, "speech": [SpeechLine(**l) for l in d["speech"]]})
            for d in data
        ]

    meta = json.loads((job_dir / "meta.json").read_text(encoding="utf-8"))

    if meta.get("source_type") == "document":
        doc_segments = json.loads((job_dir / "document.json").read_text(encoding="utf-8"))
        sections = sections_from_document(doc_segments)
        aligned_path.write_text(
            json.dumps([asdict(s) for s in sections], ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (job_dir / "aligned.md").write_text(format_aligned_markdown(sections), encoding="utf-8")
        return sections

    transcript_path = job_dir / "transcript.json"
    slides_path = job_dir / "slides.json"
    if not transcript_path.exists():
        raise FileNotFoundError(f"transcript.json이 없습니다 — 먼저 2단계(transcribe)를 실행하세요: {job_id}")

    segments = json.loads(transcript_path.read_text(encoding="utf-8"))["segments"]
    if slides_path.exists():
        slides = json.loads(slides_path.read_text(encoding="utf-8"))
        sections = align(segments, slides)
    elif meta.get("video_path"):
        # 영상인데 슬라이드 분석이 안 된 상태 — 건너뛰지 말고 명확히 실패
        raise FileNotFoundError(f"slides.json이 없습니다 — 먼저 3단계(slides)를 실행하세요: {job_id}")
    else:
        sections = pseudo_sections_from_transcript(segments)
    aligned_path.write_text(
        json.dumps([asdict(s) for s in sections], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (job_dir / "aligned.md").write_text(format_aligned_markdown(sections), encoding="utf-8")
    return sections


def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="음성·슬라이드 정렬 → 통합 스크립트")
    parser.add_argument("job_id")
    args = parser.parse_args()

    sections = align_job(args.job_id)
    total_speech = sum(len(s.speech) for s in sections)
    silent = [s.slide_index for s in sections if not s.speech]
    print(f"섹션 {len(sections)}개 생성 (발화 세그먼트 {total_speech}개 배정)")
    if silent:
        print(f"발화 없는 슬라이드: {silent}")
    for sec in sections[:5]:
        preview = sec.speech_text[:60]
        print(f"[{format_timestamp(sec.start)}~{format_timestamp(sec.end)}] 슬라이드 {sec.slide_index}: {preview}...")


if __name__ == "__main__":
    _main()
