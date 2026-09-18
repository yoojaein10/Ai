# -*- coding: utf-8 -*-
"""읽기 전용 검증 파이프라인 결정 (지시 §14).

순서: PDF 파싱 → Customer 조회 → RegHist 조회 → fingerprint 검증 → SP 파라미터 생성.
조회 실패/복수 후보/초과 결과/fingerprint 불일치/미pin 이면 '처리 불가'로 표시한다.

- SP 파라미터 생성은 허용하되(기존 pipeline.prepare 가 담당) 실행·저장 경로는 연결하지 않는다.
- 이 모듈은 실 DB 에 직접 연결하지 않는다(주입된 커서/결과만 다룬다).
- 쓰기 모듈(ts_db_writer.execute_sp/commit)에 접근하지 않는다.
"""
from __future__ import annotations

import ro_lookups

# 처리 불가 사유 코드
UNPROCESSABLE = "unprocessable"
PROCESSABLE_DRYRUN = "processable_dryrun"   # 실행/저장은 여전히 연결하지 않음


def decide(*, customer: ro_lookups.LookupResult,
           reghist: ro_lookups.LookupResult,
           metadata_verified: bool) -> dict:
    """조회/메타데이터 결과를 종합해 처리 가능 여부를 결정.

    반환에는 마스킹 DTO 개수/상태만 담고 원문은 담지 않는다.
    """
    reasons: list[str] = []

    if customer.status != ro_lookups.SINGLE:
        reasons.append(f"Customer 조회 상태={customer.status}")

    # RegHist: 복수/초과/차단/실패/무효는 처리 불가. no_result 는 Reg/Eub 없이 진행 가능.
    if reghist.status in (ro_lookups.MULTIPLE, ro_lookups.TOO_MANY,
                          ro_lookups.QUERY_BLOCKED, ro_lookups.QUERY_FAILED,
                          ro_lookups.INVALID_ADDRESS):
        reasons.append(f"RegHist 조회 상태={reghist.status}")

    if not metadata_verified:
        reasons.append("SP 메타데이터 미검증(provisional/미pin/불일치)")

    processable = not reasons
    return {
        "status": PROCESSABLE_DRYRUN if processable else UNPROCESSABLE,
        "processable": processable,
        "reasons": reasons,
        "customer_status": customer.status,
        "reghist_status": reghist.status,
        "customer_candidates": customer.count,
        "reghist_candidates": reghist.count,
        # 실행/저장 경로는 어떤 경우에도 연결하지 않음
        "execute_connected": False,
        "commit_connected": False,
    }
