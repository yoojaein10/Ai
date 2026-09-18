"""`.gam` 요약표(`outline6_na*`)의 임대 단서 → 신한 `임대` 콤보 힌트.

의견서 `그 밖의 사항` 물건특성 표(parse/characteristics)는 2026년 신한 건 10.6% 에만 있다. 표가 없으면
임대 콤보를 기본값(자가사용)으로 채우는데, 실제로는 임대 중인 건이 섞인다 — 2831(주유소·공장):
비고 `월 임대료 : 3,800,000원` 인데 자가사용으로 나가 담당자가 잡았다(2026-09-11).

같은 표의 비고(bigo1~7)에 임대료·보증금이 적혀 있으면 **임대있음**이다(로컬 추출물 374건 중 134건이
`월임대료: 3,350,000원` 꼴). `rental`·`rental_gongsil` 칸은 거의 비어 있어 근거로 안 쓴다.
"""
from __future__ import annotations

import re

from .characteristics import LEASE_PRESENT

_TABLE = re.compile(r"^outline6_na\d*$", re.IGNORECASE)
_RENT = re.compile(r"임\s*대\s*료|임\s*차\s*료|보\s*증\s*금")
_NOTE_KEYS = tuple(f"bigo{i}" for i in range(1, 8))


def lease_hint(tables: dict[str, list] | None) -> str | None:
    """임대 단서가 있으면 `임대있음`, 없으면 None(호출측이 다른 근거·기본값을 쓴다)."""
    for name, rows in (tables or {}).items():
        if not _TABLE.match(name):
            continue
        for row in rows or ():
            if not isinstance(row, dict):
                continue
            for key in _NOTE_KEYS:
                if _RENT.search(str(row.get(key) or "")):
                    return LEASE_PRESENT
    return None
