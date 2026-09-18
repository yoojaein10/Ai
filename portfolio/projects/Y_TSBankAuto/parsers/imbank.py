# -*- coding: utf-8 -*-
"""iM뱅크 탁상자문의뢰서 파서."""
from __future__ import annotations

import re

from models import RequestModel
from parsers import base


def parse(lines: list[str]) -> RequestModel:
    full = "\n".join(lines)
    m = RequestModel(bank="아이엠뱅크")

    mo = re.search(r"의뢰번호:\s*([A-Za-z0-9\-]+)", full)
    if mo:
        m.request_no = mo.group(1)

    for i, ln in enumerate(lines):
        ns = base.nospace(ln)
        if "의뢰일자" in ln:
            dt, only = base.parse_datetime(re.split("의뢰일자", ln, 1)[-1])
            m.request_datetime, m.request_date_only = dt, only
        if ns.startswith("영업점"):
            part = re.split(r"영\s*업\s*점", ln, 1)[-1]
            branch, staff = base.split_two(part, "담당자명")
            m.branch = branch
            m.staff_name = staff
        if ns.startswith("전화번호"):
            m.branch_phone = base.clean(re.split("전화번호", ln, 1)[-1])
        if "채무자명" in ln:
            m.debtor = base.split_two(re.split("채무자명", ln, 1)[-1], "소유자명")[0]
        if ns.startswith("소재지"):
            v = base.clean(re.split("소재지", ln, 1)[-1])
            if v:
                v = v.replace("일반번지", "일반")
                v = re.sub(r"\s+동\s+호$", "", v).strip()
                v = re.sub(r"제([가-힣A-Za-z0-9]+호)호\b", r"제\1", v)
                m.addresses.append(v)
        if ns.startswith("물건종류"):
            m.property_type = base.clean(re.split("물건종류", ln, 1)[-1])

    remarks: list[str] = []
    capture = False
    for idx, ln in enumerate(lines):
        ns = base.nospace(ln)
        if ns.startswith("비고"):
            if idx > 0:
                prev = base.clean(lines[idx - 1])
                if prev and not any(label in prev for label in ("물건종류", "소재지", "세부물건종류")):
                    remarks.append(prev)
            capture = True
            v = base.clean(re.split(r"비\s*고", ln, 1)[-1])
            if v:
                remarks.append(v)
            continue
        if capture:
            if re.fullmatch(r"\d+", ns):
                break
            v = base.clean(ln)
            if v:
                remarks.append(v)
    m.remarks = base.clean(" ".join(remarks))

    _, m.missing = m.has_required()
    return m


def normalize_custname(m: RequestModel) -> str:
    branch = (m.branch or "").strip()
    if not branch:
        return "아이엠뱅크"
    suffixes = ("지점", "센터", "금융센터", "본점", "영업부")
    if not branch.endswith(suffixes):
        branch += "지점"
    return f"아이엠뱅크 {branch}"
