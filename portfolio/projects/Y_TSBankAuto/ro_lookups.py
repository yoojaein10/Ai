# -*- coding: utf-8 -*-
"""APW_RegHist / APW_Customer 읽기 전용 조회 (지시 §12, §13).

참조 프로젝트(Y_BankAuto) 선택 기준을 테스트 가능한 함수로 분리했다:
- RegHist: 행정주소 토큰(AS1/AS2)으로 FUSE='1' + 접두 LIKE(ESCAPE) 조회. Reg/Eub 매핑.
- Customer: Office 고정 + CustName 접두/포함 LIKE(ESCAPE) 조회. 참조의 랭킹 규칙 이식.

원칙:
- 고정 컬럼/테이블(ro_query 레지스트리), 사용자값은 전부 `?` 바인딩.
- 결정적 TOP + ORDER BY. 빈 값/짧은 값/wildcard-only 입력 거부. LIKE ESCAPE 일관 적용.
- fetchmany 상한(레지스트리에서 강제). 복수·초과 결과를 임의 선택하지 않는다.
- 원문은 처리 중 메모리에서만 사용하고 외부(GUI/로그/보고)에는 마스킹 DTO 만 제공한다.
- 원문 결과를 JSON/CSV/Excel/로그/fixture/조사 산출물에 저장하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import ro_query
import security

# ───────────────────────────── 상태 ─────────────────────────────
INVALID = "invalid_input"
INVALID_ADDRESS = "invalid_address"
NO_RESULT = "no_result"
SINGLE = "single_result"
MULTIPLE = "multiple_results"
TOO_MANY = "too_many_results"
QUERY_BLOCKED = "query_blocked"
QUERY_FAILED = "query_failed"

_MIN_TOKEN_LEN = 2


def _mask_ident(value: str) -> str:
    """식별자(CustID 등) 마스킹: 첫 1 + * + 끝 1."""
    s = (value or "").strip()
    if not s:
        return ""
    if len(s) <= 2:
        return s[0] + "*"
    return s[0] + "*" * (len(s) - 2) + s[-1]


def _is_wildcard_only(s: str) -> bool:
    stripped = (s or "").strip()
    return bool(stripped) and all(c in "%_*[] " for c in stripped)


# ───────────────────────────── 마스킹 DTO (GUI/보고 전용) ─────────────────────────────
@dataclass
class MaskedRegHistDTO:
    reg_masked: str
    eub_masked: str
    name_masked: str

    def __repr__(self) -> str:  # 원문 노출 방지
        return "MaskedRegHistDTO(reg=***, eub=***, name=***)"


@dataclass
class MaskedCustomerDTO:
    cust_id_masked: str
    cust_name_masked: str
    active: str

    def __repr__(self) -> str:
        return "MaskedCustomerDTO(cust_id=***, cust_name=***, active=?)"


@dataclass
class LookupResult:
    """조회 결과. 원문은 _raw(메모리 전용, repr 미노출)에만 둔다."""
    status: str
    count: int
    dtos: list = field(default_factory=list)      # 마스킹 DTO 만
    reasons: list = field(default_factory=list)
    _raw_selected: dict | None = field(default=None, repr=False)  # single 일 때만

    def __repr__(self) -> str:
        return f"LookupResult(status={self.status!r}, count={self.count})"


def _classify(rows: list, cap: int) -> str:
    n = len(rows)
    if n == 0:
        return NO_RESULT
    if n == 1:
        return SINGLE
    if n >= cap:
        return TOO_MANY      # 상한까지 찼으면 더 있을 수 있음 → 초과로 취급
    return MULTIPLE


# ───────────────────────────── RegHist ─────────────────────────────
def reghist_tokens(admin_addr: str) -> list[str]:
    """행정주소를 공백 토큰으로 분리(선행 2개만 조회에 사용)."""
    return [t for t in (admin_addr or "").split() if t]


def validate_reghist_input(admin_addr: str) -> tuple[bool, str]:
    tokens = reghist_tokens(admin_addr)
    if len(tokens) < 2:
        return False, "행정주소 토큰이 2개 미만"
    a1, a2 = tokens[0], tokens[1]
    if _is_wildcard_only(a1) or _is_wildcard_only(a2):
        return False, "wildcard-only 입력"
    if len(a1) < _MIN_TOKEN_LEN or len(a2) < _MIN_TOKEN_LEN:
        return False, "검색 토큰이 너무 짧음"
    return True, ""


def lookup_reghist(cur, admin_addr: str) -> LookupResult:
    """APW_RegHist 제한 조회. 실행기(고정 쿼리)만 사용. 복수/초과는 임의 선택하지 않음."""
    ok, reason = validate_reghist_input(admin_addr)
    if not ok:
        return LookupResult(INVALID_ADDRESS, 0, reasons=[reason])
    tokens = reghist_tokens(admin_addr)
    params = [ro_query.like_prefix(tokens[0]), ro_query.like_prefix(tokens[1])]
    try:
        rows = ro_query.execute_registered(cur, "LOOKUP_REGHIST", params)
    except (ro_query.UnregisteredOperation, ro_query.QueryContract) as e:
        return LookupResult(QUERY_BLOCKED, 0, reasons=[type(e).__name__])
    except Exception as e:
        return LookupResult(QUERY_FAILED, 0, reasons=[type(e).__name__])

    status = _classify(rows, ro_query.REGHIST_TOP)
    dtos = [
        MaskedRegHistDTO(
            reg_masked=_mask_ident((r[0] or "").strip()),
            eub_masked=_mask_ident((r[1] or "").strip()),
            name_masked=security.mask_name((r[2] or "").strip()),
        )
        for r in rows
    ]
    raw = None
    if status == SINGLE:
        r = rows[0]
        raw = {"Reg": (r[0] or "").strip(), "Eub": (r[1] or "").strip()}
    return LookupResult(status, len(rows), dtos=dtos, _raw_selected=raw)


# ───────────────────────────── Customer ─────────────────────────────
_BRANCH_SUFFIXES = ("지점", "금융센터", "센터", "영업부", "본점", "출장소")


def branch_variants(branch: str) -> list[str]:
    """참조 규칙: 원문 지점명 + (알려진 접미사 없으면) '지점' 부가."""
    b = (branch or "").strip()
    if not b:
        return []
    variants = [b]
    if not any(b.endswith(s) for s in _BRANCH_SUFFIXES):
        variants.append(b + "지점")
    return variants


def rank_customer_rows(rows: list, bank_name: str, branch_name: str) -> list:
    """참조 프로젝트 랭킹 규칙 이식(낮을수록 우선). 임의 선택이 아니라 결정적 정렬."""
    bank = (bank_name or "").strip()
    branch = (branch_name or "").strip()

    def key(r):
        cust_id = (r[0] or "").strip()
        cust_name = (r[1] or "").strip()
        active = (r[2] or "").strip().upper()
        score = 0
        if active == "Y":
            score -= 100
        if bank and cust_name.startswith(bank):
            score -= 10
        if branch and branch in cust_name:
            score -= 5
        score += len(cust_name)
        return (score, cust_name, cust_id)

    return sorted(rows, key=key)


def validate_customer_input(bank_name: str, branch_name: str) -> tuple[bool, str]:
    bank = (bank_name or "").strip()
    branch = (branch_name or "").strip()
    if len(bank) < _MIN_TOKEN_LEN:
        return False, "은행명이 너무 짧음/비어 있음"
    if not branch:
        return False, "지점명이 비어 있음"
    if _is_wildcard_only(bank) or _is_wildcard_only(branch):
        return False, "wildcard-only 입력"
    return True, ""


def lookup_customer(cur, bank_name: str, branch_name: str) -> LookupResult:
    """APW_Customer 제한 조회. 고정 쿼리 + 바인딩. 복수 후보는 임의 선택하지 않는다.

    참조와 동일하게 은행 접두 + 지점 포함 LIKE 로 조회하고 랭킹은 Python 에서 결정적으로.
    """
    ok, reason = validate_customer_input(bank_name, branch_name)
    if not ok:
        return LookupResult(INVALID, 0, reasons=[reason])
    bank = bank_name.strip()
    branch = branch_name.strip()
    exact_default = (bank == "우리은행" and branch == bank)
    op_id = "LOOKUP_CUSTOMER_EXACT" if exact_default else "LOOKUP_CUSTOMER"
    params = ([bank] if exact_default else
              [ro_query.like_prefix(bank), ro_query.like_contains(branch)])
    try:
        rows = ro_query.execute_registered(cur, op_id, params)
    except (ro_query.UnregisteredOperation, ro_query.QueryContract) as e:
        return LookupResult(QUERY_BLOCKED, 0, reasons=[type(e).__name__])
    except Exception as e:
        return LookupResult(QUERY_FAILED, 0, reasons=[type(e).__name__])

    ranked = rank_customer_rows(list(rows), bank, branch)
    status = _classify(ranked, ro_query.CUSTOMER_TOP)
    dtos = [
        MaskedCustomerDTO(
            cust_id_masked=_mask_ident((r[0] or "").strip()),
            cust_name_masked=security.mask_name((r[1] or "").strip()),
            active=(r[2] or "").strip().upper(),
        )
        for r in ranked
    ]
    raw = None
    if status == SINGLE:
        r = ranked[0]
        raw = {"CustID": (r[0] or "").strip()}
    return LookupResult(status, len(ranked), dtos=dtos, _raw_selected=raw)


def lookup_customer_exact(cur, cust_name: str) -> LookupResult:
    """정규화된 CustName 정확 일치 조회. 단일 결과만 선택한다."""
    name = (cust_name or "").strip()
    if len(name) < _MIN_TOKEN_LEN or _is_wildcard_only(name):
        return LookupResult(INVALID, 0, reasons=["거래처명이 비어 있거나 잘못됨"])
    try:
        rows = ro_query.execute_registered(cur, "LOOKUP_CUSTOMER_EXACT", [name])
    except (ro_query.UnregisteredOperation, ro_query.QueryContract) as e:
        return LookupResult(QUERY_BLOCKED, 0, reasons=[type(e).__name__])
    except Exception as e:
        return LookupResult(QUERY_FAILED, 0, reasons=[type(e).__name__])
    ranked = list(rows)
    status = _classify(ranked, ro_query.CUSTOMER_TOP)
    dtos = [
        MaskedCustomerDTO(
            cust_id_masked=_mask_ident((r[0] or "").strip()),
            cust_name_masked=security.mask_name((r[1] or "").strip()),
            active=(r[2] or "").strip().upper(),
        ) for r in ranked
    ]
    raw = {"CustID": (ranked[0][0] or "").strip()} if status == SINGLE else None
    return LookupResult(status, len(ranked), dtos=dtos, _raw_selected=raw)


def lookup_managers(cur, cust_id: str) -> list:
    """APW_Customer_Manager 에서 CustID 의 재직 담당자(Manager) distinct 목록을 조회한다.

    고정 쿼리(LOOKUP_MANAGER) + CustID `?` 바인딩. Office 는 고정 상수 필터. 퇴사자는
    TMWCMN_USR_BAC_INFO(USR_SEQ) LEFT JOIN + RTRM_FL<>'1' 로 걸러 재직자만 반환한다
    (직원 마스터에 없는 미매칭 Manager 코드는 재직 취급으로 보존 = fail-open).
    반환은 비어있지 않은 distinct Manager 문자열 리스트(원 순서 유지). 조회 실패·미등록·
    빈 CustID 는 빈 리스트(호출자에서 저장 진행 = fail-open). Manager 값 자체는 상위
    호출자가 allowlist 비교에만 쓰고 로그로 남기지 않는다(PII 취급).
    """
    cid = (cust_id or "").strip()
    if not cid:
        return []
    try:
        rows = ro_query.execute_registered(cur, "LOOKUP_MANAGER", [cid])
    except Exception:
        return []
    out = []
    for r in rows:
        val = ("" if r[0] is None else str(r[0])).strip()
        if val and val not in out:
            out.append(val)
    return out
