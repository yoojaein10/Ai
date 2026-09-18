# -*- coding: utf-8 -*-
"""농협중앙회 탁상자문의뢰서 파서."""
from __future__ import annotations

import re

from models import RequestModel
from parsers import base


def parse(lines: list[str]) -> RequestModel:
    full = "\n".join(lines)
    m = RequestModel(bank="농협중앙회")

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
            part = re.split(r"영\s*업\s*점", ln, 1)[-1]
            branch, phone = base.split_two(part, "전화번호")
            m.branch = branch
            if phone:
                m.branch_phone = phone
        if ns.startswith("담당자"):
            m.staff_name = base.clean(re.split(r"담\s*당\s*자", ln, 1)[-1])
        if ns.startswith("전달사항"):
            m.remarks = base.clean(re.split("전달사항", ln, 1)[-1])
        if "채무자" in ln and "성 명" in ln:
            part = re.split(r"성\s*명", ln, 1)[-1]
            m.debtor = base.split_two(part, "전화번호")[0]

    addr1_values: list[str] = []
    addr2_values: list[str] = []
    for ln in obj:
        ns = base.nospace(ln)
        if "물건종류" in ns and not m.property_type:
            m.property_type = base.clean(re.split("물건종류", ln, 1)[-1])
        if ns.startswith("주소1") or re.match(r"주\s*소\s*1", ln):
            v = base.clean(re.split(r"주\s*소\s*1", ln, 1)[-1])
            if v:
                addr1_values.append(v)
        if ns.startswith("주소2") or re.match(r"주\s*소\s*2", ln):
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
    return (m.branch or "").strip() or "농협중앙회"
