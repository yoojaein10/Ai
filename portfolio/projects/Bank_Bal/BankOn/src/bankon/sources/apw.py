"""APW 원천 DB 조회 — `.gam` 에 없는 값들.

전부 읽기 전용이다. 각 함수는 커서를 받아 순수 값만 돌려주므로
가짜 커서로 단위 테스트할 수 있다.

출처(실물 검증 완료):
  법정동코드/지번  apw_masterex.REG+EUB, SAN, BUN1, BUN2   보유 97.8%
  심사자          APW_Judgment(itype=2) ⟕ TMWCMN_USR_BAC_INFO.EMP
  복수평가사       apw_masterex.manager (콤마 분리, `공(이름)` 래퍼)
  대표/지사장      apw_office.Boss (OfficeID='10' = 본사)
  수수료 계좌      APW_Bill.Account (청구서 자유 텍스트)
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..parse.account import BankAccount, primary_account

HEAD_OFFICE_ID = "10"

# manager 는 `안창덕,황인석` 처럼 콤마로 나뉘고, 공동평가자는 `공(황인석)` 로 감싸져 있다.
_CO_APPRAISER = re.compile(r"^공\s*\((?P<name>.+)\)$")


@dataclass(frozen=True)
class Jibun:
    """법정동코드와 지번. 뱅크온라인은 은행마다 나눠 받거나 붙여 받는다."""

    reg: str | None       # 시군구 코드 5자리
    eub: str | None       # 읍면동 코드 5자리
    san: str | None       # '1'=일반 / '2'=산
    bun1: str | None      # 본번(4자리 0채움 → 앞의 0 제거)
    bun2: str | None      # 부번(0000 → 없음)

    @property
    def legal_code(self) -> str | None:
        """국민은행처럼 10자리 한 칸으로 받는 경우."""
        if not (self.reg and self.eub):
            return None
        return f"{self.reg}{self.eub}"

    @property
    def jibun_kind(self) -> str | None:
        """번지구분 — 신한/국민 공통으로 '일반'/'산'."""
        return {"1": "일반", "2": "산"}.get((self.san or "").strip())


def _strip_zero(value: str | None) -> str | None:
    """`0201` → `201`, `0000` → None."""
    text = (value or "").strip()
    if not text:
        return None
    trimmed = text.lstrip("0")
    return trimmed or None


def fetch_jibun(cursor, doc_id: str) -> Jibun | None:
    """법정동코드·번지구분·본번·부번."""
    cursor.execute(
        "SELECT REG, EUB, SAN, BUN1, BUN2 FROM apw_masterex WHERE DocID = ?", doc_id
    )
    row = cursor.fetchone()
    if row is None:
        return None
    reg, eub, san, bun1, bun2 = ((str(v).strip() if v is not None else None) for v in row)
    return Jibun(
        reg=reg or None,
        eub=eub or None,
        san=san or None,
        bun1=_strip_zero(bun1),
        bun2=_strip_zero(bun2),
    )


def fetch_reviewer(cursor, master_id: int) -> str | None:
    """심사자 이름. itype=2 가 심사자다(itype 1/5/6 은 다른 역할)."""
    cursor.execute(
        """SELECT B.EMP FROM APW_Judgment A
           LEFT JOIN TMWCMN_USR_BAC_INFO B ON A.JudgCharge = B.USR_SEQ
           WHERE A.MasterID = ? AND A.itype = 2""",
        master_id,
    )
    row = cursor.fetchone()
    if row is None or not row[0]:
        return None
    return str(row[0]).strip() or None


def split_appraisers(manager: str | None) -> tuple[str, ...]:
    """`apw_masterex.manager` → 평가사 이름들.

    `안창덕,황인석` → ('안창덕', '황인석')
    `공(노승환)`     → ('노승환',)      — '공' 은 공동평가 표시라 이름이 아니다
    """
    names: list[str] = []
    for chunk in (manager or "").split(","):
        name = chunk.strip()
        if not name:
            continue
        match = _CO_APPRAISER.match(name)
        if match:
            name = match.group("name").strip()
        if name:
            names.append(name)
    return tuple(names)


def fetch_appraisers(cursor, doc_id: str) -> tuple[str, ...]:
    cursor.execute("SELECT manager FROM apw_masterex WHERE DocID = ?", doc_id)
    row = cursor.fetchone()
    return split_appraisers(row[0] if row else None)


def fetch_office_boss(cursor, office_id: str = HEAD_OFFICE_ID) -> str | None:
    """지사 대표자. 원본에 `정   우   종` 처럼 공백이 끼어 있어 제거한다."""
    cursor.execute("SELECT Boss FROM apw_office WHERE OfficeID = ?", office_id)
    row = cursor.fetchone()
    if row is None or not row[0]:
        return None
    return re.sub(r"\s+", "", str(row[0])) or None


def fetch_account(cursor, master_id: int) -> BankAccount | None:
    """수수료 청구서의 입금 계좌. 값이 없거나 계좌 형식이 아니면 None."""
    cursor.execute("SELECT Account FROM APW_Bill WHERE MasterID = ?", master_id)
    row = cursor.fetchone()
    return primary_account(row[0] if row else None)


def fetch_master_id(cursor, doc_id: str) -> int | None:
    cursor.execute("SELECT MasterID FROM apw_Master WHERE DocID = ?", doc_id)
    row = cursor.fetchone()
    return int(row[0]) if row and row[0] is not None else None


def fetch_legal_code(cursor, address: str | None) -> str | None:
    """**소재지(시도 시군구 동)로** 법정동코드 10자리. 못 정하면 None(화면은 사람이 채운다).

    코드→명칭 표가 DB 에 없어서, 지난 의뢰의 `apw_masterex` **ADDR ↔ REG/EUB** 를 표처럼 쓴다
    (동 단위 주소 25,907가지). 다현장 문서에서 **문서 대표가 아닌 현장**의 코드를 얻는 유일한 길이다
    (2818 삼성동 → 11680+10500 = 1168010500, 실화면과 일치).

    같은 주소에 코드가 여러 개 붙어 있기도 하다(옛 의뢰의 입력 오류 — 옹정리 132건 vs 2건 vs 1건 vs 1건).
    그래서 **최빈값이 나머지를 2배 이상 압도할 때만** 쓰고, 팽팽하면 None 으로 물러선다(틀린 코드보단 빈칸).
    """
    text = re.sub(r"\s+", " ", (address or "").strip())
    if not text:
        return None
    cursor.execute(
        """SELECT TOP 2 REG, EUB, COUNT(*) AS n FROM apw_masterex
           WHERE ADDR = ? AND REG IS NOT NULL AND EUB IS NOT NULL
           GROUP BY REG, EUB ORDER BY n DESC""",
        text,
    )
    rows = cursor.fetchall()
    if not rows:
        return None
    reg, eub, top = str(rows[0][0]).strip(), str(rows[0][1]).strip(), int(rows[0][2])
    if len(reg) != 5 or len(eub) != 5 or not (reg + eub).isdigit():
        return None
    if len(rows) > 1 and top < int(rows[1][2]) * 2:
        return None
    return reg + eub

@dataclass(frozen=True)
class Site:
    """의뢰 물건의 주소 — `apw_masterex` 의 두 주소 컬럼.

    `address` 는 **화면 `소재지` 칸에 그대로 들어가는 값**이고, `full` 은 지번·건물명·
    층/호까지 이어 붙인 자유 문자열이라 건물명을 떼어내는 데 쓴다.
    """

    address: str | None = None      # ADDR    예: 서울특별시 강남구 수서동
    full: str | None = None         # Address 예: 서울특별시 성동구 성수동1가 656-1110외서울숲엘타워 7층 703호외704호


def fetch_site(cursor, doc_id: str) -> Site:
    """소재지(ADDR)와 물건 표시(Address). 공백이 여러 칸 들어 있어 하나로 줄인다."""
    cursor.execute("SELECT ADDR, Address FROM apw_masterex WHERE DocID = ?", doc_id)
    row = cursor.fetchone()
    if row is None:
        return Site()

    def clean(value) -> str | None:
        if value is None:
            return None
        return re.sub(r"\s+", " ", str(value)).strip() or None

    return Site(address=clean(row[0]), full=clean(row[1]))


def fetch_sender(cursor, doc_id: str) -> str | None:
    """발송(입력) 담당자 이름 — `apw_masterex.Sendman` 이 직원 일련번호다.

    농협 화면 `입력자성명` 이 이 값이다(실측 14/14). 같은 표의 전화번호 컬럼은 없어
    `입력자연락처` 는 못 채운다(BANK24 쪽 사용자 정보로 보인다).
    """
    cursor.execute(
        """SELECT B.EMP FROM apw_masterex A
           LEFT JOIN TMWCMN_USR_BAC_INFO B ON A.Sendman = B.USR_SEQ
           WHERE A.DocID = ?""",
        doc_id,
    )
    row = cursor.fetchone()
    if row is None or not row[0]:
        return None
    return str(row[0]).strip() or None

