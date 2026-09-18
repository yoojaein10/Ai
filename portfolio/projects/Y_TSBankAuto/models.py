# -*- coding: utf-8 -*-
"""공통 데이터 모델.

- RequestModel: 은행 공통 접수 모델. debtor/owner/owner_phone(PII)은 메모리에만 보존하며
  SP 로 전송하지 않는다. 영속화(pickle/json/csv) 금지.
- StructuredAddress: 주소 구조화 결과.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields

import security


@dataclass
class StructuredAddress:
    """PDF 주소 구조화 결과."""
    raw: str = ""                 # 원문(메모리 전용)
    admin_addr: str = ""          # 시도·시군구·읍면동·리까지 (Addr 후보)
    san: str = "1"                # 실서버 규칙: '1'=일반, '2'=산
    bun1: str = ""                # 본번 (4자리 0패딩)
    bun2: str = ""                # 부번 (4자리 0패딩)
    building_nm: str = ""         # 건물명 (명확할 때만)
    dong: str = ""                # 동 (명확할 때만)
    ho: str = ""                  # 호 (명확할 때만)
    building: str = ""            # 지번 이후 상세 (명확할 때만)
    addr_etc: str = ""            # 다필지/추가 (명확할 때만)


@dataclass
class RequestModel:
    """은행 공통 접수 모델."""
    bank: str = ""
    request_no: str = ""
    request_datetime: str = ""    # 의뢰일시 (날짜만일 수 있음)
    request_date_only: bool = False  # 시간 없이 날짜만이면 True
    branch: str = ""
    staff_name: str = ""
    branch_phone: str = ""
    extension: str = ""
    # ---- PII (메모리 전용, SP 미전송, 로그 원문 금지) ----
    debtor: str = ""
    owner: str = ""
    owner_phone: str = ""
    # ---- 물건/주소 ----
    addresses: list[str] = field(default_factory=list)   # 원문 주소들(첫번째=대표)
    fallback_addresses: list[str] = field(default_factory=list)
    property_type: str = ""
    building_structure: str = ""
    building_year: str = ""
    building_name: str = ""
    dong: str = ""
    ho: str = ""
    remarks: str = ""
    # 다물건 추가 호/필지 (병합용, 구조화 값만)
    extra_units: list[str] = field(default_factory=list)
    # 파싱 누락 필드명 목록
    missing: list[str] = field(default_factory=list)

    REQUIRED = ("bank", "request_no", "request_datetime", "branch", "addresses")
    PII_FIELDS = ("debtor", "owner", "owner_phone")

    def representative_address(self) -> str:
        """대표 주소 = 첫 번째 물건 (결정적 기준)."""
        return self.addresses[0] if self.addresses else ""

    def has_required(self) -> tuple[bool, list[str]]:
        """필수 필드 충족 여부와 누락 목록."""
        miss = []
        for k in self.REQUIRED:
            v = getattr(self, k)
            if not v:
                miss.append(k)
        return (not miss), miss

    def safe_log_dict(self) -> dict:
        """로그/리포트용 마스킹 dict. PII 원문·전체 모델·PDF 원문 미포함."""
        return {
            "bank": self.bank,
            "request_no": security.mask_request_no(self.request_no),
            "request_datetime": self.request_datetime,
            "branch": self.branch,
            "staff_name": security.mask_name(self.staff_name),
            "branch_phone": security.mask_phone(self.branch_phone),
            "address": security.mask_address(self.representative_address()),
            "property_type": self.property_type,
            "unit_count": len(self.addresses),
        }

    def field_presence(self) -> dict:
        """회귀 테스트용: PII 제외 필드 존재 여부(bool)만."""
        out = {}
        for f in fields(self):
            if f.name in self.PII_FIELDS or f.name in ("missing",):
                continue
            v = getattr(self, f.name)
            if isinstance(v, list):
                out[f.name] = len(v) > 0
            else:
                out[f.name] = bool(v)
        return out
