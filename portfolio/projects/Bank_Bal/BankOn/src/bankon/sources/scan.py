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

from ..parse import address

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


_JIBUN = re.compile(r"(?<![\d-])(\d+(?:-\d+)?)(?=\s|$|외)")

# 호번호 해석은 `parse.address` 한 곳에만 둔다 — 예전엔 여기에 사본이 있어
# `제4층제402호` 를 `4층제402` 로 읽고 등기행을 못 찾았다.
_ho = address.ho_of


def _jibun(text: str | None) -> str | None:
    found = _JIBUN.search(text or "")
    return found.group(1) if found else None


def identify(
    rows: tuple[GongbuRow, ...],
    *,
    area: Decimal | None = None,
    location: str | None = None,
    jibun: str | None = None,
) -> tuple[GongbuRow, ...]:
    """물건 고유값으로 공부 행을 좁힌다 — **면적 → 호 → 지번** 순으로 강한 키다.

    한 문서에 등기 고유번호가 여러 개 있을 때(집합건물 여러 호, 여러 필지) 순번(`No`)
    만으로는 못 고른다 — 실측 2625 는 408호·409호가 각각 `No=3` 이고, 2399 는 세 필지가
    전부 `No=1` 이다. **면적이 사실상 유일키**다(실측 4/4 정확).

        2625 물건① 90.48㎡ → 제4층 제408호 행 → 1357-2016-011047 (화면과 일치)
        2399 물건① 2,612㎡ → 815-1 행       → 1951-1996-264449
        2461 물건① 396㎡   → 815 행         → 1245-1996-136350
    """
    if area is not None:
        matched = tuple(r for r in rows if r.area is not None and r.area == area)
        if matched:
            return matched
    ho = _ho(location)
    if ho:
        matched = tuple(r for r in rows if _ho(r.address) == ho)
        if matched:
            return matched
    number = _jibun(jibun)
    if number:
        matched = tuple(r for r in rows if _jibun(r.address) == number)
        if matched:
            return matched
    return ()


def _foreign_parcels(rows: tuple[GongbuRow, ...], jibun: str | None) -> bool:
    """스캔 행이 전부 **다른 지번**의 공부인가 — 그러면 어느 행의 등기번호도 이 물건 것이 아니다.

    실측 2739(한남동 657-97): T_SCAN_GONGBU 에 인천 용현동 573-7 공부가 잘못 붙어 있었고, 면적·호·지번
    어느 것도 안 맞자 예전 폴백(첫 행)이 그 등기번호를 화면에 넣었다(2026-09-11). 지번을 아는 행이 하나라도
    있고 그 중 이 물건 지번과 같은 게 없으면 fail-closed — 사람이 채운다.
    """
    number = _jibun(jibun)
    if not number:
        return False
    known = [_jibun(r.address) for r in rows if _jibun(r.address)]
    return bool(known) and number not in known


def registry_for(
    rows: tuple[GongbuRow, ...],
    *,
    kind: str | None = None,
    seq_no: str | None = None,
    area: Decimal | None = None,
    location: str | None = None,
    jibun: str | None = None,
) -> str | None:
    """조건에 맞는 등기번호 하나.

    같은 문서에 여러 물건이 있으면 순번(`No`)으로 고르고, 순번이 없으면 종류로
    고른다. 종류도 지정하지 않으면 **건물 우선**(담보는 대개 건물이 대상이다).
    """
    # 물건 고유값(면적·호·지번)을 주면 그걸로 먼저 좁힌다 — 순번(`No`)은 문서에 따라
    # 중복되거나 물건과 어긋나 믿을 수 없다(실측 2625·2399, 농협 이식 2026-09-07).
    identified = identify(rows, area=area, location=location, jibun=jibun)
    if not identified and _foreign_parcels(rows, jibun):
        return None
    candidates = list(identified or rows)
    if not identified and seq_no is not None:
        matched = [r for r in candidates if r.seq_no == seq_no]
        if matched:
            candidates = matched
    if kind is not None:
        typed = [r for r in candidates if (r.kind or "").strip() == kind]
        # 고유값으로 이미 좁힌 뒤라면 종류가 안 맞아도 버리지 않는다(스캔 종류 표기가 우리 분류와 다를 수 있다).
        candidates = typed if (typed or not identified) else candidates
    elif candidates:
        buildings = [r for r in candidates if r.is_building]
        candidates = buildings or candidates

    for row in candidates:
        if row.registry_no:
            return row.registry_no
    return None
