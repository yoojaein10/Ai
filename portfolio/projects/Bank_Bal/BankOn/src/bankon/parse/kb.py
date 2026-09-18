"""`.gam` 의 `KB_*` 테이블 파싱 — 국민은행 전용.

신한에 `mullist` 가 있듯, 국민에는 `KB_*` 가 있다. 체크리스트만 있는 줄 알았으나
실제로는 화면에 그대로 들어가는 값이 담겨 있다.

    KB_Summary       CustName(의뢰처)·debtor·category·addr(완성된 소재지)·Write_Date·Writer
    KB_Summary_Chk   a1~a12 / b1~b5 / c1~c3 = **점검항목 20개** (Y=여 / N=부)
    KB_Con           물건 집계(필지수·면적·금액)
    KB_Reason        비교사례 3건(소재지·지목·용도지역·단가·기준시점·목적)
    KB_Examine       중개업소 탐문 3건 + 종합의견
    Kb_EtcChk        별도 체크 13개 + Pung

점검항목 대응은 감정평가서 양식(참고 폴더 스크린샷)과 화면 순서로 확인했다:
    a1~a12 → 2-1. 정규담보 취득제한 부동산 점검사항 (①~⑪, ④가 두 줄이라 12개)
    b1~b5  → 2-2. 일반 점검사항 (조건부감정 + 기타 4)
    c1~c3  → 2-3. 중점 점검사항 (반복매매 · 장기 미분양 · 취약 담보물건)
화면의 점검항목 콤보를 **위→아래 순서**로 채우면 이 순서와 그대로 맞는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

_TABLE = re.compile(r"^kb_(?P<name>[a-z_]+?)\d*$", re.IGNORECASE)
_ROUND = re.compile(r"^round\d+$", re.IGNORECASE)
_HOCOUNT = re.compile(r"(\d+)\s*개호")

# 점검항목 컬럼 순서 — 화면 위→아래 순서와 같다.
CHECK_COLUMNS: tuple[str, ...] = (
    *(f"a{i}" for i in range(1, 13)),
    *(f"b{i}" for i in range(1, 6)),
    *(f"c{i}" for i in range(1, 4)),
)

YES = "예"
NO = "아니오"


@dataclass(frozen=True)
class KbSummary:
    """`KB_Summary` — 국민은행 요약 헤더."""

    client: str | None = None       # CustName  (예: 국민은행 강남파이낸스지점장)
    debtor: str | None = None
    category: str | None = None     # 토지건물 / 구분건물 …
    address: str | None = None      # addr — 계층으로 쪼개지지 않은 **완성된 소재지**
    write_date: str | None = None
    writer: str | None = None


def _find(tables: dict[str, list], name: str) -> list[dict]:
    """`KB_Summary0` 처럼 뒤에 바인더 번호가 붙는 테이블을 이름으로 찾는다."""
    wanted = name.lower()
    for key, rows in tables.items():
        match = _TABLE.match(key)
        if match and match.group("name").lower().strip("_") == wanted and rows:
            return [r for r in rows if isinstance(r, dict)]
    return []


def _text(row: dict, key: str) -> str | None:
    value = row.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass(frozen=True)
class KbConItem:
    """`KB_Con` 물건별 집계값 — 집계형 명세(개별 물건이 명세표에 없을 때)의 출처."""

    area: Decimal | None = None          # Con_Area (사정면적)
    unit_price: Decimal | None = None    # Con_Price (평가단가)
    amount: Decimal | None = None        # Con_TotPrice (감정평가액)
    aggregated: bool = False             # Con_Ho='N개호' N>=2 → 개별물건 아님(합산)


def _num(text: str | None) -> Decimal | None:
    if not text:
        return None
    cleaned = re.sub(r"[^\d.]", "", str(text))
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def parse_con(tables: dict[str, list]) -> tuple[KbConItem, ...]:
    """`KB_Con` 의 물건별 집계값(면적·단가·총액)을 순서대로.

    집계형 구분건물/토지(명세표엔 총액·비준가액만, 개별 물건은 여기)에서 쓴다.
    `Con_Ho='8개호'` 처럼 여러 호를 한 행에 합산한 것은 aggregated=True(개별물건 아님).
    """
    rows = _find(tables, "con")
    if not rows:
        return ()
    row = rows[0]
    items: list[KbConItem] = []
    for n in range(1, 6):
        amount = _num(_text(row, f"Con_TotPrice{n}"))
        if amount is None:
            continue
        count = _HOCOUNT.search(_text(row, f"Con_Ho{n}") or "")
        items.append(KbConItem(
            area=_num(_text(row, f"Con_Area{n}")),
            unit_price=_num(_text(row, f"Con_Price{n}")),
            amount=amount,
            aggregated=bool(count) and int(count.group(1)) >= 2))
    return tuple(items)


def reviewer_from_round(tables: dict[str, list]) -> str | None:
    """`.gam` `round0` 첫 행 `inspection` = 심사자.

    DB(APW_Judgment)에 심사자가 없을 때(스캔 커버리지 이전 문서 등)의 대체원.
    서식행 테이블(`round_20` 등)은 `^round\\d+$` 에 안 걸려 무시된다.
    실측: 0658 round0.inspection=김태우(=DB 일치), 0636 DB None 이나 round0=김형식.
    """
    for key, rows in tables.items():
        if _ROUND.match(key) and rows and isinstance(rows[0], dict):
            name = (rows[0].get("inspection") or "").strip()
            return name or None
    return None


def parse_summary(tables: dict[str, list]) -> KbSummary:
    rows = _find(tables, "summary")
    if not rows:
        return KbSummary()
    row = rows[0]
    return KbSummary(
        client=_text(row, "CustName"),
        debtor=_text(row, "debtor"),
        category=_text(row, "category"),
        address=_text(row, "addr"),
        write_date=_text(row, "Write_Date"),
        writer=_text(row, "Writer"),
    )


def _to_answer(raw: str | None) -> str | None:
    """`Y`/`N` (또는 True/False) → 화면 콤보 값."""
    if raw is None:
        return None
    text = raw.strip().upper()
    if text in ("Y", "TRUE", "1", "여", "예"):
        return YES
    if text in ("N", "FALSE", "0", "부", "아니오", "아니요"):
        return NO
    return None


def parse_checks(tables: dict[str, list]) -> tuple[str | None, ...]:
    """점검항목 20개를 **화면 순서대로** 돌려준다.

    표가 없으면 전부 None — 호출측이 기본값(`아니오`)을 쓴다.
    """
    rows = _find(tables, "summary_chk")
    if not rows:
        return (None,) * len(CHECK_COLUMNS)
    row = rows[0]
    return tuple(_to_answer(_text(row, column)) for column in CHECK_COLUMNS)
