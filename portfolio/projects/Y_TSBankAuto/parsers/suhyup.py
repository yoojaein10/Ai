# -*- coding: utf-8 -*-
"""수협은행 탁상감정평가의뢰서 파서.

라벨: 의뢰점 / 담당자 / 전화번호 / 소재지.
의뢰점명이 두 줄로 갈라질 수 있어 앞·뒤 줄을 결합한다.
의뢰일자도 날짜(오전/오후)와 시각이 다른 줄로 갈라질 수 있어 결합한다.
'통조림가공수산업협동조합' → '통조림가공수협' 축약(이 모듈에 격리).
"""
from __future__ import annotations

import re

from models import RequestModel
from parsers import base


def parse(lines: list[str]) -> RequestModel:
    full = "\n".join(lines)
    m = RequestModel(bank="수협은행")

    mo = re.search(r"의뢰번호:\s*([A-Za-z0-9\-]+)", full)
    if mo:
        m.request_no = mo.group(1)

    # 의뢰점 라인 + 앞뒤 줄로 의뢰점명 결합
    idx = next((i for i, ln in enumerate(lines) if base.nospace(ln).startswith("의뢰점")), -1)
    if idx >= 0:
        ln = lines[idx]
        # 담당자 / 전화번호 추출
        mm = re.search(r"담당자\s*(\S+)", ln)
        if mm:
            m.staff_name = mm.group(1)
        mp = re.search(r"전화번호\s*([0-9\-]+)", ln)
        if mp:
            m.branch_phone = mp.group(1)
        # 실제 양식은 의뢰점 값도 같은 추출 행에서 담당자 라벨 앞에 온다.
        part = re.split(r"의뢰점", ln, 1)[-1]
        same_line_branch, _ = base.split_two(part, "담당자")
        prev = base.clean(lines[idx - 1]) if idx - 1 >= 0 else ""
        nxt = base.clean(lines[idx + 1]) if idx + 1 < len(lines) else ""
        # prev/nxt 가 라벨 줄이면 제외
        if any(t in prev for t in ("기본", "소 속", "채무자", "휴대폰")):
            prev = ""
        m.branch = same_line_branch or base.clean(f"{prev} {nxt}")

    # 의뢰일자: 날짜(오전/오후) + 시각 결합
    dm = re.search(r"(\d{4}-\d{2}-\d{2})\s*(오전|오후)?", full)
    tm = re.search(r"\b(\d{1,2}:\d{2}:\d{2})\b", full)
    if dm:
        combined = dm.group(0)
        if tm:
            combined = f"{dm.group(1)} {dm.group(2) or ''} {tm.group(1)}"
        m.request_datetime, m.request_date_only = base.parse_datetime(combined)

    for i, ln in enumerate(lines):
        sN = base.nospace(ln)
        if sN.startswith("소재지"):
            v = base.clean(re.split("소재지", ln, 1)[-1])
            if v:
                m.addresses.append(v)
        if "신축년도" in ln and not m.building_year:
            my = re.search(r"신축년도\s+([\d\-.]+)", ln)
            if my:
                m.building_year = my.group(1)
        if "건물구조" in ln and not m.building_structure:
            v = base.clean(re.split("건물구조", ln, 1)[-1])
            if v and not v.isdigit():
                m.building_structure = v
        if "성 명" in ln and "채무자" not in sN and not m.owner:
            # 수협 채무자 성명
            name, _ = base.split_two(re.split(r"성\s*명", ln, 1)[-1], "자택전화번호")
            if name:
                m.debtor = name
        if sN.startswith("참고사항") and not m.remarks:
            same = base.clean(re.split("참고사항", ln, 1)[-1])
            if same:
                m.remarks = same
            else:
                parts = []
                if i > 0:
                    prev = base.clean(lines[i - 1])
                    if prev and not any(x in prev for x in ("기관", "의뢰일자")):
                        parts.append(prev)
                j = i + 1
                while j < len(lines) and "물건내역" not in lines[j]:
                    value = base.clean(lines[j])
                    if value and not value.startswith("▣"):
                        parts.append(value)
                    j += 1
                m.remarks = " ".join(parts)

    _, m.missing = m.has_required()
    return m


def normalize_custname(m: RequestModel) -> str:
    branch = (m.branch or "").strip()
    # '수산업협동조합'(줄바꿈으로 공백이 낀 '수산업협동 조합' 포함) → '수협'
    branch = re.sub(r"수산업\s*협\s*동\s*조\s*합", "수협", branch)
    branch = re.sub(r"\s+", " ", branch).strip()
    if not branch:
        return "수협은행"
    if "수협" in branch:
        return branch
    return f"수협은행 {branch}"
