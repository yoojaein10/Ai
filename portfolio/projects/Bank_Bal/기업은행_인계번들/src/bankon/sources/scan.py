"""공부 스캔 DB(`appraisal.dbo.T_SCAN_GONGBU`) 조회 — 등기 고유번호.

`mullist` 가 없는 건(국민은행 전부, 신한의 32%)은 등기번호를 여기서만 얻을 수 있다.
**본사(01지사) 전용** 시스템이라 지사 건은 비어 있다(실측: 01지사 72%, 나머지 0%).

컬럼: Seq, No(물건순번), Gubun(토지/건물), Docid, UniqueNo, Address, Area, Bigo
  UniqueNo  `1357-1996-070593` — 하이픈을 빼면 전 행이 정확히 14자리(실측 11,712행)
  Bigo      토지=지목(`대`,`전`) / 건물=구조·용도 서술 → 건물구조 보완에 쓸 수 있다
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

LAND = "토지"
BUILDING = "건물"


@dataclass(frozen=True)
class GongbuRow:
    """공부 스캔 한 행(물건 하나)."""

    seq_no: str | None       # No     — 물건순번
    kind: str | None         # Gubun  — 토지 / 건물
    unique_no: str | None    # UniqueNo — 등기 고유번호(하이픈 포함 원본)
    address: str | None
    area: Decimal | None
    note: str | None         # Bigo

    @property
    def registry_no(self) -> str | None:
        """화면에 넣는 형태 — 하이픈 없는 숫자 14자리."""
        if not self.unique_no:
            return None
        return re.sub(r"\D", "", self.unique_no) or None

    @property
    def is_land(self) -> bool:
        return (self.kind or "").strip() == LAND

    @property
    def is_building(self) -> bool:
        return (self.kind or "").strip() == BUILDING


def _text(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def fetch_rows(cursor, doc_id: str) -> tuple[GongbuRow, ...]:
    """문서의 공부 행을 순번대로 가져온다. 없으면 빈 튜플."""
    cursor.execute(
        """SELECT No, Gubun, UniqueNo, Address, Area, Bigo
           FROM dbo.T_SCAN_GONGBU WHERE Docid = ? ORDER BY Seq""",
        doc_id,
    )
    rows = []
    for no, gubun, unique_no, address, area, bigo in cursor.fetchall():
        rows.append(GongbuRow(
            seq_no=_text(no),
            kind=_text(gubun),
            unique_no=_text(unique_no),
            address=_text(address),
            area=Decimal(str(area)) if area is not None else None,
            note=_text(bigo),
        ))
    return tuple(rows)


def registry_for(
    rows: tuple[GongbuRow, ...],
    *,
    kind: str | None = None,
    seq_no: str | None = None,
) -> str | None:
    """조건에 맞는 등기번호 하나.

    같은 문서에 여러 물건이 있으면 순번(`No`)으로 고르고, 순번이 없으면 종류로
    고른다. 종류도 지정하지 않으면 **건물 우선**(담보는 대개 건물이 대상이다).
    """
    candidates = list(rows)
    if seq_no is not None:
        matched = [r for r in candidates if r.seq_no == seq_no]
        if matched:
            candidates = matched
    if kind is not None:
        candidates = [r for r in candidates if (r.kind or "").strip() == kind]
    elif candidates:
        buildings = [r for r in candidates if r.is_building]
        candidates = buildings or candidates

    for row in candidates:
        if row.registry_no:
            return row.registry_no
    return None
