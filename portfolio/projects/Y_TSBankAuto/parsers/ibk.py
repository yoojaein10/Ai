# -*- coding: utf-8 -*-
"""기업은행 파서.

라벨: 영 업 점 / 담당자명 / 대표번호 / 내선번호 / 소 재 지.
의뢰일자는 'YYYYMMDD' 날짜만일 수 있다(시간 임의 생성 금지 → date_only).
영업점 '하남' → '기업은행 하남지점' 형태로 정규화(이 모듈에 격리).
"""
from __future__ import annotations

import re

from models import RequestModel
from parsers import base

_BRANCH_SUFFIX = ("지점", "센터", "점", "출장소")

# 소재지 재조립 시 인접 줄이 다른 항목이면 멈추는 라벨 토큰(공백 제거 후 비교).
_ADDR_STOP_TOKENS = (
    "새주소", "물건", "정보", "토지", "건물", "채무", "소유자", "담당자명",
    "영업점", "우편번호", "참고사항", "휴대폰", "내선번호", "대표번호", "소속",
    "물건종류", "평가사명",
)


def _looks_like_stop(sN: str) -> bool:
    return any(tok in sN for tok in _ADDR_STOP_TOKENS)


def _reconstruct_address(lines: list[str], label_idx: int) -> str:
    """`소 재 지` 라벨이 값과 분리돼 혼자 있는 표 셀 레이아웃 대응.

    실 Bank24 출력 PDF는 긴 주소가 줄바꿈되면 추출 순서가
    값(앞줄) → 라벨 → 값(뒷줄) 로 나온다. 라벨 앞줄(주소 첫 줄)과
    다음 라벨 전까지의 뒷줄들을 이어 붙여 원 주소를 복원한다.
    """
    parts: list[str] = []
    if label_idx - 1 >= 0:
        prev = base.clean(lines[label_idx - 1])
        if prev and not _looks_like_stop(base.nospace(prev)):
            parts.append(prev)
    j = label_idx + 1
    while j < len(lines) and (j - label_idx) <= 3:
        sN = base.nospace(lines[j])
        if not sN or _looks_like_stop(sN):
            break
        cl = base.clean(lines[j])
        if cl:
            parts.append(cl)
        j += 1
    return " ".join(parts).strip()


def parse(lines: list[str]) -> RequestModel:
    full = "\n".join(lines)
    m = RequestModel(bank="기업은행")
    new_address = ""
    addr_label_idx = None

    mo = re.search(r"의뢰번호:\s*([A-Za-z0-9\-]+)", full)
    if mo:
        m.request_no = mo.group(1)

    for idx, ln in enumerate(lines):
        sN = base.nospace(ln)
        if "물건종류" in sN and not m.property_type:
            kind, _ = base.split_two(re.split("물건종류", ln, 1)[-1], "평가사명")
            m.property_type = kind
        if "소 재 지" in ln or sN.startswith("소재지"):
            v = base.clean(re.split(r"소\s*재\s*지", ln, 1)[-1])
            if v and "새주소" not in sN:
                m.addresses.append(v)
            elif not v and "새주소" not in sN and addr_label_idx is None:
                # 라벨만 있고 값이 없는 줄: 앞뒤 줄에서 복원(아래 fallback).
                addr_label_idx = idx
        if sN.startswith("새주소(소재지)"):
            new_address = base.clean(re.split(r"새주소\s*\(소재지\)", ln, 1)[-1])
        if "담당자명" in ln:
            staff, _ = base.split_two(re.split("담당자명", ln, 1)[-1], "의뢰일자")
            m.staff_name = staff
        if "의뢰일자" in ln:
            dt, only = base.parse_datetime(re.split("의뢰일자", ln, 1)[-1])
            m.request_datetime, m.request_date_only = dt, only
        if "영 업 점" in ln or sN.startswith("영업점"):
            part = re.split(r"영\s*업\s*점", ln, 1)[-1]
            branch, _ = base.split_two(part, "대표번호")
            if branch and not branch.endswith(_BRANCH_SUFFIX):
                branch += "지점"
            m.branch = branch
            if _:
                m.branch_phone = _
        if "내선번호" in ln:
            ext, _ = base.split_two(re.split("내선번호", ln, 1)[-1], "휴대폰")
            m.extension = ext
        if "채무자" in ln:
            name, _ = base.split_two(re.split("채무자", ln, 1)[-1], "소유자")
            m.debtor = name
        if "소유자" in ln and "성" not in sN:
            name = base.clean(re.split("소유자", ln, 1)[-1])
            m.owner = name
        if base.nospace(ln).startswith("참고사항"):
            m.remarks = base.clean(re.split("참고사항", ln, 1)[-1])
        if "신축년도" in ln:
            my = re.search(r"신축년도\s+([\d\-.]+)", ln)
            if my:
                m.building_year = my.group(1)
        if "건물구조" in ln and not base.nospace(ln).startswith("건물구조토지"):
            v = base.clean(re.split("건물구조", ln, 1)[-1])
            if v and not v.isdigit():
                m.building_structure = v

    # 같은 줄에서 소재지 값을 못 찾았고 라벨만 있는 줄이 있으면 앞뒤 줄에서 복원한다.
    if not m.addresses and addr_label_idx is not None:
        recovered = _reconstruct_address(lines, addr_label_idx)
        if recovered:
            m.addresses.append(recovered)

    # 지번주소를 우선하되 새주소에만 있는 호수는 상세주소로 보완한다.
    if m.addresses and new_address and not re.search(r"\d+\s*호", m.addresses[0]):
        unit = re.search(r"(?:제)?(\d+)\s*호", new_address)
        if unit:
            m.addresses[0] = f"{m.addresses[0]} {unit.group(1)}호"

    _, m.missing = m.has_required()
    return m


def normalize_custname(m: RequestModel) -> str:
    """'하남' → '기업은행 하남지점'. 이미 점/센터 접미사면 그대로."""
    branch = (m.branch or "").strip()
    if not branch:
        return "기업은행"
    if branch.endswith(_BRANCH_SUFFIX):
        return f"기업은행 {branch}"
    return f"기업은행 {branch}지점"
