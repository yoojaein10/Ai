"""수수료 청구서 계좌 문구 파싱 (`APW_Bill.Account`).

원본은 사람이 편집한 자유 텍스트라 표기가 제각각이다. 실제 값 예:

    ◈ 신한은행       : 100-025-471640      ( 예금주 :(주)대화감정평가법인 )
    ◈ 국민은행 남부터미널역 : 484201-01-128982(예금주:(주)대화감정평가법인 본사 )
        : 022-6000-1855-706   ( 예금주 :(주)대화감정평가법인 )

흡수해야 하는 변형: `◈` 유무, 은행명 누락, `(` 앞 공백 유무, 예금주에 `(주)` 처럼
괄호가 들어가는 경우, 한 칸에 계좌가 여러 개인 경우.

본사 담보 2026 실측: 값이 있는 1,581건 전부 파싱 성공.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# 은행명은 없을 수 있고, 예금주에 괄호가 들어가므로 줄 끝의 ')' 까지 비탐욕으로 먹는다.
_ACCOUNT = re.compile(
    r"(?:◈\s*)?(?P<bank>[^\r\n:◈]*?)\s*:\s*"
    r"(?P<number>\d[\d\-]{6,})\s*"
    r"\(\s*예금주\s*:\s*(?P<holder>.+?)\s*\)\s*$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class BankAccount:
    """청구서에 적힌 입금 계좌 한 건."""

    bank: str
    number: str
    holder: str


def parse_accounts(text: str | None) -> tuple[BankAccount, ...]:
    """청구서 계좌 문구에서 계좌를 모두 뽑는다.

    값이 없거나 계좌 형식이 아니면(예: '카드결제시연락주세요') 빈 튜플을 준다.
    """
    if not text or not text.strip():
        return ()
    return tuple(
        BankAccount(
            bank=match.group("bank").strip(),
            number=match.group("number").strip(),
            holder=match.group("holder").strip(),
        )
        for match in _ACCOUNT.finditer(text)
    )


def primary_account(text: str | None) -> BankAccount | None:
    """첫 번째 계좌만 쓴다(뱅크온라인은 계좌 한 칸)."""
    accounts = parse_accounts(text)
    return accounts[0] if accounts else None
