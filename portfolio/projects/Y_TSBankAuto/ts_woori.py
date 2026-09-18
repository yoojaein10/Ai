# -*- coding: utf-8 -*-
"""
우리은행 탁상자문의뢰서 PDF 파서 (1차 버전)

입력: PDF 페이지의 "레이아웃 보존" 텍스트 (pdftotext -layout 또는
      fitz words 좌표 재구성 결과). 라벨과 값이 같은 물리 라인에
      [라벨][공백들][값] 형태로 놓이는 구조를 이용한다.
출력: 필드 dict
"""
import re

FIELDS = [
    "은행", "문서종류", "의뢰번호", "자문번호",
    "소속", "채무자", "채무자전화", "의뢰일자",
    "영업점", "담당자명", "영업점전화", "내선번호", "핸드폰번호", "참고사항",
    "일련번호", "물건종류", "동코드", "주소", "새주소",
    "소유자", "소유자전화",
    "토지지목", "토지용도", "토지면적",
    "건물구조", "건물용도", "건물면적", "건축년도",
]

_nospace = lambda x: re.sub(r"\s+", "", x or "")


def _clean(s):
    return re.sub(r"\s+", " ", s).strip() if s else ""


def _split_two(value_part, second_label):
    """value_part 안에 second_label이 있으면 (앞값, 뒷값)으로 분리."""
    if second_label and second_label in value_part:
        a, b = value_part.split(second_label, 1)
        return _clean(a), _clean(b)
    return _clean(value_part), ""


def _date(s):
    m = re.search(r"\d{4}[-.]\d{1,2}[-.]\d{1,2}", s or "")
    return m.group(0) if m else _clean(s)


def parse_woori_ts(text):
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    full = "\n".join(lines)

    r = {k: "" for k in FIELDS}
    r["은행"] = "우리은행"
    r["문서종류"] = "탁상자문의뢰서"
    r["_missing"] = []

    # ---- 헤더 (한 줄: 의뢰기관 / 의뢰번호 / 자문번호) ----
    m = re.search(r"의뢰기관:\s*(\S+)", full)
    if m:
        r["은행"] = m.group(1)
    m = re.search(r"의뢰번호:\s*([A-Za-z0-9\-]+)", full)
    if m:
        r["의뢰번호"] = m.group(1)
    m = re.search(r"자문번호:\s*([0-9\-]+)", full)
    if m:
        r["자문번호"] = m.group(1)

    # 본문을 의뢰내역/물건내역으로 분할
    obj_idx = next((i for i, ln in enumerate(lines) if "물건내역" in ln), len(lines))
    head_lines = lines[:obj_idx]
    obj_lines = lines[obj_idx:]

    # ---- 의뢰내역 ----
    # 소속
    for ln in head_lines:
        if "소속" in _nospace(ln)[:6] or "소   속" in ln:
            v = re.split(r"소\s*속", ln, 1)[-1].strip()
            if v:
                r["소속"] = _clean(v)
                break

    # 채무자 성명 + 전화번호
    for ln in head_lines:
        if "전화번호" in ln and "성" in ln and "명" in ln:
            part = re.split(r"성\s*명", ln, 1)[-1]
            name, phone = _split_two(part, "전화번호")
            r["채무자"] = name
            r["채무자전화"] = phone
            break

    # 의뢰일자
    for ln in head_lines:
        if "의뢰일자" in ln:
            r["의뢰일자"] = _date(re.split("의뢰일자", ln, 1)[-1])
            break

    # 영업점 + 담당자명
    for ln in head_lines:
        if "영업점" in ln:
            part = re.split("영업점", ln, 1)[-1]
            branch, mgr = _split_two(part, "담당자명")
            r["영업점"] = branch
            r["담당자명"] = mgr
            break

    # 영업점 전화번호 (영업점 줄 이후 첫 단독 전화번호 줄)
    seen = False
    for ln in head_lines:
        if "영업점" in ln:
            seen = True
            continue
        if seen and "전화번호" in ln and "성" not in ln and "명" not in ln:
            r["영업점전화"] = _clean(re.split("전화번호", ln, 1)[-1])
            break

    # 내선번호 + 핸드폰번호
    for ln in head_lines:
        if "내선번호" in ln:
            part = re.split("내선번호", ln, 1)[-1]
            ext, hp = _split_two(part, "핸드폰번호")
            r["내선번호"] = ext
            r["핸드폰번호"] = hp
            break

    # 참고사항
    for ln in head_lines:
        if "참고사항" in ln:
            r["참고사항"] = _clean(re.split("참고사항", ln, 1)[-1])
            break

    # ---- 물건내역 ----
    # 일련번호 + 물건종류
    for ln in obj_lines:
        if "일련번호" in ln:
            part = re.split("일련번호", ln, 1)[-1]
            seq, kind = _split_two(part, "물건종류")
            r["일련번호"] = seq
            r["물건종류"] = kind
            break

    # 동코드
    for ln in obj_lines:
        if "동코드" in ln:
            v = re.split("동코드", ln, 1)[-1]
            mm = re.search(r"\d{6,12}", v)
            r["동코드"] = mm.group(0) if mm else _clean(v)
            break

    # 주소 (주 소) - '새주소'/'우편' 제외, 좌측 '물건정보' 등 접두 노이즈 허용
    for ln in obj_lines:
        sN = _nospace(ln)
        if "주소" in sN and "새주소" not in sN and "우편" not in ln and "동코드" not in ln:
            v = re.split(r"주\s*소", ln, 1)[-1].strip()
            if v:
                r["주소"] = _clean(v)
                break

    # 새주소
    for ln in obj_lines:
        if "새주소" in _nospace(ln):
            r["새주소"] = _clean(re.split(r"새\s*주\s*소", ln, 1)[-1])
            break

    # 소유자 성명 + 전화번호
    for ln in obj_lines:
        if "소유자" in ln and "성명" in _nospace(ln):
            part = re.split(r"성\s*명", ln, 1)[-1]
            name, phone = _split_two(part, "전화번호")
            r["소유자"] = name
            r["소유자전화"] = phone
            break

    # 토지: 지목 + 용도
    for ln in obj_lines:
        if "지목" in ln:
            part = re.split("지목", ln, 1)[-1]
            jimok, yongdo = _split_two(part, "용도")
            r["토지지목"] = jimok
            r["토지용도"] = yongdo
            break

    # 토지 면적: '지목' 줄 다음 첫 '면적' (건축년도 줄 제외)
    after_jimok = False
    for ln in obj_lines:
        if "지목" in ln:
            after_jimok = True
            continue
        if after_jimok and "면적" in ln and "건축" not in ln:
            mm = re.search(r"면적\s*([\d,]+)", ln) or re.search(r"([\d,]+)\s*$", ln)
            if mm:
                r["토지면적"] = mm.group(1).replace(",", "")
                break

    # 건물 구조 + 용도 (지목과 별개의 '구조' 줄)
    for ln in obj_lines:
        sN = _nospace(ln)
        if "구조" in sN and "용도" in sN and "지목" not in sN:
            part = re.split("구조", ln, 1)[-1]
            gujo, yongdo = _split_two(part, "용도")
            r["건물구조"] = gujo
            r["건물용도"] = yongdo
            break

    # 건물 면적 + 건축년도
    for ln in obj_lines:
        if "건축년도" in ln:
            ma = re.search(r"면적\s+([\d,]+)", ln)
            if ma:
                r["건물면적"] = ma.group(1).replace(",", "")
            my = re.search(r"건축년도\s+([\d\-\.]+)", ln)
            if my:
                r["건축년도"] = my.group(1)
            break

    for k in ("의뢰번호", "자문번호", "채무자", "주소", "동코드"):
        if not r[k]:
            r["_missing"].append(k)
    return r
