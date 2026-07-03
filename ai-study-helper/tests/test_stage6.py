"""6단계 테스트: 청킹(시간 메타데이터 보존), 문장 분할, Chroma 검색(가짜 임베딩).

Gemini 임베딩·생성은 API가 필요해 수동 검증으로 하고,
벡터DB 저장·검색은 가짜 벡터로 로컬에서 실제 Chroma를 돌려 검증한다.
"""

import pytest

from src.rag import Chunk, Source, _split_sentences, build_chunks


def _sec(index, speech_texts, content="슬라이드 제목\n본문 내용"):
    t = index * 100.0
    speech = []
    for i, text in enumerate(speech_texts):
        speech.append({"start": t + i * 10, "end": t + i * 10 + 8, "text": text})
    return {
        "slide_index": index,
        "start": t,
        "end": t + 100,
        "slide_image": f"slide_{index:03d}.jpg",
        "slide_content": content,
        "speech": speech,
    }


# --- 청킹 -------------------------------------------------------------------

def test_build_chunks_screen_and_speech():
    chunks = build_chunks([_sec(1, ["첫 발화입니다."])])
    ids = [c.id for c in chunks]
    assert "s001-screen" in ids   # 화면 내용도 검색 대상
    assert "s001-speech0" in ids


def test_build_chunks_header_injected():
    """발화 조각에도 슬라이드 요지가 붙어야 검색기가 문맥을 안다."""
    chunks = build_chunks([_sec(3, ["발화."])])
    speech_chunk = next(c for c in chunks if c.id == "s003-speech0")
    assert "[슬라이드 3] 슬라이드 제목" in speech_chunk.text


def test_build_chunks_long_speech_split_with_timestamps():
    """긴 발화는 나뉘고, 각 조각의 시간은 자기 구간을 가리켜야 한다."""
    texts = ["가" * 300, "나" * 300, "다" * 300, "라" * 300]
    chunks = build_chunks([_sec(1, texts)], max_chars=600)
    speech_chunks = [c for c in chunks if "speech" in c.id]

    assert len(speech_chunks) >= 2
    # 두 번째 조각의 시작 시간은 첫 조각보다 뒤여야 한다 (섹션 시작이 아니라)
    assert speech_chunks[1].start > speech_chunks[0].start


def test_build_chunks_no_speech_section():
    chunks = build_chunks([_sec(1, [], content="화면만 있는 슬라이드")])
    assert len(chunks) == 1
    assert chunks[0].id == "s001-screen"


def test_build_chunks_no_content_no_speech():
    chunks = build_chunks([_sec(1, [], content="")])
    assert chunks == []


# --- 문장 분할 ----------------------------------------------------------------

def test_split_sentences_respects_max():
    text = "첫 문장입니다. 둘째 문장입니다. 셋째 문장입니다."
    pieces = _split_sentences(text, max_chars=15)
    assert all(len(p) <= 25 for p in pieces)  # 문장 하나가 한도 근처면 약간 초과 허용
    assert "".join(pieces).replace(" ", "") == text.replace(" ", "")  # 유실 없음


# --- Chroma 저장·검색 (가짜 임베딩) ---------------------------------------------

def test_chroma_roundtrip(tmp_path):
    import chromadb

    client = chromadb.PersistentClient(path=str(tmp_path))
    col = client.get_or_create_collection("test", metadata={"hnsw:space": "cosine"})
    col.add(
        ids=["a", "b"],
        embeddings=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        documents=["16% 통계 얘기", "수입형 전략 얘기"],
        metadatas=[{"slide_index": 6, "start": 90.0, "end": 120.0},
                   {"slide_index": 11, "start": 300.0, "end": 360.0}],
    )
    # [1,0,0]에 가까운 질의 → "a"가 1등이어야 한다
    result = col.query(query_embeddings=[[0.9, 0.1, 0.0]], n_results=2)
    assert result["ids"][0][0] == "a"
    assert result["metadatas"][0][0]["slide_index"] == 6


def test_source_label_format():
    src = Source(slide_index=6, start=94.5, text="...")
    assert src.label == "슬라이드 6, 01:34"
