"""RAG Q&A: 청킹 → 임베딩 → Chroma → 검색 → 근거(슬라이드·타임스탬프) 붙여 답변.

파이프라인 (계획서 핵심 용어의 실전 구현):
1. 청킹: 정렬된 섹션(화면+발화)을 검색 단위로 분할. 발화가 길면 문장 경계에서
   나누되, 조각마다 슬라이드 번호·시간을 메타데이터로 보존한다.
2. 임베딩: Gemini 임베딩(문서용 task_type)으로 벡터화 → Chroma에 저장.
3. 질의: 질문을 질문용 임베딩으로 변환 → 유사 청크 top-k 검색 →
   근거만 사용해 답하라는 프롬프트로 Gemini 호출 → 답변 + 근거 목록.

"근거에 없으면 모른다고 답하라"가 핵심 — RAG의 존재 이유는 환각 억제다.

사용법:
  python -m src.rag <job_id> --build        # 인덱스만 구축
  python -m src.rag <job_id> "질문 내용"     # 질문 (인덱스 없으면 자동 구축)
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from . import config
from .transcribe import format_timestamp

CHUNK_MAX_CHARS = 800  # 검색 단위. 너무 크면 검색이 둔해지고, 너무 작으면 문맥이 부족.
TOP_K = 5

ANSWER_PROMPT = """당신은 강의 내용 전문 조교입니다. 아래 [근거]만 사용해서 [질문]에 답하세요.

규칙:
- 근거에 있는 내용만 답하고, 근거로 답할 수 없으면 "강의에서 다루지 않은 내용입니다"라고 하세요.
- 답변 속 주장 뒤에 해당 근거 번호를 [1], [2] 형식으로 표기하세요.
- 한국어로, 명확하고 간결하게.

[근거]
{context}

[질문]
{question}"""


@dataclass
class Chunk:
    id: str
    text: str
    slide_index: int
    start: float
    end: float
    has_slide: bool = True
    location: str = ""  # 문서 job의 위치 라벨 (p.3, 시트:매출 등)


@dataclass
class Source:
    slide_index: int
    start: float
    text: str
    has_slide: bool = True
    location: str = ""

    @property
    def label(self) -> str:
        """근거 라벨 우선순위: 문서 위치 > 슬라이드+시각 > 시각만 (입력 유형별)."""
        if self.location:
            return self.location
        ts = format_timestamp(self.start)
        return f"슬라이드 {self.slide_index}, {ts}" if self.has_slide else ts


@dataclass
class Answer:
    question: str
    text: str
    sources: list[Source]


def _split_sentences(text: str, max_chars: int) -> list[str]:
    """문장 경계(마침표·물음표 등) 기준으로 max_chars 이하 조각들로 묶는다."""
    sentences = re.split(r"(?<=[.!?다요죠])\s+", text)
    pieces: list[str] = []
    current = ""
    for sent in sentences:
        if current and len(current) + len(sent) + 1 > max_chars:
            pieces.append(current)
            current = sent
        else:
            current = f"{current} {sent}".strip()
    if current:
        pieces.append(current)
    return pieces


def build_chunks(sections: list[dict], max_chars: int = CHUNK_MAX_CHARS) -> list[Chunk]:
    """정렬 섹션 → 검색 청크. 발화가 길면 나누되 각 조각의 시간 범위를 따로 계산한다.

    모든 청크 앞에 슬라이드 요지(첫 줄)를 붙인다 — 발화 조각만으로는
    "이게 무슨 슬라이드 얘기인지" 검색기가 알 수 없기 때문(문맥 주입).
    """
    chunks: list[Chunk] = []
    for sec in sections:
        slide_content = (sec.get("slide_content") or "").strip()
        gist = slide_content.split("\n")[0][:100] if slide_content else ""
        has_slide = bool(sec.get("slide_image"))
        location = sec.get("location") or ""
        if has_slide:
            header = f"[슬라이드 {sec['slide_index']}] {gist}".strip()
        elif location:
            header = f"[{location}]"
        else:
            header = f"[구간 {sec['slide_index']}]"

        # 화면 내용 자체도 검색 대상 (표·수치는 발화에 없는 경우가 많다)
        if slide_content:
            chunks.append(
                Chunk(
                    id=f"s{sec['slide_index']:03d}-screen",
                    text=f"{header}\n(화면 내용)\n{slide_content[:max_chars * 2]}",
                    slide_index=sec["slide_index"],
                    start=sec["start"],
                    end=sec["end"],
                    has_slide=has_slide,
                    location=location,
                )
            )

        speech = sec.get("speech") or []
        if not speech:
            continue
        # 발화를 문자 예산으로 나누되 SpeechLine 경계를 유지해 조각별 시간을 보존
        piece_lines: list[list[dict]] = [[]]
        size = 0
        for line in speech:
            if piece_lines[-1] and size + len(line["text"]) > max_chars:
                piece_lines.append([])
                size = 0
            piece_lines[-1].append(line)
            size += len(line["text"])

        for j, lines in enumerate(piece_lines):
            text = " ".join(l["text"] for l in lines)
            chunks.append(
                Chunk(
                    id=f"s{sec['slide_index']:03d}-speech{j}",
                    text=f"{header}\n(발화)\n{text}",
                    slide_index=sec["slide_index"],
                    start=lines[0]["start"],
                    end=lines[-1]["end"],
                    has_slide=has_slide,
                )
            )
    return chunks


def _collection(job_id: str):
    import chromadb

    client = chromadb.PersistentClient(path=str(config.BASE_DIR / "vectorstore" / job_id))
    return client.get_or_create_collection("lecture", metadata={"hnsw:space": "cosine"})


def build_index(job_id: str) -> int:
    """aligned.json → 청크 → 임베딩 → Chroma. 이미 최신이면 건너뛴다(캐싱)."""
    job_dir = config.JOBS_DIR / job_id
    aligned_path = job_dir / "aligned.json"
    if not aligned_path.exists():
        raise FileNotFoundError(f"aligned.json이 없습니다 — 먼저 4단계(align)를 실행하세요: {job_id}")
    sections = json.loads(aligned_path.read_text(encoding="utf-8"))
    chunks = build_chunks(sections)

    col = _collection(job_id)
    if col.count() == len(chunks):  # 캐시 적중
        print(f"인덱스 최신 상태 (청크 {len(chunks)}개) — 건너뜀")
        return len(chunks)

    from .llm import get_client

    print(f"청크 {len(chunks)}개 임베딩 중...")
    vectors = get_client().embed([c.text for c in chunks])

    # 재구축: 기존 것을 지우고 새로 넣는다 (부분 갱신은 스테일 청크를 남긴다)
    existing = col.get()["ids"]
    if existing:
        col.delete(ids=existing)
    col.add(
        ids=[c.id for c in chunks],
        embeddings=vectors,
        documents=[c.text for c in chunks],
        metadatas=[
            {
                "slide_index": c.slide_index,
                "start": c.start,
                "end": c.end,
                "has_slide": c.has_slide,
                "location": c.location,
            }
            for c in chunks
        ],
    )
    print(f"인덱스 구축 완료: 청크 {len(chunks)}개")
    return len(chunks)


def ask(job_id: str, question: str, top_k: int = TOP_K) -> Answer:
    """질문 → 유사 청크 검색 → 근거 기반 답변 + 출처(슬라이드·타임스탬프)."""
    from .llm import get_client

    client = get_client()
    col = _collection(job_id)
    if col.count() == 0:
        build_index(job_id)
        col = _collection(job_id)

    query_vec = client.embed([question], for_query=True)[0]
    result = col.query(query_embeddings=[query_vec], n_results=min(top_k, col.count()))

    sources: list[Source] = []
    context_parts: list[str] = []
    for i, (doc, meta) in enumerate(zip(result["documents"][0], result["metadatas"][0]), start=1):
        src = Source(
            slide_index=int(meta["slide_index"]),
            start=float(meta["start"]),
            text=doc,
            has_slide=bool(meta.get("has_slide", True)),
            location=str(meta.get("location", "")),
        )
        sources.append(src)
        context_parts.append(f"[{i}] ({src.label})\n{doc}")

    answer_text = client.generate(
        ANSWER_PROMPT.format(context="\n\n".join(context_parts), question=question)
    )
    return Answer(question=question, text=answer_text, sources=sources)


def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="RAG Q&A: 강의 내용 질문답변")
    parser.add_argument("job_id")
    parser.add_argument("question", nargs="?", default=None, help="질문 (생략하면 --build만)")
    parser.add_argument("--build", action="store_true", help="인덱스만 구축")
    args = parser.parse_args()

    if args.build or not args.question:
        build_index(args.job_id)
    if args.question:
        answer = ask(args.job_id, args.question)
        print(f"\n질문: {answer.question}\n")
        print(answer.text)
        print("\n--- 근거 ---")
        for i, src in enumerate(answer.sources, start=1):
            print(f"[{i}] {src.label}")


if __name__ == "__main__":
    _main()
