# -*- coding: utf-8 -*-
"""새마을금고 파서.

은행명이 헤더 별도 줄에 있고 `의뢰기관:` 값은 비어 있을 수 있다.
라벨: 금 고 / 금고 담당자명 / 금고 전화번호 / 세부주소.
CustName 은 금고명+본점·지점 표현을 정규화한다(이 모듈에 격리).
"""
from __future__ import annotations

import re

from models import RequestModel
from parsers import base


def parse(lines: list[str]) -> RequestModel:
    full = "\n".join(lines)
    m = RequestModel(bank="새마을금고")

    mo = re.search(r"의뢰번호:\s*([A-Za-z0-9\-]+)", full)
    if mo:
        m.request_no = mo.group(1)

    for ln in lines:
        sN = base.nospace(ln)
        if sN.startswith("금고") and "담당자" not in sN and "전화" not in sN:
            m.branch = base.clean(re.split(r"금\s*고", ln, 1)[-1])
        if "금고담당자명" in sN or ("담당자명" in ln and "금고" in ln):
            part = re.split("담당자명", ln, 1)[-1]
            staff, phone = base.split_two(part, "금고 전화번호")
            if not phone:
                staff, phone = base.split_two(part, "전화번호")
            m.staff_name = staff
            if phone:
                m.branch_phone = re.sub(r"^금고\s*전화번호\s*", "", phone)
        if "전화번호" in ln and "금고" in ln and not m.branch_phone:
            m.branch_phone = base.clean(re.split("전화번호", ln, 1)[-1])
        if "의뢰일자" in ln:
            dt, only = base.parse_datetime(re.split("의뢰일자", ln, 1)[-1])
            m.request_datetime, m.request_date_only = dt, only
        if "채무자" in ln and "성" in ln and "명" in ln:
            name, _ = base.split_two(re.split(r"성\s*명", ln, 1)[-1], "전화번호")
            m.debtor = name
        if "소유자" in ln and "성" in ln and "명" in ln:
            name, phone = base.split_two(re.split(r"성\s*명", ln, 1)[-1], "전화번호")
            m.owner, m.owner_phone = name, phone
        if "물건종류" in ln:
            _, kind = base.split_two(re.split(r"번\s*호", ln, 1)[-1], "물건종류")
            if kind:
                m.property_type = kind

    # 비고: 인라인 "비 고 <값>" 또는 세로 라벨 "기 타 / 비 고 / 정 보"(값이 기타·정보
    # 줄로 나뉘고 비고 줄은 빈 라벨) 레이아웃 모두 지원. 물건정보 이전(head)만 스캔해야
    # 아래 "정 보  <세부주소>"(물건정보 라벨)를 비고로 오인하지 않는다.
    remark_end = next((i for i, ln in enumerate(lines)
                       if "물건정보" in ln or "물건내역" in ln), len(lines))
    _remark_labels = (("기타", r"기\s*타"), ("비고", r"비\s*고"), ("정보", r"정\s*보"))
    remark_parts: list[str] = []
    for ln in lines[:remark_end]:
        sN = base.nospace(ln)
        for key, pat in _remark_labels:
            if sN.startswith(key):
                after = base.clean(re.split(pat, ln, 1)[-1])
                if after:
                    remark_parts.append(after)
                break
    if remark_parts:
        m.remarks = " ".join(remark_parts)

    # 세부주소가 라벨/값 분리 레이아웃일 수 있어 물건정보 영역에서 시도 기반 탐색.
    obj_start = next((i for i, ln in enumerate(lines)
                      if "물건정보" in ln or "물건내역" in ln), 0)
    addrs = base.find_addresses(lines, start=obj_start)
    if addrs:
        m.addresses = addrs
        if len(addrs) > 1:
            m.extra_units = addrs[1:]
    if m.staff_name and not m.extension:
        m.extension = "2"

    _, m.missing = m.has_required()
    return m


def normalize_custname(m: RequestModel) -> str:
    """금고명+본점/지점 정규화: '의왕 본점' → '의왕새마을금고 본점'."""
    branch = (m.branch or "").strip()
    if not branch:
        return "새마을금고"
    if "새마을금고" in branch:
        return branch
    toks = branch.split()
    head = toks[0]
    rest = " ".join(toks[1:])
    if rest and not rest.endswith(("본점", "지점", "센터", "출장소")):
        rest += "지점"
    return f"{head}새마을금고 {rest}".strip()
