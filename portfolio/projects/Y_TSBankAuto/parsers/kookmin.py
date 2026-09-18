# -*- coding: utf-8 -*-
"""국민은행 파서.

문서 제목은 `담보감정평가의뢰서`일 수 있으나 탁상 경로 문서다(제목으로 판별 금지).
물건 `주 소`는 `일련번호` 이후 영역에서만 취득(세금계산서 주소와 구분).
다물건이면 대표=첫 물건, 나머지 지번은 구조화 가능할 때만 병합.
"""
from __future__ import annotations

import re

from models import RequestModel
from parsers import base


def parse(lines: list[str]) -> RequestModel:
    full = "\n".join(lines)
    m = RequestModel(bank="국민은행")

    mo = re.search(r"의뢰번호:\s*([A-Za-z0-9\-]+)", full)
    if mo:
        m.request_no = mo.group(1)

    # 일련번호 첫 등장 = 물건 영역 시작
    obj_idx = next((i for i, ln in enumerate(lines) if "일련번호" in ln), len(lines))
    head, obj = lines[:obj_idx], lines[obj_idx:]

    for ln in head:
        if "의뢰일자" in ln:
            dt, only = base.parse_datetime(re.split("의뢰일자", ln, 1)[-1])
            m.request_datetime, m.request_date_only = dt, only
        if "영 업 점" in ln or base.nospace(ln).find("영업점") == 0:
            part = re.split(r"영\s*업\s*점", ln, 1)[-1]
            # 같은 추출 행에 다음 열 라벨 '담당자명'이 붙으면 그 앞에서 지점명을
            # 자른다(§20). 라벨이 없으면 값 전체를 지점명으로 보존한다(§21).
            branch, _ = base.split_two(part, "담당자명")
            m.branch = branch

    # 담당자명 + 전화번호 (영업점 다음 줄)
    for ln in head:
        if "담당자명" in ln:
            part = re.split("담당자명", ln, 1)[-1]
            staff, phone = base.split_two(part, "전화번호")
            m.staff_name = staff
            if phone:
                m.branch_phone = phone
            break

    # 전화번호가 담당자명과 별도 행에 배치되는 실제 국민은행 양식.
    if not m.branch_phone:
        for ln in head:
            if base.nospace(ln).startswith("전화번호"):
                phone = base.clean(re.split("전화번호", ln, 1)[-1])
                if re.fullmatch(r"[0-9\- ]+", phone or ""):
                    m.branch_phone = phone
                    break

    # 채무자 성명 (PII)
    for ln in head:
        if "채무자" in ln and "성" in ln and "명" in ln:
            name, _ = base.split_two(re.split(r"성\s*명", ln, 1)[-1], "전화번호")
            m.debtor = name
            break

    # 참고사항
    for ln in head:
        if base.nospace(ln).startswith("참고사항"):
            m.remarks = base.clean(re.split("참고사항", ln, 1)[-1])
            break

    # 물건종류 / 추가필지
    extra: list[str] = []
    for ln in obj:
        sN = base.nospace(ln)
        if "물건종류" in sN and not m.property_type:
            kind, _ = base.split_two(re.split("물건종류", ln, 1)[-1], "취약담보물여부")
            if kind:
                m.property_type = kind
        if "추가필지정보" in ln:
            v = base.clean(re.split("추가필지정보", ln, 1)[-1])
            if v:
                extra.append(v)

    # 주소: 세금계산서 주소(head)와 분리하기 위해 물건 영역(obj)에서만 탐색.
    addrs = base.find_addresses(obj)
    if addrs:
        m.addresses = addrs
        if len(addrs) > 1:
            m.extra_units = addrs[1:]
    if not m.extra_units and extra:
        m.extra_units = extra

    _, m.missing = m.has_required()
    return m


def normalize_custname(m: RequestModel) -> str:
    branch = (m.branch or "").strip()
    if not branch:
        return "국민은행"
    suffixes = ("지점", "센터", "금융센터", "본점", "영업부")
    if not branch.endswith(suffixes):
        branch += "지점"
    return f"국민은행 {branch}"
