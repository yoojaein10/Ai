# -*- coding: utf-8 -*-
"""한국투자저축은행 탁상자문의뢰서 파서."""
from __future__ import annotations

import re

from models import RequestModel
from parsers import base


def parse(lines: list[str]) -> RequestModel:
    full = "\n".join(lines)
    m = RequestModel(bank="한국투자저축은행")

    mo = re.search(r"의뢰번호:\s*([A-Za-z0-9\-]+)", full)
    if mo:
        m.request_no = mo.group(1)

    basic_addr = ""
    detail_addr = ""
    for ln in lines:
        sN = base.nospace(ln)
        if "의뢰일자" in ln:
            m.request_datetime, m.request_date_only = base.parse_datetime(
                re.split("의뢰일자", ln, 1)[-1])
        if "영업점" in sN:
            part = re.split(r"영\s*업\s*점", ln, 1)[-1]
            m.branch, _ = base.split_two(part, "담당자명")
        if sN.startswith("담당자명"):
            part = re.split("담당자명", ln, 1)[-1]
            m.staff_name, phone = base.split_two(part, "전화번호")
            if phone:
                m.branch_phone = phone
        if base.nospace(ln).startswith("참고사항"):
            m.remarks = base.clean(re.split("참고사항", ln, 1)[-1])
        if "물건종류" in ln and not m.property_type:
            _, m.property_type = base.split_two(
                re.split("일련번호", ln, 1)[-1], "물건종류")
        if sN.startswith("기본주소"):
            basic_addr = base.clean(re.split("기본주소", ln, 1)[-1])
        if sN.startswith("상세주소"):
            detail_addr = base.clean(re.split("상세주소", ln, 1)[-1])

    address = base.clean(f"{basic_addr} {detail_addr}")
    if address:
        address = re.sub(r"(\d+(?:-\d+)?)\s*번지\b", r"일반 \1", address)
        m.addresses = [address]

    _, m.missing = m.has_required()
    return m


def normalize_custname(m: RequestModel) -> str:
    branch = (m.branch or "").strip()
    return f"한국투자저축은행 {branch}".strip()
