# -*- coding: utf-8 -*-
"""하나은행 탁상자문의뢰서 파서."""
from __future__ import annotations

import re

from models import RequestModel
from parsers import base


def _after_label(line: str, label: str) -> str:
    if label not in line:
        return ""
    return base.clean(line.split(label, 1)[-1])


def _strip_next_label(value: str, *labels: str) -> str:
    out = value
    for label in labels:
        if label in out:
            out = out.split(label, 1)[0]
    return base.clean(out)


def _parse_extension(lines: list[str], phone: str) -> str:
    full = "\n".join(lines)
    m = re.search(r"내선\s*([0-9]{2,5})", full)
    if m:
        return m.group(1)
    digits = re.sub(r"\D+", "", phone or "")
    if digits:
        m = re.search(rf"{re.escape(digits[:2])}[-\s]*{re.escape(digits[2:6])}[-\s]*{re.escape(digits[6:])}\s*\((\d{{2,5}})\)", full)
        if m:
            return m.group(1)
    m = re.search(r"\((\d{2,5})\)", full)
    return m.group(1) if m else ""


def parse(lines: list[str]) -> RequestModel:
    full = "\n".join(lines)
    m = RequestModel(bank="하나은행")

    mo = re.search(r"의뢰번호:\s*([A-Za-z0-9\-]+)", full)
    if mo:
        m.request_no = mo.group(1)

    for ln in lines:
        if "영 업 점" in ln or "영업점" in base.nospace(ln):
            part = re.split(r"영\s*업\s*점", ln, 1)[-1]
            branch, rest = base.split_two(part, "담당자명")
            m.branch = branch
            if rest:
                m.staff_name = _strip_next_label(rest, "전화번호")
            continue
        if "의뢰일자" in ln:
            tail = _after_label(ln, "의뢰일자")
            dt_part, phone_part = base.split_two(tail, "전화번호")
            m.request_datetime, m.request_date_only = base.parse_datetime(dt_part)
            if phone_part:
                m.branch_phone = phone_part
            continue
        if "채무자" in ln and "성 명" in ln:
            part = re.split(r"성\s*명", ln, 1)[-1]
            m.debtor = _strip_next_label(part, "전화번호")

    # 기타 정보: 요청사항/내선/다중 호수 등이 들어간다.
    remarks: list[str] = []
    capture = False
    for ln in lines:
        ns = base.nospace(ln)
        if ns.startswith("기타"):
            capture = True
            v = re.split(r"기\s*타", ln, 1)[-1]
            v = re.sub(r"^\s*정\s*보\s*", "", v)
            if base.clean(v):
                remarks.append(base.clean(v))
            continue
        if capture:
            if "물건정보" in ns or ns.startswith("소유자"):
                break
            v = re.sub(r"^\s*정\s*보\s*", "", ln)
            if base.clean(v):
                remarks.append(base.clean(v))
    m.remarks = base.clean(" ".join(remarks))
    m.extension = _parse_extension(lines, m.branch_phone)

    obj_idx = next((i for i, ln in enumerate(lines)
                    if "물건정보" in base.nospace(ln)),
                   len(lines))
    obj = lines[obj_idx:]
    for ln in obj:
        ns = base.nospace(ln)
        if "물건종류" in ns and not m.property_type:
            part = re.split(r"물건종류", ln, 1)[-1]
            kind, _ = base.split_two(part, "소 유 자")
            m.property_type = kind

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
        return "하나은행"
    suffixes = ("지점", "센터", "금융센터", "본점", "영업부")
    if not branch.endswith(suffixes):
        branch += "지점"
    return f"하나은행 {branch}"
