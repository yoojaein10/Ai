# -*- coding: utf-8 -*-
"""신한은행 탁상자문평가의뢰서 파서."""
from __future__ import annotations

import re

from models import RequestModel
from parsers import base


def _strip_branch_code(value: str) -> str:
    return base.clean(re.sub(r"\([^)]*$|\([^)]*\)", "", value or ""))


def parse(lines: list[str]) -> RequestModel:
    full = "\n".join(lines)
    m = RequestModel(bank="신한은행")

    mo = re.search(r"의뢰번호:\s*([A-Za-z0-9\-]+)", full)
    if mo:
        m.request_no = mo.group(1)

    first_obj = next((i for i, ln in enumerate(lines) if "물건내역" in ln), len(lines))
    head, obj = lines[:first_obj], lines[first_obj:]

    for i, ln in enumerate(head):
        ns = base.nospace(ln)
        if not m.branch and i + 1 < len(head) and "의뢰점" in head[i + 1]:
            m.branch = _strip_branch_code(ln)
        if "의뢰점" in ln:
            # 신형 양식은 `의뢰점 지점명(코드) 담당자 ...`를 한 줄에 배치한다.
            branch_part = re.split(r"의\s*뢰\s*점", ln, 1)[-1]
            branch, _ = base.split_two(branch_part, "담당자")
            if branch:
                m.branch = _strip_branch_code(branch)
            staff, phone = base.split_two(re.split("담당자", ln, 1)[-1], "전화번호")
            m.staff_name = staff
            if phone:
                m.branch_phone = phone
        if ns.startswith("비고"):
            m.remarks = base.clean(re.split(r"비\s*고", ln, 1)[-1])

    md = re.search(r"(\d{4}-\d{2}-\d{2})\s*(오전|오후).*?(\d{1,2}:\d{2}:\d{2})", full, re.S)
    if md:
        m.request_datetime, m.request_date_only = base.parse_datetime(
            f"{md.group(1)} {md.group(2)} {md.group(3)}")

    for ln in obj:
        ns = base.nospace(ln)
        if "담보종류" in ns and not m.property_type:
            m.property_type = base.clean(re.split("담보종류", ln, 1)[-1])
        if ns.startswith("비고") and not m.remarks:
            m.remarks = base.clean(re.split(r"비\s*고", ln, 1)[-1])

    addrs = base.find_addresses(obj)
    if addrs:
        m.addresses = addrs
        if len(addrs) > 1:
            m.extra_units = addrs[1:]

    _, m.missing = m.has_required()
    return m


def normalize_custname(m: RequestModel) -> str:
    branch = (m.branch or "").strip()
    if not branch:
        return "신한은행"
    suffixes = ("지점", "센터", "금융센터", "본점", "영업부")
    if not branch.endswith(suffixes):
        branch += "지점"
    return f"신한은행 {branch}"
