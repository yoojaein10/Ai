# -*- coding: utf-8 -*-
"""우리은행 탁상자문의뢰서 파서.

라벨: 영 업 점 / 담당자명 / 전화번호 / 내선번호 / 주 소.
의뢰번호 T... 는 모델에 보존하되 HFDocid 로 쓰지 않는다(@HFDocid=NULL).
"""
from __future__ import annotations

import re

from models import RequestModel
from parsers import base


def parse(lines: list[str]) -> RequestModel:
    full = "\n".join(lines)
    m = RequestModel(bank="우리은행")

    mo = re.search(r"의뢰번호:\s*([A-Za-z0-9\-]+)", full)
    if mo:
        m.request_no = mo.group(1)

    obj_idx = next((i for i, ln in enumerate(lines) if "물건내역" in ln or "물건정보" in ln),
                   len(lines))
    head, obj = lines[:obj_idx], lines[obj_idx:]

    for ln in head:
        if "의뢰일자" in ln:
            dt, only = base.parse_datetime(re.split("의뢰일자", ln, 1)[-1])
            m.request_datetime, m.request_date_only = dt, only
            break

    # 채무자 성명 + 전화번호 (PII)
    for ln in head:
        if "채무자" in ln and "성" in ln and "명" in ln:
            part = re.split(r"성\s*명", ln, 1)[-1]
            name, phone = base.split_two(part, "전화번호")
            m.debtor = name
            break

    # 영업점 + 담당자명
    for ln in head:
        if base.nospace(ln).startswith("영업점") or "영 업 점" in ln:
            part = re.split(r"영\s*업\s*점", ln, 1)[-1]
            branch, staff = base.split_two(part, "담당자명")
            m.branch, m.staff_name = branch, staff
            break
    # 영업점 공란 fallback 없음: 영업점 미상 건은 parse_request 가
    # EXCLUDED_NO_BRANCH 로 저장 제외한다(전 은행 공통, 2026-07-28).

    # 영업점 전화번호 = 영업점 줄 이후 첫 단독 전화번호
    seen = False
    for ln in head:
        if "영 업 점" in ln or base.nospace(ln).startswith("영업점"):
            seen = True
            continue
        if seen and "전화번호" in ln and "성" not in ln:
            m.branch_phone = base.clean(re.split("전화번호", ln, 1)[-1])
            break

    for ln in head:
        if "내선번호" in ln:
            ext, _ = base.split_two(re.split("내선번호", ln, 1)[-1], "핸드폰번호")
            m.extension = ext
            break

    for i, ln in enumerate(head):
        if "참고사항" in ln:
            # 참고사항 값이 라벨 줄(same)뿐 아니라 앞/뒤 줄로도 이어지는 우리은행 양식.
            # same 유무와 무관하게 앞줄·라벨줄·뒷줄 연속값을 순서대로 병합한다.
            # (버그: 예전엔 라벨 줄에 값이 있으면 앞/뒤 줄을 버려 비고가 잘렸음.)
            same = base.clean(re.split("참고사항", ln, 1)[-1])
            prev_parts = []
            k = i - 1
            while k >= 0:
                prev = base.clean(head[k])
                prev_ns = base.nospace(prev)
                if not prev or any(label in prev_ns for label in (
                    "의뢰기관", "영업점", "채무자", "전화번호", "의뢰일자", "내선번호",
                )):
                    break
                if "물건내역" in prev_ns or "물건정보" in prev_ns:
                    break
                prev_parts.append(prev)
                k -= 1
            parts = list(reversed(prev_parts))
            if same:
                parts.append(same)
            j = i + 1
            while j < len(head) and "물건내역" not in head[j]:
                value = base.clean(head[j])
                if value and not value.startswith("▣"):
                    parts.append(value)
                j += 1
            m.remarks = " ".join(parts)
            break

    # 물건종류
    for ln in obj:
        if "물건종류" in ln:
            _, kind = base.split_two(re.split("일련번호", ln, 1)[-1], "물건종류")
            m.property_type = kind
            break

    # 주소 (주 소) — 새주소/우편/동코드 제외
    for ln in obj:
        sN = base.nospace(ln)
        if "주소" in sN and "새주소" not in sN and "우편" not in ln and "동코드" not in ln:
            v = base.clean(re.split(r"주\s*소", ln, 1)[-1])
            if v:
                m.addresses.append(v)
                break
    if not m.addresses:
        m.addresses = base.find_addresses(obj)

    # 소유자 성명/전화 (PII)
    for ln in obj:
        if "소유자" in ln and "성" in ln and "명" in ln:
            part = re.split(r"성\s*명", ln, 1)[-1]
            name, phone = base.split_two(part, "전화번호")
            m.owner, m.owner_phone = name, phone
            break

    # 건물구조 (구 조 라인; 지목과 구분)
    for ln in obj:
        sN = base.nospace(ln)
        if "구조" in sN and "용도" in sN and "지목" not in sN:
            struct, _ = base.split_two(re.split("구조", ln, 1)[-1], "용도")
            m.building_structure = struct
            break

    # 건축년도
    for ln in obj:
        if "건축년도" in ln:
            my = re.search(r"건축년도\s+([\d\-.]+)", ln)
            if my:
                m.building_year = my.group(1)
            break

    _, m.missing = m.has_required()
    return m


def normalize_custname(m: RequestModel) -> str:
    branch = (m.branch or "").strip()
    if not branch or branch == "우리은행":
        return "우리은행"
    return f"우리은행 {branch}"
