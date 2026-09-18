# -*- coding: utf-8 -*-
"""은행별 파서 레지스트리 및 디스패치."""
from __future__ import annotations

from models import RequestModel
from parsers import (
    base, forest, hana, ibk, imbank, kookmin, koreainvest, nhcentral,
    nonghyup, saemaeul, shinhan, suhyup, woori,
)

# 은행명 → 모듈
_REGISTRY = {
    "우리은행": woori,
    "국민은행": kookmin,
    "새마을금고": saemaeul,
    "기업은행": ibk,
    "하나은행": hana,
    "신한은행": shinhan,
    "아이엠뱅크": imbank,
    "농협은행": nonghyup,
    "농협중앙회": nhcentral,
    "산림조합중앙회": forest,
    "수협은행": suhyup,
    "한국투자저축은행": koreainvest,
}


class UnknownBankError(Exception):
    """헤더에서 지원 은행을 판별하지 못함."""


class ExcludedRequest(Exception):
    """저장 제외 대상이라 파싱/저장하지 않음.

    일반 파싱 실패(UnknownBankError 등)와 구분되는 명시적 제외 상태다(§7).
    안전코드: EXCLUDED_HUG(의뢰기관=주택도시보증공사), EXCLUDED_NO_BANK(은행명
    미상), EXCLUDED_NO_BRANCH(영업점 미상), EXCLUDED_MANAGER(담당자 제외).
    """

    def __init__(self, code: str = "EXCLUDED_HUG"):
        self.code = code
        super().__init__(code)


def parse_request(lines: list[str]) -> RequestModel:
    """라인 → 은행 판별 → 은행별 파서 → RequestModel.

    은행 파서 선택 전에 '의뢰기관' 값 셀로 제외 여부를 먼저 판정한다(§1).
    은행명 미판별·영업점(지점/금고명) 미추출 건도 실패가 아닌 저장 제외로
    분류한다(ExcludedRequest).
    """
    if base.requesting_agency_excluded(lines):
        raise ExcludedRequest()
    bank = base.detect_bank(lines)
    if not bank:
        raise ExcludedRequest("EXCLUDED_NO_BANK")
    if bank not in _REGISTRY:
        raise UnknownBankError(f"지원하지 않는 은행: {bank}")
    model = _REGISTRY[bank].parse(lines)
    if not (model.branch or "").strip():
        raise ExcludedRequest("EXCLUDED_NO_BRANCH")
    return model


def build_custname(m: RequestModel) -> str:
    """은행별 CustName 정규화 규칙 적용. 전역 무차별 치환 금지."""
    mod = _REGISTRY.get(m.bank)
    if mod and hasattr(mod, "normalize_custname"):
        return mod.normalize_custname(m)
    # 기본: 은행명 + 영업점
    return f"{m.bank} {m.branch}".strip()


__all__ = ["parse_request", "build_custname", "UnknownBankError",
           "ExcludedRequest", "base"]
