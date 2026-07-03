"""학습 콘텐츠 생성: 퀴즈 (8단계) · 플래시카드 (9단계) · 마인드맵 (10단계).

구조화 출력 파이프라인 (계획서 "핵심 기술 포인트"):
Pydantic 스키마 정의 → Gemini 네이티브 구조화 출력(모델 단 형식 강제)
→ 타입 검증 → 의미 검증(정답이 보기에 있는가 등) → 실패 시 오류 되먹임 재시도.

형식은 스키마가 보장하지만 "말이 되는지"는 못 보장한다 — 그래서 의미 검증이
따로 있다. 예: 객관식 정답이 보기 목록에 없으면 형식상 유효해도 퀴즈로는 불량.

사용법: python -m src.generate <job_id> quiz [--count 10] [--difficulty 보통]
"""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from . import config

DIFFICULTIES = ["쉬움", "보통", "어려움"]

DIFFICULTY_GUIDE = {
    "쉬움": "노트에 명시된 사실을 그대로 묻는 기억 확인 문제.",
    "보통": "개념 이해를 확인하는 문제. 사실 + 이유·차이를 묻는다.",
    "어려움": "개념을 새 상황에 적용하거나 여러 개념을 연결해야 풀리는 문제.",
}

QUIZ_PROMPT = """다음 강의 노트를 바탕으로 퀴즈 {count}문항을 만드세요.

규칙:
- 객관식(multiple_choice)과 단답형(short_answer)을 섞을 것 (객관식 위주, 약 7:3)
- 객관식은 보기(options) 정확히 4개, answer는 보기 중 하나와 글자까지 동일해야 함
- 단답형은 options를 빈 목록으로, answer는 한두 단어의 명확한 정답
- explanation은 왜 그게 정답인지 노트 내용으로 설명
- source_slide는 문제 근거가 된 슬라이드 번호 (노트에 없으면 0)
- 난이도: {difficulty} — {difficulty_guide}
- 문제·보기·해설 모두 한국어

[강의 노트]
{notes}"""


FLASHCARD_PROMPT = """다음 강의 노트에서 핵심 개념·용어 플래시카드 {count}장을 만드세요.

규칙:
- front: 용어 하나 또는 한 문장 질문 (앞면만 보고 답을 떠올리는 훈련용)
- back: 답 또는 설명. 1~3문장, 노트 내용에 근거할 것
- front에 답이 들어가면 안 됨 (예: front "수입형이란 대본을 가져오는 것인가?" ← 나쁨)
- 서로 다른 개념을 다룰 것 (중복 금지), 중요도 높은 개념부터
- source_slide는 근거 슬라이드 번호 (모르면 0)
- 모두 한국어

[강의 노트]
{notes}"""


class Flashcard(BaseModel):
    front: str = Field(min_length=2)
    back: str = Field(min_length=2)
    source_slide: int = 0


class FlashcardDeck(BaseModel):
    cards: list[Flashcard]


GLOSSARY_PROMPT = """다음 강의 노트에서 전문 용어 {count}개 안팎을 뽑아 용어집을 만드세요.

규칙:
- term: 원어 용어 (영어 논문이면 영어 원어, 한국어 자료면 한국어 용어)
- korean: 한국어 번역·표기 (원어가 한국어면 동일하게)
- definition: 이 자료의 맥락에 맞는 1~2문장 한국어 설명
- 중요도 높은 용어부터, 중복 금지

[강의 노트]
{notes}"""


class GlossaryTerm(BaseModel):
    term: str = Field(min_length=1)
    korean: str = Field(min_length=1)
    definition: str = Field(min_length=5)


class Glossary(BaseModel):
    terms: list[GlossaryTerm]


MINDMAP_PROMPT = """다음 강의 노트의 개념 구조를 마인드맵으로 만드세요.

규칙:
- 노드는 평면 목록으로, parent_id로 부모를 가리킴 (트리 구조)
- 루트 노드는 정확히 1개, parent_id는 빈 문자열 "" — 강의 전체 주제
- 루트 바로 아래는 대주제 3~7개, 그 아래 세부 개념 (전체 깊이 3~4단계)
- label은 간결하게 (2~15자 권장), 노트의 용어를 그대로 사용
- id는 "n1", "n2" 같은 짧은 고유 문자열
- 전체 노드 수 {count}개 안팎
- 모두 한국어

[강의 노트]
{notes}"""


class MindmapNode(BaseModel):
    id: str = Field(min_length=1)
    label: str = Field(min_length=1, max_length=60)
    parent_id: str = ""  # "" = 루트


class Mindmap(BaseModel):
    nodes: list[MindmapNode]


class QuizQuestion(BaseModel):
    type: Literal["multiple_choice", "short_answer"]
    question: str = Field(min_length=5)
    options: list[str]  # 객관식 4개, 단답형은 빈 목록
    answer: str = Field(min_length=1)
    explanation: str = Field(min_length=5)
    source_slide: int = 0


class Quiz(BaseModel):
    questions: list[QuizQuestion]


def validate_quiz(quiz: Quiz, expected_count: int) -> list[str]:
    """의미 검증 — 스키마가 못 잡는 품질 문제를 잡는다. 반환: 문제점 목록(비면 통과)."""
    problems: list[str] = []
    if len(quiz.questions) < max(1, int(expected_count * 0.7)):
        problems.append(f"문항 수 부족: {len(quiz.questions)}/{expected_count}")
    for i, q in enumerate(quiz.questions, start=1):
        if q.type == "multiple_choice":
            if len(q.options) != 4:
                problems.append(f"{i}번: 보기가 4개가 아님 ({len(q.options)}개)")
            elif q.answer not in q.options:
                problems.append(f"{i}번: 정답 '{q.answer}'이 보기에 없음")
            elif len(set(q.options)) != 4:
                problems.append(f"{i}번: 중복된 보기 존재")
        else:  # short_answer
            if q.options:
                problems.append(f"{i}번: 단답형인데 보기가 있음")
    return problems


def generate_quiz(job_id: str, count: int = 10, difficulty: str = "보통") -> Quiz:
    """노트 기반 퀴즈 생성. 의미 검증 실패 시 문제점을 되먹여 1회 재생성."""
    if difficulty not in DIFFICULTIES:
        raise ValueError(f"난이도는 {DIFFICULTIES} 중 하나여야 합니다: {difficulty}")

    job_dir = config.JOBS_DIR / job_id
    notes_path = job_dir / "notes.md"
    if not notes_path.exists():
        raise FileNotFoundError(f"notes.md가 없습니다 — 먼저 5단계(notes)를 실행하세요: {job_id}")
    notes = notes_path.read_text(encoding="utf-8")

    from .llm import get_client

    client = get_client()
    prompt = QUIZ_PROMPT.format(
        count=count, difficulty=difficulty, difficulty_guide=DIFFICULTY_GUIDE[difficulty], notes=notes
    )

    quiz: Quiz = client.generate_structured(prompt, Quiz)
    problems = validate_quiz(quiz, count)
    if problems:
        print(f"의미 검증 실패({len(problems)}건) → 재생성: {problems[:3]}")
        retry_prompt = f"{prompt}\n\n직전 생성본의 문제점 — 모두 고치세요:\n" + "\n".join(problems)
        quiz = client.generate_structured(retry_prompt, Quiz)
        problems = validate_quiz(quiz, count)
        if problems:
            # 남은 불량 문항만 버리고 정상 문항은 살린다 (전체 실패보다 낫다)
            bad_idx = {int(p.split("번")[0]) - 1 for p in problems if p[0].isdigit()}
            quiz = Quiz(questions=[q for i, q in enumerate(quiz.questions) if i not in bad_idx])
            print(f"불량 문항 {len(bad_idx)}개 제외, {len(quiz.questions)}개 확정")

    out_path = job_dir / f"quiz_{difficulty}.json"
    out_path.write_text(quiz.model_dump_json(indent=2), encoding="utf-8")
    print(f"퀴즈 {len(quiz.questions)}문항 저장: {out_path.name} (Gemini 호출 {client.call_count}회)")
    return quiz


# 뒷면이 이런 글자로 끝나면 문장이 중간에서 잘린 것 (조사·연결어미로 끝나는 한국어 문장은 없다)
_TRUNCATION_ENDINGS = ("은", "는", "이", "가", "을", "를", "의", "에", "와", "과", "로", "고", ",")


def validate_flashcards(deck: FlashcardDeck, expected_count: int) -> list[str]:
    """플래시카드 의미 검증: 중복 앞면, 앞면에 답 노출(앞뒤 동일), 문장 절단, 수량."""
    problems: list[str] = []
    if len(deck.cards) < max(1, int(expected_count * 0.7)):
        problems.append(f"카드 수 부족: {len(deck.cards)}/{expected_count}")
    seen: set[str] = set()
    for i, card in enumerate(deck.cards, start=1):
        key = "".join(card.front.lower().split())
        if key in seen:
            problems.append(f"{i}번: 중복된 앞면 '{card.front[:30]}'")
        seen.add(key)
        if "".join(card.front.split()) == "".join(card.back.split()):
            problems.append(f"{i}번: 앞면과 뒷면이 동일")
        back = card.back.strip()
        if back.endswith(_TRUNCATION_ENDINGS):
            problems.append(f"{i}번: 뒷면 문장이 중간에서 잘림 ('...{back[-15:]}')")
    return problems


def generate_flashcards(job_id: str, count: int = 15) -> FlashcardDeck:
    """노트 기반 플래시카드 생성. 검증 실패 시 되먹임 재생성 → 불량 카드만 제외."""
    job_dir = config.JOBS_DIR / job_id
    notes_path = job_dir / "notes.md"
    if not notes_path.exists():
        raise FileNotFoundError(f"notes.md가 없습니다 — 먼저 5단계(notes)를 실행하세요: {job_id}")
    notes = notes_path.read_text(encoding="utf-8")

    from .llm import get_client

    client = get_client()
    prompt = FLASHCARD_PROMPT.format(count=count, notes=notes)

    deck: FlashcardDeck = client.generate_structured(prompt, FlashcardDeck)
    problems = validate_flashcards(deck, count)
    if problems:
        print(f"의미 검증 실패({len(problems)}건) → 재생성: {problems[:3]}")
        retry_prompt = f"{prompt}\n\n직전 생성본의 문제점 — 모두 고치세요:\n" + "\n".join(problems)
        deck = client.generate_structured(retry_prompt, FlashcardDeck)
        problems = validate_flashcards(deck, count)
        if problems:
            bad_idx = {int(p.split("번")[0]) - 1 for p in problems if p[0].isdigit()}
            deck = FlashcardDeck(cards=[c for i, c in enumerate(deck.cards) if i not in bad_idx])
            print(f"불량 카드 {len(bad_idx)}개 제외, {len(deck.cards)}개 확정")

    out_path = job_dir / "flashcards.json"
    out_path.write_text(deck.model_dump_json(indent=2), encoding="utf-8")
    print(f"플래시카드 {len(deck.cards)}장 저장: {out_path.name} (Gemini 호출 {client.call_count}회)")
    return deck


def validate_glossary(glossary: Glossary, expected_count: int) -> list[str]:
    """용어집 의미 검증: 중복 용어, 수량."""
    problems: list[str] = []
    if len(glossary.terms) < max(1, int(expected_count * 0.5)):
        problems.append(f"용어 수 부족: {len(glossary.terms)}/{expected_count}")
    seen: set[str] = set()
    for i, t in enumerate(glossary.terms, start=1):
        key = "".join(t.term.lower().split())
        if key in seen:
            problems.append(f"{i}번: 중복된 용어 '{t.term}'")
        seen.add(key)
    return problems


def generate_glossary(job_id: str, count: int = 20) -> Glossary:
    """노트 기반 용어집 생성 (원어-한국어 대응) — 계획서 10-1."""
    job_dir = config.JOBS_DIR / job_id
    notes_path = job_dir / "notes.md"
    if not notes_path.exists():
        raise FileNotFoundError(f"notes.md가 없습니다 — 먼저 5단계(notes)를 실행하세요: {job_id}")

    from .llm import get_client

    client = get_client()
    prompt = GLOSSARY_PROMPT.format(count=count, notes=notes_path.read_text(encoding="utf-8"))

    glossary: Glossary = client.generate_structured(prompt, Glossary)
    problems = validate_glossary(glossary, count)
    if problems:
        print(f"의미 검증 실패({len(problems)}건) → 재생성: {problems[:3]}")
        glossary = client.generate_structured(
            f"{prompt}\n\n직전 생성본의 문제점 — 모두 고치세요:\n" + "\n".join(problems), Glossary
        )
        problems = validate_glossary(glossary, count)
        if problems:
            bad_idx = {int(p.split("번")[0]) - 1 for p in problems if p[0].isdigit()}
            glossary = Glossary(terms=[t for i, t in enumerate(glossary.terms) if i not in bad_idx])

    (job_dir / "glossary.json").write_text(glossary.model_dump_json(indent=2), encoding="utf-8")
    print(f"용어집 {len(glossary.terms)}개 저장: glossary.json (Gemini 호출 {client.call_count}회)")
    return glossary


def validate_mindmap(mindmap: Mindmap) -> list[str]:
    """마인드맵 구조 검증: 루트 유일성, 고아 노드(없는 부모), 순환, id 중복."""
    problems: list[str] = []
    ids = [n.id for n in mindmap.nodes]
    if len(ids) != len(set(ids)):
        problems.append("중복된 노드 id 존재")
    id_set = set(ids)

    roots = [n for n in mindmap.nodes if not n.parent_id]
    if len(roots) != 1:
        problems.append(f"루트 노드가 {len(roots)}개 (정확히 1개여야 함)")

    by_id = {n.id: n for n in mindmap.nodes}
    for n in mindmap.nodes:
        if n.parent_id and n.parent_id not in id_set:
            problems.append(f"'{n.label}': 존재하지 않는 부모 id '{n.parent_id}'")
            continue
        # 순환 감지: 부모를 따라 올라가며 자기 자신을 다시 만나면 순환
        seen = {n.id}
        cur = n
        while cur.parent_id:
            if cur.parent_id in seen:
                problems.append(f"'{n.label}': 순환 참조 감지")
                break
            if cur.parent_id not in by_id:
                break
            seen.add(cur.parent_id)
            cur = by_id[cur.parent_id]
    return problems


def _mermaid_label(label: str) -> str:
    """Mermaid 문법과 충돌하는 문자를 정리 (반각 괄호는 노드 모양 문법으로 해석된다).

    반각 → 전각 치환으로 뜻은 보존하면서 문법 충돌만 제거한다."""
    replacements = [
        ("(", "（"), (")", "）"),  # ( ) → （ ）
        ("[", "［"), ("]", "］"),  # [ ] → ［ ］
        ('"', "'"), ("{", ""), ("}", ""),
    ]
    for ch, repl in replacements:
        label = label.replace(ch, repl)
    return label.strip() or "-"


def render_mermaid(mindmap: Mindmap) -> str:
    """트리 순회로 Mermaid mindmap 문법 생성 (들여쓰기가 계층)."""
    children: dict[str, list[MindmapNode]] = {}
    root: MindmapNode | None = None
    for n in mindmap.nodes:
        if not n.parent_id:
            root = n
        else:
            children.setdefault(n.parent_id, []).append(n)
    if root is None:
        raise ValueError("루트 노드가 없습니다")

    lines = ["mindmap", f"  root(({_mermaid_label(root.label)}))"]

    def walk(node_id: str, depth: int) -> None:
        for child in children.get(node_id, []):
            lines.append("  " * (depth + 1) + _mermaid_label(child.label))
            walk(child.id, depth + 1)

    walk(root.id, 1)
    return "\n".join(lines)


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>마인드맵</title>
<script type="module">
import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";
mermaid.initialize({{ startOnLoad: true }});
</script>
<style>body {{ margin: 0; font-family: sans-serif; }} .mermaid {{ width: 100vw; height: 100vh; }}</style>
</head>
<body>
<pre class="mermaid">
{mermaid}
</pre>
</body>
</html>"""


def generate_mindmap(job_id: str, count: int = 30) -> Mindmap:
    """노트 기반 마인드맵 생성 → mindmap.json + mindmap.html(Mermaid 시각화)."""
    job_dir = config.JOBS_DIR / job_id
    notes_path = job_dir / "notes.md"
    if not notes_path.exists():
        raise FileNotFoundError(f"notes.md가 없습니다 — 먼저 5단계(notes)를 실행하세요: {job_id}")
    notes = notes_path.read_text(encoding="utf-8")

    from .llm import get_client

    client = get_client()
    prompt = MINDMAP_PROMPT.format(count=count, notes=notes)

    mindmap: Mindmap = client.generate_structured(prompt, Mindmap)
    problems = validate_mindmap(mindmap)
    if problems:
        print(f"구조 검증 실패({len(problems)}건) → 재생성: {problems[:3]}")
        retry_prompt = f"{prompt}\n\n직전 생성본의 문제점 — 모두 고치세요:\n" + "\n".join(problems)
        mindmap = client.generate_structured(retry_prompt, Mindmap)
        problems = validate_mindmap(mindmap)
        if problems:
            raise RuntimeError(f"마인드맵 구조가 재시도 후에도 불량입니다: {problems}")

    (job_dir / "mindmap.json").write_text(mindmap.model_dump_json(indent=2), encoding="utf-8")
    mermaid = render_mermaid(mindmap)
    (job_dir / "mindmap.html").write_text(_HTML_TEMPLATE.format(mermaid=mermaid), encoding="utf-8")
    print(f"마인드맵 노드 {len(mindmap.nodes)}개 저장: mindmap.json, mindmap.html (Gemini 호출 {client.call_count}회)")
    return mindmap


def grade_answer(question: QuizQuestion, user_answer: str) -> bool:
    """채점: 객관식은 보기 원문 또는 번호(1~4), 단답형은 공백·대소문자 무시 비교."""
    user_answer = user_answer.strip()
    if question.type == "multiple_choice":
        if user_answer.isdigit() and 1 <= int(user_answer) <= len(question.options):
            return question.options[int(user_answer) - 1] == question.answer
        return user_answer == question.answer
    norm = lambda s: "".join(s.lower().split())
    return norm(user_answer) == norm(question.answer)


def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="학습 콘텐츠 생성 (구조화 JSON)")
    parser.add_argument("job_id")
    parser.add_argument("kind", choices=["quiz", "flashcard", "mindmap", "glossary"], help="생성 유형")
    parser.add_argument("--count", type=int, default=None)
    parser.add_argument("--difficulty", default="보통", choices=DIFFICULTIES)
    args = parser.parse_args()

    if args.kind == "quiz":
        quiz = generate_quiz(args.job_id, count=args.count or 10, difficulty=args.difficulty)
        for i, q in enumerate(quiz.questions, start=1):
            print(f"\n{i}. [{q.type}] {q.question}")
            for j, opt in enumerate(q.options, start=1):
                mark = "✓" if opt == q.answer else " "
                print(f"   {j}){mark} {opt}")
            if not q.options:
                print(f"   정답: {q.answer}")
            print(f"   해설: {q.explanation[:80]} (근거: 슬라이드 {q.source_slide})")
    elif args.kind == "flashcard":
        deck = generate_flashcards(args.job_id, count=args.count or 15)
        for i, card in enumerate(deck.cards, start=1):
            print(f"\n{i}. 앞: {card.front}")
            print(f"   뒤: {card.back} (근거: 슬라이드 {card.source_slide})")
    elif args.kind == "mindmap":
        mindmap = generate_mindmap(args.job_id, count=args.count or 30)
        print()
        print(render_mermaid(mindmap))
    elif args.kind == "glossary":
        glossary = generate_glossary(args.job_id, count=args.count or 20)
        for t in glossary.terms:
            print(f"- {t.term} ({t.korean}): {t.definition}")


if __name__ == "__main__":
    _main()
