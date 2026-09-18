"""은행 공통 코드 변환.

`.gam` 표기와 뱅크온라인 표기가 같은 방식으로 어긋나는 항목은 여기 모은다.
은행별 고유 코드체계는 `codes/<bank>.py` 에 둔다.
"""
from __future__ import annotations

import re

# 공부상 표기 `대` 를 화면은 `대지` 로 쓴다(신한·국민 공통 확인).
CATEGORY_ALIAS: dict[str, str] = {"대": "대지"}


def land_category(raw: str | None, allowed: frozenset[str] | None = None) -> str | None:
    """지목 → 화면 코드. 목록에 없으면 None(비워둠)."""
    name = (raw or "").strip()
    if not name:
        return None
    mapped = CATEGORY_ALIAS.get(name, name)
    if allowed is not None and mapped not in allowed:
        return None
    return mapped

_STRUCT_ROOF = re.compile(r"\s*/\s*")
_STRUCT_PAREN = re.compile(r"\s*[（(].*$")             # '(평스라브)','((철근)콘크리트)' 꼬리
# 구분자 없이 이어 붙은 지붕 표기 — `철근콘크리트구조 철근콘크리트지붕`(실측 2656 개요).
# 앞에 구조가 남아 있을 때만 떼어 낸다(통째로 지붕인 값을 빈 값으로 만들지 않도록).
_STRUCT_ROOF_WORD = re.compile(r"(?<=\S)\s+\S*지붕\s*$")
_STRUCT_KEEP = frozenset({"연와조", "석조", "와가", "초가"})  # '구조' 변형이 없는 표기


def _join_split_suffix(head: str) -> str:
    """구조 표기 안의 끊김을 잇는다 — `철골철근콘크리트구 조` → `철골철근콘크리트구조`.

    공부스캔 비고(2829 `전유부분 철골철근콘크리트구 조`)·명세표 줄바꿈이 낱말 가운데 공백을 남긴다.
    그대로 두면 `…구 조` 가 `…조` 로 끝나 `…구 구조` 로 정규화돼 화면과 어긋난다(2026-09-11 실측).
    공백을 없앤 결과가 `조` 로 끝날 때만 잇는다 — 지붕·층수·용도가 이어진 긴 비고는 건드리지 않는다.
    """
    compact = re.sub(r"\s+", "", head)
    return compact if compact.endswith("조") else head


def struct_only(text: str | None, *, to_gujo: bool = True) -> str | None:
    """`철근콘크리트조 / 슬라브지붕` → `철근콘크리트구조`(지붕·괄호부기 제거).

    화면 `건물구조` 칸에는 구조만 들어간다. 명세표는 사람이 직접 타이핑해 접미사가
    `…조`/`…구조` 로 들쭉날쭉이라 화면 표기로 맞춘다.

    `to_gujo` 는 **은행마다 화면 표기가 달라서** 있다 —
      국민(True)  : 화면이 `…구조` 로 통일 (실측 0636 철근콘크리트조→철근콘크리트구조)
      기업(False) : 화면이 **원문 그대로** (실측 2682 화면=`철근콘크리트조`)
    '연와조·석조'처럼 `구조` 변형이 없는 표기는 True 여도 예외로 둔다.
    """
    if not text:
        return None
    head = _STRUCT_ROOF.split(text)[0]          # `구조 / 지붕` 형태
    head = _STRUCT_PAREN.sub("", head).strip()  # 괄호 부기 제거
    head = _STRUCT_ROOF_WORD.sub("", head).strip()   # `구조 지붕` 형태(구분자 없음)
    head = _join_split_suffix(head)
    if not head:
        return None
    if not to_gujo or head.endswith("구조") or head in _STRUCT_KEEP:  # 멱등 + 예외
        return head
    return re.sub(r"조$", "구조", head) if head.endswith("조") else head


def best_struct(*candidates: str | None, to_gujo: bool = True) -> str | None:
    """구조 후보 중 완전한 값(…조/…구조로 끝)을 우선, 없으면 첫 유효값.

    명세표 gujo 는 word-wrap 으로 조각날 수 있어(`철근` 만 잡히는 식), 조각이면 의견서
    개요의 완전한 값으로 폴백한다. 둘 다 조각이면 최선값(잡음).
    """
    cleaned = [struct_only(c, to_gujo=to_gujo) for c in candidates]
    for value in cleaned:
        if value and (value.endswith("조") or value in _STRUCT_KEEP):
            return value
    return next((value for value in cleaned if value), None)


def zone_name(text: str | None) -> str | None:
    """용도지역 표기 정리 — 화면 한 칸에 들어가는 **첫 용도지역** 하나.

    명세표는 `제2종일반주거지역, 자연녹지지역` 처럼 둘을 적어 두기도 하는데 화면은
    첫 것만 받는다(실측 2546 화면=`제２종일반주거지역`). 의견서 개요는 줄바꿈 자리에
    공백이 남아 `제2종일반 주거지역` 으로 오기도 해서 내부 공백도 없앤다(실측 2561).
    """
    if not text:
        return None
    head = text.split(",")[0].split("·")[0]
    return re.sub(r"\s+", "", head).strip() or None

