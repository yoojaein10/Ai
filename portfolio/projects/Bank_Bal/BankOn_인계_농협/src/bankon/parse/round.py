"""`.gam` `round*` 테이블 — 감정평가표 머리말.

한 문서에 감정평가표가 여러 장일 수 있다(`round0`, `round1` …). 물건이 서로 다른 건물이면
표를 나눠 쓰고, 표마다 총액(`round_price`)이 따로 있다. 그래서 **표 수가 1장이 아니면**
문서 총액과 화면 총액이 다를 수 있다(실측 2645: 문서 676,000,000 / 표 하나 338,000,000).

서식행 테이블(`round_20` 등)은 `^round\\d+$` 에 안 걸려 무시된다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

_ROUND = re.compile(r"^round(?P<index>\d+)$", re.IGNORECASE)


@dataclass(frozen=True)
class RoundInfo:
    """감정평가표 한 장."""

    index: int = 0
    appraiser: str | None = None     # par_player
    reviewer: str | None = None      # inspection — 심사자(DB 에 없을 때의 대체원)
    client: str | None = None        # custpart  — 의뢰처(예: 농협은행 보문동지점장)
    owner: str | None = None         # ownername — 화면 `소유자명`
    debtor: str | None = None        # debtor
    category: str | None = None      # 토지 / 구분건물 / 토지건물 …
    amount: Decimal | None = None    # round_price — 이 표의 총액
    title: str | None = None         # atitle    — (토지)감정평가표 …
    memo: str | None = None          # round_memo


def _text(row: dict, key: str) -> str | None:
    value = row.get(key)
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def _amount(row: dict, key: str) -> Decimal | None:
    text = _text(row, key)
    if not text:
        return None
    try:
        return Decimal(re.sub(r"[^\d.\-]", "", text))
    except (InvalidOperation, ValueError):
        return None


def parse(tables: dict[str, list]) -> tuple[RoundInfo, ...]:
    """감정평가표들을 표 번호 순서로."""
    found: list[RoundInfo] = []
    for name, rows in tables.items():
        match = _ROUND.match(name)
        if not match or not rows or not isinstance(rows[0], dict):
            continue
        row = rows[0]
        found.append(RoundInfo(
            index=int(match.group("index")),
            appraiser=_text(row, "par_player"),
            reviewer=_text(row, "inspection"),
            client=_text(row, "custpart"),
            owner=_text(row, "ownername"),
            debtor=_text(row, "debtor"),
            category=_text(row, "category"),
            amount=_amount(row, "round_price"),
            title=_text(row, "atitle"),
            memo=_text(row, "round_memo"),
        ))
    return tuple(sorted(found, key=lambda r: r.index))


def first(rounds: tuple[RoundInfo, ...]) -> RoundInfo:
    """첫 감정평가표(없으면 빈 것)."""
    return rounds[0] if rounds else RoundInfo()
