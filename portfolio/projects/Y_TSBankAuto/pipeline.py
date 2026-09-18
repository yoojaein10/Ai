# -*- coding: utf-8 -*-
"""PDF 라인 → 공통모델 → 주소구조화 → SP 파라미터 조립 오케스트레이션.

GUI/테스트 공용. DB/Bank24/네트워크에 접근하지 않는다(순수 변환).
Reg/Eub 는 이번 작업에서 조회하지 않으므로 None(파라미터는 명시적 NULL).
"""
from __future__ import annotations

from dataclasses import dataclass

import address_mapper
import parsers
import sp_spec   # 파라미터 빌더(실행/커밋 코드 미포함; 지시 §13)
from models import RequestModel, StructuredAddress


@dataclass
class PreparedRequest:
    model: RequestModel
    structured: StructuredAddress
    custname: str
    custphone: str
    custcharge: str
    params: dict | None           # 필수 미충족 시 None (SP 호출 대상 아님)
    eligible: bool
    reasons: list[str]            # 비대상 사유
    addr_len_check: dict


def build_custcharge(m: RequestModel) -> str:
    """담당자명 + 내선번호(있으면). PDF 파생값만."""
    staff = (m.staff_name or "").strip()
    ext = (m.extension or "").strip()
    if staff and ext:
        return f"{staff}/{ext}"
    return staff or ""


def prepare(lines: list[str]) -> PreparedRequest:
    model = parsers.parse_request(lines)
    structured = address_mapper.structure_address(model.representative_address())
    if model.bank == "새마을금고" and structured.building_nm:
        branch_tokens = (model.branch or "").split()
        locality = branch_tokens[-1] if len(branch_tokens) > 1 else ""
        if locality and structured.building_nm.startswith(locality + " "):
            structured.building_nm = structured.building_nm[len(locality):].strip()
            parts = [structured.building_nm]
            if structured.dong:
                parts.append(f"{structured.dong}동")
            if structured.ho:
                parts.append(f"{structured.ho}호")
            structured.building = " ".join(parts)
    custname = parsers.build_custname(model)
    custphone = (model.branch_phone or "").strip()
    custcharge = build_custcharge(model)

    reasons: list[str] = []
    ok_required, missing = model.has_required()
    if not ok_required:
        reasons.append("필수 필드 누락: " + ", ".join(missing))
    if not model.request_datetime:
        reasons.append("의뢰일시 누락(발번 불가)")

    # Addr 길이 검증 (provisional: 콜레이션 미확인)
    addr_len_check = address_mapper.validate_addr_length(structured.admin_addr, max_len=40)
    if not addr_len_check["ok"]:
        reasons.append("Addr 길이/인코딩 실패: " + addr_len_check["reason"])

    eligible = not reasons
    params = None
    if eligible:
        params = sp_spec.build_sp_params(
            model,
            custname=custname, custphone=custphone, custcharge=custcharge,
            addr=structured, reg=None, eub=None,
        )

    return PreparedRequest(
        model=model, structured=structured,
        custname=custname, custphone=custphone, custcharge=custcharge,
        params=params, eligible=eligible, reasons=reasons,
        addr_len_check=addr_len_check,
    )
