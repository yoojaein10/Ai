# -*- coding: utf-8 -*-
"""산림조합중앙회 탁상자문의뢰서 파서."""
from __future__ import annotations

import re

from models import RequestModel
from parsers import base


def parse(lines: list[str]) -> RequestModel:
    full = "\n".join(lines)
    m = RequestModel(bank="산림조합중앙회")

    mo = re.search(r"의뢰번호:\s*([A-Za-z0-9\-]+)", full)
    if mo:
        m.request_no = mo.group(1)

    first_obj = next((i for i, ln in enumerate(lines) if "물건내역" in ln), len(lines))
    head, obj = lines[:first_obj], lines[first_obj:]

    for ln in head:
        ns = base.nospace(ln)
        if "의뢰일자" in ln:
            dt, only = base.parse_datetime(re.split("의뢰일자", ln, 1)[-1])
            m.request_datetime, m.request_date_only = dt, only
        if ns.startswith("영업점"):
            m.branch = base.clean(re.split(r"영\s*업\s*점", ln, 1)[-1])
        if "담당자명" in ln:
            staff, phone = base.split_two(re.split("담당자명", ln, 1)[-1], "전화번호")
            m.staff_name = staff
            if phone:
                m.branch_phone = phone
        if ns.startswith("참고사항"):
            m.remarks = base.clean(re.split("참고사항", ln, 1)[-1])
        if "채무자명" in ln:
            m.debtor = base.split_two(re.split("채무자명", ln, 1)[-1], "채무자 연락처")[0]

    base_addr = ""
    for ln in obj:
        ns = base.nospace(ln)
        if "담보종류" in ns and not m.property_type:
            m.property_type = base.clean(re.split("담보종류", ln, 1)[-1])
        if "기본주소" in ln:
            base_addr = base.clean(re.split("기본주소", ln, 1)[-1])
        if "상세주소" in ln:
            detail = base.clean(re.split("상세주소", ln, 1)[-1])
            if base_addr and detail:
                m.addresses.append(f"{base_addr} {detail}")
            elif base_addr:
                m.addresses.append(base_addr)

    # 상세주소가 빈 줄로 분리되어 마지막 기본주소만 남는 경우.
    if not m.addresses:
        addrs = base.find_addresses(obj)
        if addrs:
            m.addresses = addrs

    if len(m.addresses) > 1:
        m.extra_units = m.addresses[1:]

    _, m.missing = m.has_required()
    return m


def normalize_custname(m: RequestModel) -> str:
    return (m.branch or "").strip() or "산림조합중앙회"
