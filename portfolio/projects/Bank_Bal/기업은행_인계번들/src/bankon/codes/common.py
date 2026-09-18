"""은행 공통 코드 변환.

`.gam` 표기와 뱅크온라인 표기가 같은 방식으로 어긋나는 항목은 여기 모은다.
은행별 고유 코드체계는 `codes/<bank>.py` 에 둔다.
"""
from __future__ import annotations

import re

# 공부상 표기 `대` 를 화면은 `대지` 로 쓴다(신한·국민 공통 확인).
CATEGORY_ALIAS: dict[str, str] = {"대": "대지"}

_STRUCT_ROOF = re.compile(r"\s*/\s*")
_STRUCT_PAREN = re.compile(r"\s*[（(].*$")             # '(평스라브)','((철근)콘크리트)' 꼬리
# 구분자 없이 이어 붙은 지붕 표기 — `철근콘크리트구조 철근콘크리트지붕`(실측 2656 개요).
# 앞에 구조가 남아 있을 때만 떼어 낸다(통째로 지붕인 값을 빈 값으로 만들지 않도록).
_STRUCT_ROOF_WORD = re.compile(r"(?<=\S)\s+\S*지붕\s*$")
_STRUCT_KEEP = frozenset({"연와조", "석조", "와가", "초가"})  # '구조' 변형이 없는 표기


def struct_only(text: str | None) -> str | None:
    """`철근콘크리트조 / 슬라브지붕` → `철근콘크리트구조`.

    화면 `건물구조` 칸에는 구조만 들어간다(지붕·괄호부기 제거). 명세표는 사람이
    직접 타이핑해 접미사가 `…조`/`…구조` 로 들쭉날쭉이라 화면 표기(`…구조`)로
    정규화한다(실측: 0636 철근콘크리트조→철근콘크리트구조, 0658 이미 구조=멱등,
    0668 일반철골구조). '연와조·석조'처럼 `구조` 변형이 없는 표기는 예외로 둔다.
    """
    if not text:
        return None
    head = _STRUCT_ROOF.split(text)[0]          # `구조 / 지붕` 형태
    head = _STRUCT_PAREN.sub("", head).strip()  # 괄호 부기 제거
    head = _STRUCT_ROOF_WORD.sub("", head).strip()   # `구조 지붕` 형태(구분자 없음)
    if not head:
        return None
    if head.endswith("구조") or head in _STRUCT_KEEP:  # 멱등 + 예외
        return head
    return re.sub(r"조$", "구조", head) if head.endswith("조") else head


def best_struct(*candidates: str | None) -> str | None:
    """구조 후보 중 완전한 값(…조/…구조로 끝)을 우선, 없으면 첫 유효값.

    명세표 gujo 는 word-wrap 으로 조각날 수 있어(철골철근/콘크리트구조 두 줄, 또는
    기업 토지명세 건물유닛의 `철근`), 조각이면 의견서 개요의 완전한 값으로 폴백한다.
    둘 다 조각이면 최선값(잡음).
    """
    cleaned = [struct_only(c) for c in candidates]
    for value in cleaned:
        if value and (value.endswith("구조") or value in _STRUCT_KEEP):
            return value
    return next((value for value in cleaned if value), None)


def land_category(raw: str | None, allowed: frozenset[str] | None = None) -> str | None:
    """지목 → 화면 코드. 목록에 없으면 None(비워둠)."""
    name = (raw or "").strip()
    if not name:
        return None
    mapped = CATEGORY_ALIAS.get(name, name)
    if allowed is not None and mapped not in allowed:
        return None
    return mapped
