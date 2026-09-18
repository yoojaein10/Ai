"""신한은행 담보 폼의 코드 변환표.

콤보 선택지는 `tools/list_combo_items.py` 로 실제 화면에서 수집했다
(담보종류 83 · 담보용도 42 · 건물구조(신) 39 · 지목 28 · 용도지역구분(신) 41 …).
여기서는 `.gam` 값 → 그 코드로 바꾸는 규칙만 둔다.

화면 양식이 바뀌면 **이 파일 한 곳만** 고치면 된다.
"""
from __future__ import annotations

import re

# 지목 별칭은 은행 공통이라 codes/common.py 에 두고 여기서는 재수출만 한다.
from .common import CATEGORY_ALIAS, land_category  # noqa: F401

# ── 담보종류: mullist.DABO_JONG_SUB 는 92% 가 코드와 그대로 일치한다.
# 나머지 5종만 별칭으로 잇는다(2026-08-19 가정 — 확정 시 이 표만 수정).
COLLATERAL_KIND_ALIAS: dict[str, str] = {
    "일반창고시설": "창고시설(일반)",
    "동산담보": "기계기구",
    "공장저당": "공장",
    "의료시설": "기타부동산",
    "위험물 저장 및 처리시설": "기타부동산",
}

# ── 담보용도(42)는 담보종류(83)의 상위 분류다. 같은 이름이면 그대로 쓰고,
# 아래 표에 있으면 상위 분류로 올린다. 표에 없고 이름도 다르면 비워둔다
# (기계기구·차량·선박 계열은 담보용도 목록 자체에 없다).
KIND_TO_USE: dict[str, str] = {
    "연립/빌라": "연립주택",
    "다가구주택": "단독주택",
    "일반상가": "상가(중/소형)",
    "집합상가": "상가(중/소형)",
    "일반업무시설": "업무시설",
    "집합업무시설": "업무시설",
    "주거용오피스텔": "오피스텔",
    "호텔": "숙박시설",
    "일반숙박시설": "숙박시설",
    "병원(대형)": "기타부동산(단독시설)",
    "주유소": "기타부동산(단독시설)",
    "극장": "기타부동산(단독시설)",
    "사우나": "기타부동산(단독시설)",
    "종교시설": "기타부동산(단독시설)",
    "골프장": "기타부동산(단독시설)",
    "레져/스포츠시설": "기타부동산(단독시설)",
    "노인복지주택": "기타부동산(단독시설)",
    "창고시설(일반)": "기타부동산(단독시설)",
    "창고시설(집합)": "기타부동산(단독시설)",
    "자동차관련시설": "기타부동산(단독시설)",
    "자원순환관련시설": "기타부동산(단독시설)",
    "기타부동산": "기타부동산(단독시설)",
    "기타토지": "잡종지",
}

# 담보용도 목록에 그대로 있는 값(담보종류와 이름이 같은 것들).
USE_PASSTHROUGH: frozenset[str] = frozenset({
    "아파트", "단독주택", "연립주택", "다세대주택", "기타공동주택", "상가주택",
    "대형상업시설", "오피스텔", "대지", "공장용지", "전", "답", "과수원",
    "목장용지", "염전", "임야", "잡종지", "광천지", "학교용지", "주차장",
    "주유소용지", "창고용지", "도로", "철도용지", "제방", "하천", "구거",
    "유지", "양어장", "수도용지", "공원", "체육용지", "유원지", "종교용지",
    "사적지", "묘지", "공장", "아파트형공장",
})

# ── 건물구조: `.gam` 표기가 '…조' 로 끝나고 신한은 '…구조' 인 경우가 많다.
# 접미사 정규화로 대부분 흡수하고, 정규화로 안 되는 것만 별칭에 둔다.
STRUCT_ALIAS: dict[str, str] = {
    "철근콩크리트조": "철근콘크리트구조",   # 오타 '콩'
    "철근콩크리트구조": "철근콘크리트구조",
    "세멘벽돌조": "시멘트벽돌구조",
    "세멘블록조": "시멘트블럭조",
    "시멘트블록조": "시멘트블럭조",
    "블록조": "블럭구조",
    "블럭조": "블럭구조",
    "판넬조": "조립식판넬조",
    "조적조": "조적구조",
    "파이프조": "강파이프구조",
    "철파이프구조": "철파이프조",
    "목조": "목구조",
}

_STRUCT_SUFFIX = re.compile(r"조$")


def _clean(value: str | None) -> str:
    return re.sub(r"\s+", "", value or "")


def collateral_kind(raw: str | None, allowed: frozenset[str] | None = None) -> str | None:
    """DABO_JONG_SUB → 담보종류 코드. 모르는 값이면 None(비워둠)."""
    name = (raw or "").strip()
    if not name:
        return None
    mapped = COLLATERAL_KIND_ALIAS.get(name, name)
    if allowed is not None and mapped not in allowed:
        return None
    return mapped


def collateral_use(kind: str | None, allowed: frozenset[str] | None = None) -> str | None:
    """담보종류 → 담보용도(상위 분류). 대응이 없으면 None(비워둠)."""
    name = (kind or "").strip()
    if not name:
        return None
    mapped = KIND_TO_USE.get(name) or (name if name in USE_PASSTHROUGH else None)
    if mapped is None:
        return None
    if allowed is not None and mapped not in allowed:
        return None
    return mapped


def building_struct(raw: str | None, allowed: frozenset[str] | None = None) -> str | None:
    """건물 물건의 JI_YOUNGDO → 건물구조(신) 코드.

    1) 별칭표 → 2) 그대로 → 3) '…조' 를 '…구조' 로 바꿔서 재시도.
    allowed(실제 콤보 목록)를 주면 목록에 없는 값은 None 이 되어 비워진다.
    """
    name = (raw or "").strip()
    if not name:
        return None

    for candidate in (
        STRUCT_ALIAS.get(_clean(name)),
        STRUCT_ALIAS.get(name),
        name,
        _STRUCT_SUFFIX.sub("구조", name),
    ):
        if not candidate:
            continue
        if allowed is None or candidate in allowed:
            return candidate
    return None
