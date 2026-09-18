# -*- coding: utf-8 -*-
"""농협은행 파서.

라벨: 영업점 / 전화번호 / 담 당 자 / 주 소1 / 주 소2.
▣물건내역 블록이 반복될 수 있다. 대표=첫 블록 주소1, 나머지는 병합.
"""
from __future__ import annotations

import re

from models import RequestModel
from parsers import base


def parse(lines: list[str]) -> RequestModel:
    full = "\n".join(lines)
    m = RequestModel(bank="농협은행")

    mo = re.search(r"의뢰번호:\s*([A-Za-z0-9\-]+)", full)
    if mo:
        m.request_no = mo.group(1)

    # head = 첫 물건내역 이전
    first_obj = next((i for i, ln in enumerate(lines) if "물건내역" in ln), len(lines))
    head = lines[:first_obj]

    for ln in head:
        if "의뢰일자" in ln:
            dt, only = base.parse_datetime(re.split("의뢰일자", ln, 1)[-1])
            m.request_datetime, m.request_date_only = dt, only
        if base.nospace(ln).startswith("영업점"):
            part = re.split(r"영\s*업\s*점", ln, 1)[-1]
            branch, phone = base.split_two(part, "전화번호")
            m.branch = branch
            if phone:
                m.branch_phone = phone
        if base.nospace(ln).startswith("담당자"):
            m.staff_name = base.clean(re.split(r"담\s*당\s*자", ln, 1)[-1])
        if "채무자" in ln and "성" in ln and "명" in ln:
            name, _ = base.split_two(re.split(r"성\s*명", ln, 1)[-1], "전화번호")
            m.debtor = name

    # 물건내역 블록 단위
    obj = lines[first_obj:]
    addr1_values: list[str] = []
    addr2_values: list[str] = []
    for ln in obj:
        sN = base.nospace(ln)
        if sN.startswith("주소1") or re.match(r"주\s*소\s*1", ln):
            v = base.clean(re.split(r"주\s*소\s*1", ln, 1)[-1])
            if v:
                # `산269 산 269-`처럼 주소1 끝에 중복 인쇄된 지번 꼬리 제거.
                v = re.sub(r"(산\s*\d+)\s+산\s+\d+\s*-?\s*$", r"\1", v)
                addr1_values.append(v)
        if sN.startswith("주소2") or re.match(r"주\s*소\s*2", ln):
            v = base.clean(re.split(r"주\s*소\s*2", ln, 1)[-1])
            if v:
                addr2_values.append(v)
        if "구 조" in ln and not m.building_structure:
            v = base.clean(re.split(r"구\s*조", ln, 1)[-1])
            if v:
                m.building_structure = v
        if "신축일자" in ln and not m.building_year:
            my = re.search(r"신축일자\s+([\d\-.]+)", ln)
            if my:
                m.building_year = my.group(1)
        if "물건종류" in ln and not m.property_type:
            _, kind = base.split_two(re.split("일련번호", ln, 1)[-1], "물건종류")
            m.property_type = kind

    # 주소1을 우선 사용하고, 주소1 값이 추출되지 않은 양식만 주소2로 fallback한다.
    if addr1_values:
        m.addresses = addr1_values
        m.fallback_addresses = addr2_values
        if len(addr1_values) > 1:
            m.extra_units = addr1_values[1:]
    elif addr2_values:
        m.addresses = addr2_values
        if len(addr2_values) > 1:
            m.extra_units = addr2_values[1:]

    _, m.missing = m.has_required()
    return m


def normalize_custname(m: RequestModel) -> str:
    branch = (m.branch or "").strip()
    return f"농협은행 {branch}".strip() if branch else "농협은행"
