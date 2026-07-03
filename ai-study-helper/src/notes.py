"""노트·요약·목차 생성: 통합 스크립트(음성+슬라이드) → map-reduce로 구조화 노트.

왜 map-reduce인가 (계획서 핵심 용어):
긴 강의는 통째로 LLM 컨텍스트에 넣으면 품질이 떨어지고(중간 내용 무시),
모델 한도도 초과할 수 있다. 그래서
- map: 섹션들을 문자 예산 단위 청크로 묶어 청크별 노트 생성 (병렬 가능한 구조)
- reduce: 청크 노트들을 하나의 일관된 노트로 통합
- 마지막: 전체 요약 + 시간대별 챕터 목차(JSON, 슬라이드 번호 연결)

체크포인트: 청크 노트 하나 생성될 때마다 저장 — 한도 초과로 끊겨도 이어서 재개.

사용법: python -m src.notes <job_id> [--detail 하|중|상]
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from . import config
from .transcribe import format_timestamp

# 청크당 문자 예산. 너무 크면 노트가 뭉개지고, 너무 작으면 호출 수(비용)가 는다.
CHUNK_CHAR_BUDGET = 7000

DETAIL_GUIDE = {
    "하": "핵심 개념 위주로 간결하게. 슬라이드당 1~3개 불릿.",
    "중": "주요 개념과 설명을 균형 있게. 예시는 짧게 언급.",
    "상": "세부 설명·예시·수치까지 최대한 보존. 스스로 공부할 수 있는 수준으로.",
}

MAP_PROMPT = """다음은 PPT 강의 영상의 일부 구간입니다. 각 섹션은 [화면]에 보인 슬라이드 내용과 그때의 [발화]로 구성됩니다.

이 구간의 구조화 학습 노트를 마크다운으로 작성하세요:
- 주제별로 ## 제목을 붙이고 내용은 불릿으로
- 화면의 표·수치·목록 구조는 그대로 보존
- 발화에만 있는 설명(예시, 강조, 이유)을 화면 내용과 통합
- 잡담·인사·수업 운영 멘트는 제외
- 노트는 반드시 한국어로. 원문이 외국어(영어 논문 등)면 번역해 정리하되 전문용어는 원어 병기 (예: 역전파(backpropagation))
- 상세도: {detail}{extra}

{content}"""

# 외국어 문서 + 병기 옵션 (계획서 10-1)
BILINGUAL_GUIDE = "\n- 핵심 주장·정의는 한국어 설명 뒤에 원문 문장을 > 인용으로 병기"

# 논문 구조 인식 (계획서 10-1)
PAPER_GUIDE = (
    "\n- 이 문서는 학술 논문이다. 논문 구조(초록/서론/관련 연구/방법/실험·결과/결론)를"
    " ## 제목으로 삼아 섹션별로 정리하고, 각 섹션의 핵심 기여·수치를 명시"
)

REDUCE_PROMPT = """다음은 한 강의를 구간별로 나눠 만든 노트 조각들입니다. 이를 하나의 일관된 학습 노트로 통합하세요:
- 전체 흐름이 보이도록 대주제(##)-소주제(###) 구조로 재구성
- 구간 경계에서 중복된 내용은 병합
- 표·수치·구조는 보존
- 반드시 한국어로 (전문용어는 원어 병기)
- 상세도: {detail}{extra}

{content}"""

SUMMARY_TOC_PROMPT = """다음은 PPT 강의의 구간별 정보입니다 (구간 번호, 시간, 슬라이드 요지).

두 가지를 만들어 반드시 아래 JSON 형식으로만 응답하세요 (다른 텍스트 금지):
{{
  "summary": "강의 전체 요약 (3~5문장)",
  "chapters": [
    {{"title": "챕터 제목", "start": 시작초, "end": 종료초, "slides": [슬라이드 번호들]}}
  ]
}}

챕터는 내용 흐름이 바뀌는 지점 기준 4~8개로 나누고, 시간이 겹치지 않게 하세요.
잡담·인사 구간은 가장 가까운 챕터에 포함시키세요.

{content}"""


@dataclass
class NotesResult:
    notes_md: str
    summary: str
    chapters: list[dict]


def chunk_sections(sections: list[dict], budget: int = CHUNK_CHAR_BUDGET) -> list[list[dict]]:
    """연속된 섹션을 문자 예산 단위로 묶는다. 섹션 하나가 예산을 넘어도 쪼개지 않는다
    (화면+발화 쌍을 찢으면 문맥이 깨진다 — 예산은 소프트 리밋)."""
    chunks: list[list[dict]] = []
    current: list[dict] = []
    size = 0
    for sec in sections:
        sec_size = len(sec.get("slide_content") or "") + sum(len(l["text"]) for l in sec["speech"])
        if current and size + sec_size > budget:
            chunks.append(current)
            current, size = [], 0
        current.append(sec)
        size += sec_size
    if current:
        chunks.append(current)
    return chunks


def _render_chunk(chunk: list[dict]) -> str:
    """청크를 LLM 입력 텍스트로 직렬화."""
    parts: list[str] = []
    for sec in chunk:
        speech = " ".join(l["text"] for l in sec["speech"]) or "(발화 없음)"
        where = sec.get("location") or f"{format_timestamp(sec['start'])}~{format_timestamp(sec['end'])}"
        parts.append(
            f"[섹션 {sec['slide_index']} | {where}]\n"
            f"[화면]\n{(sec.get('slide_content') or '(없음)').strip()}\n[발화]\n{speech}"
        )
    return "\n\n".join(parts)


def _render_toc_input(sections: list[dict]) -> str:
    """목차 생성용 경량 입력: 슬라이드 요지 첫 줄만 — 토큰 절약."""
    lines = []
    for sec in sections:
        gist = (sec.get("slide_content") or "").strip().split("\n")[0][:80]
        where = sec.get("location") or f"{sec['start']:.0f}~{sec['end']:.0f}초"
        lines.append(f"섹션 {sec['slide_index']} | {where} | {gist}")
    return "\n".join(lines)


def extract_json(text: str) -> dict:
    """LLM 응답에서 JSON을 꺼낸다. ```json 펜스·앞뒤 잡설을 방어적으로 제거."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"응답에서 JSON을 찾을 수 없습니다: {text[:200]}")
    return json.loads(text[start : end + 1])


def _validate_chapters(data: dict, max_slide: int) -> list[dict]:
    """챕터 JSON 검증 — 형식 위반은 여기서 잡아 재시도로 보낸다 (구조화 출력 안정성)."""
    chapters = data.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        raise ValueError("chapters가 비어 있습니다")
    for ch in chapters:
        if not isinstance(ch.get("title"), str) or not ch["title"].strip():
            raise ValueError(f"챕터 제목이 없습니다: {ch}")
        if not isinstance(ch.get("start"), (int, float)) or not isinstance(ch.get("end"), (int, float)):
            raise ValueError(f"챕터 시간이 숫자가 아닙니다: {ch}")
        slides = ch.get("slides", [])
        ch["slides"] = [s for s in slides if isinstance(s, int) and 1 <= s <= max_slide]
    return chapters


def generate_notes(job_id: str, detail: str = "중", bilingual: bool = False) -> NotesResult:
    """aligned.json → 노트·요약·목차. 청크별 체크포인트로 이어서 재개 가능.

    bilingual=True면 핵심 문장에 원문을 인용 병기 (외국어 문서용 옵션).
    문서가 논문 구조면(meta.doc_is_paper) 섹션별 요약 지침이 자동 활성화된다."""
    if detail not in DETAIL_GUIDE:
        raise ValueError(f"상세도는 {list(DETAIL_GUIDE)} 중 하나여야 합니다: {detail}")

    job_dir = config.JOBS_DIR / job_id
    aligned_path = job_dir / "aligned.json"
    if not aligned_path.exists():
        raise FileNotFoundError(f"aligned.json이 없습니다 — 먼저 4단계(align)를 실행하세요: {job_id}")
    sections = json.loads(aligned_path.read_text(encoding="utf-8"))

    # 외국어·논문 경로 분기 (계획서 10-1)
    meta = json.loads((job_dir / "meta.json").read_text(encoding="utf-8"))
    extra = ""
    if meta.get("doc_is_paper"):
        extra += PAPER_GUIDE
        print("논문 구조 감지 → 섹션별 요약 모드")
    if bilingual:
        extra += BILINGUAL_GUIDE
    if meta.get("doc_language") == "en":
        print("외국어(영어) 문서 → 한국어 학습자료 생성 모드")

    from .llm import get_client

    client = get_client()

    # --- map: 청크별 노트 (체크포인트) ---
    chunks = chunk_sections(sections)
    chunk_notes_path = job_dir / "notes_chunks.json"
    chunk_notes: list[str | None] = (
        json.loads(chunk_notes_path.read_text(encoding="utf-8"))
        if chunk_notes_path.exists()
        else [None] * len(chunks)
    )
    if len(chunk_notes) != len(chunks):  # 청크 구성이 바뀌었으면 처음부터
        chunk_notes = [None] * len(chunks)

    import threading
    from concurrent.futures import ThreadPoolExecutor

    from .llm import MIN_CALL_INTERVAL_SEC

    workers = 8 if MIN_CALL_INTERVAL_SEC <= 0 else 1  # 유료 티어면 map 병렬
    print(f"map: 청크 {len(chunks)}개 (완료 {sum(1 for c in chunk_notes if c)}개, 동시 {workers})")
    save_lock = threading.Lock()

    def map_one(i: int) -> None:
        chunk_notes[i] = client.generate(
            MAP_PROMPT.format(detail=DETAIL_GUIDE[detail], extra=extra, content=_render_chunk(chunks[i]))
        )
        with save_lock:  # 청크별 체크포인트 — 병렬이어도 저장은 직렬화
            chunk_notes_path.write_text(json.dumps(chunk_notes, ensure_ascii=False), encoding="utf-8")
        print(f"  청크 {i + 1}/{len(chunks)} 완료")

    todo = [i for i in range(len(chunks)) if not chunk_notes[i]]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(map_one, todo))

    # --- reduce: 통합 노트 ---
    print("reduce: 노트 통합 중...")
    notes_md = client.generate(
        REDUCE_PROMPT.format(detail=DETAIL_GUIDE[detail], extra=extra, content="\n\n---\n\n".join(chunk_notes))
    )

    # --- 요약 + 시간대별 목차 (JSON, 검증 실패 시 1회 재시도) ---
    print("요약·목차 생성 중...")
    toc_input = _render_toc_input(sections)
    max_slide = max(s["slide_index"] for s in sections)
    prompt = SUMMARY_TOC_PROMPT.format(content=toc_input)
    try:
        data = extract_json(client.generate(prompt))
        chapters = _validate_chapters(data, max_slide)
    except (ValueError, json.JSONDecodeError) as e:
        print(f"  목차 JSON 검증 실패({e}) → 재시도")
        data = extract_json(client.generate(prompt + f"\n\n직전 응답은 이 문제로 거부됐습니다: {e}\nJSON만 출력하세요."))
        chapters = _validate_chapters(data, max_slide)
    summary = str(data.get("summary", "")).strip()

    # --- 저장 ---
    slide_images = {s["slide_index"]: s["slide_image"] for s in sections}
    toc_lines = ["# 시간대별 목차", ""]
    for ch in chapters:
        toc_lines.append(f"- **[{format_timestamp(ch['start'])}~{format_timestamp(ch['end'])}] {ch['title']}**")
        for idx in ch["slides"][:1]:  # 챕터 대표 썸네일 1장 (슬라이드 없는 job은 생략)
            if slide_images.get(idx):
                toc_lines.append(f"  ![슬라이드 {idx}]({slide_images[idx]})")
    final_md = f"# 요약\n\n{summary}\n\n{chr(10).join(toc_lines)}\n\n# 학습 노트\n\n{notes_md}"

    (job_dir / "notes.md").write_text(final_md, encoding="utf-8")
    (job_dir / "chapters.json").write_text(
        json.dumps({"summary": summary, "chapters": chapters}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"완료 (Gemini 호출 {client.call_count}회) → notes.md, chapters.json")
    return NotesResult(notes_md=final_md, summary=summary, chapters=chapters)


def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="구조화 노트·요약·시간대별 목차 생성")
    parser.add_argument("job_id")
    parser.add_argument("--detail", default="중", choices=list(DETAIL_GUIDE), help="노트 상세도 (기본: 중)")
    parser.add_argument("--bilingual", action="store_true", help="핵심 문장에 원문 인용 병기 (외국어 문서용)")
    args = parser.parse_args()

    result = generate_notes(args.job_id, detail=args.detail, bilingual=args.bilingual)
    print(f"\n요약: {result.summary}\n")
    for ch in result.chapters:
        print(f"[{format_timestamp(ch['start'])}~{format_timestamp(ch['end'])}] {ch['title']} (슬라이드 {ch['slides'][:5]}{'...' if len(ch['slides']) > 5 else ''})")


if __name__ == "__main__":
    _main()
