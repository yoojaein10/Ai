# -*- coding: utf-8 -*-
"""탁상 중복 후보 조회 (지시 §8 중복).

원칙:
- SELECT 만 사용한다.
- 탁상 업무의 실제 식별 필드를 확인하기 전에는 중복 키를 추정하지 않는다.
- 주소나 PDF 해시만으로 중복을 확정하지 않는다.
- 없음/후보/판정불가를 구분한다. 후보를 자동 처리하지 않는다.

현재 탁상 마스터의 확정된 중복 식별 필드가 아직 검증되지 않았다. 따라서 기본 동작은
'판정 불가(UNDECIDABLE)'이며 어떤 쿼리도 실행하지 않는다. 실제 식별 필드가 사람 검토로
확정되면 그때 고정 쿼리를 ro_query 레지스트리에 추가하고 confirmed_key 로 활성화한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

NO_DUPLICATE = "no_duplicate"
CANDIDATE = "duplicate_candidate"
UNDECIDABLE = "undecidable"


@dataclass
class DuplicateResult:
    status: str
    candidate_count: int = 0
    reasons: list = field(default_factory=list)

    def __repr__(self) -> str:
        return f"DuplicateResult(status={self.status!r}, candidates={self.candidate_count})"


def classify_rows(rows) -> str:
    """확정 키로 조회한 결과 행을 없음/후보로 분류(후보 자동처리 없음)."""
    n = len(rows or [])
    if n == 0:
        return NO_DUPLICATE
    return CANDIDATE


def check_duplicate(cur=None, *, confirmed_key: dict | None = None) -> DuplicateResult:
    """중복 후보 조회.

    confirmed_key 가 없으면(현재 상태) 어떤 쿼리도 실행하지 않고 UNDECIDABLE 을 반환한다.
    추정 키(주소/PDF 해시)로 중복을 확정하지 않는다.
    """
    if not confirmed_key:
        return DuplicateResult(
            UNDECIDABLE, reasons=["탁상 중복 식별 필드 미확정 — 추정 금지"])
    # confirmed_key 가 주어져도, 등록된 고정 쿼리가 아직 없으면 실행하지 않는다.
    return DuplicateResult(
        UNDECIDABLE, reasons=["확정 키에 대응하는 등록 쿼리 미구현 — 실행 안 함"])
