# -*- coding: utf-8 -*-
"""주소 구조화 및 RegHist 조회/길이 검증.

- structure_address: PDF 주소 → 행정구역/법정동·리, 산여부, 본번/부번(4자리), 건물·동·호.
- lookup_reghist: 고정 SQL + 바인딩으로 APW_RegHist 조회(이번 작업 미실행, provisional).
- validate_addr_length: varchar(40) 등 길이/인코딩 손실 검증(provisional 상태 표기).

주의: 주소 잔여 문자열을 Building/Dong/Ho/AddrEtc 에 임의로 넣지 않는다.
명확히 식별된 호(N호)·동(X동)·건물명만 채운다.
"""
from __future__ import annotations

import re

from models import StructuredAddress

# 고정 테이블 allowlist (SQL 인젝션 방지; S3)
ALLOWED_REGHIST_TABLES = frozenset({"APW_RegHist"})

_SIDO = ("서울특별시", "서울", "부산광역시", "부산", "대구광역시", "대구",
         "인천광역시", "인천", "광주광역시", "광주", "대전광역시", "대전",
         "울산광역시", "울산", "세종특별자치시", "세종", "경기도", "경기",
         "강원특별자치도", "강원도", "강원", "충청북도", "충북", "충청남도", "충남",
         "전북특별자치도", "전라북도", "전북", "전라남도", "전남",
         "경상북도", "경북", "경상남도", "경남", "제주특별자치도", "제주")

_SIDO_CANONICAL = {
    "서울": "서울특별시", "부산": "부산광역시", "대구": "대구광역시",
    "인천": "인천광역시", "광주": "광주광역시", "대전": "대전광역시",
    "울산": "울산광역시", "세종": "세종특별자치시", "경기": "경기도",
    "강원": "강원특별자치도", "강원도": "강원특별자치도",
    "충북": "충청북도", "충남": "충청남도", "전북": "전북특별자치도",
    "전라북도": "전북특별자치도", "전남": "전라남도", "경북": "경상북도",
    "경남": "경상남도", "제주": "제주특별자치도",
}

# 토큰 시작부의 지번(본번-부번). 외/번지/콤마 등 접미사 허용(prefix 매칭).
_JIBUN_PREFIX_RE = re.compile(r"^(산)?(\d{1,5})(?:\s*-\s*(\d{1,5}))?")
_HO_RE = re.compile(r"(?:제\s*)?(?!제)([가-힣A-Za-z]?\d+(?:-\d+)?)\s*호")
_HO_RANGE_RE = re.compile(r"제?\s*(\d+(?:-\d+)?)\s*호\s*~\s*제?\s*(\d+(?:-\d+)?)\s*호")
_MULTI_ALPHA_HO_RE = re.compile(r"\b([A-Za-z]?\d+(?:-\d+)?)\s*호\b")
_DONG_RE = re.compile(r"^(.+?)동$")
_FLOOR_RE = re.compile(r"제?\s*\d+\s*층")
_DAPILJI_RE = re.compile(r"외\s*\d*\s*필지")


def _pad4(num: str) -> str:
    """본번/부번 4자리 0패딩 문자열. 빈값은 '0000'."""
    n = re.sub(r"\D", "", num or "")
    if not n:
        return "0000"
    return n.zfill(4)[-4:] if len(n) <= 4 else n  # 4자리 초과면 원본 유지(손실 금지)


def structure_address(raw: str) -> StructuredAddress:
    """PDF 주소 문자열을 구조화."""
    sa = StructuredAddress(raw=raw or "")
    s = re.sub(r"\s+", " ", (raw or "").strip())
    if not s:
        return sa
    tokens = s.split()

    # 1) 산/일반 마커 위치 결정
    marker_idx = None
    is_san = False
    for i, t in enumerate(tokens):
        if t == "일반":
            marker_idx = i
            break
        if t == "산" or re.match(r"^산\d", t):
            marker_idx = i
            is_san = True
            break

    if marker_idx is not None:
        admin_tokens = tokens[:marker_idx]
        if tokens[marker_idx] == "산":
            rest = tokens[marker_idx + 1:]
        elif is_san:  # '산286' 형태
            rest = [tokens[marker_idx][1:]] + tokens[marker_idx + 1:]
        else:
            rest = tokens[marker_idx + 1:]
            # 일부 농협 PDF는 지번을 `... 233-4 일반 233-4`처럼 중복 인쇄한다.
            # `일반` 앞뒤의 지번 토큰이 정확히 같을 때만 Addr 후보에서 앞쪽을 제거한다.
            if admin_tokens and rest:
                before = _JIBUN_PREFIX_RE.fullmatch(admin_tokens[-1])
                after = _JIBUN_PREFIX_RE.fullmatch(rest[0])
                if before and after and before.groups() == after.groups():
                    admin_tokens.pop()
    else:
        # 마커 없음: 지번처럼 보이는(숫자 시작) 첫 토큰을 찾는다(외/번지/콤마 허용).
        jibun_pos = None
        for i, t in enumerate(tokens):
            if i == 0:
                continue
            mm = _JIBUN_PREFIX_RE.match(t)
            if mm and mm.group(2):
                jibun_pos = i
                break
        if jibun_pos is None:
            sa.admin_addr = " ".join(tokens)
            sa.san = "1"
            return sa
        admin_tokens = tokens[:jibun_pos]
        rest = tokens[jibun_pos:]

    if admin_tokens:
        admin_tokens[0] = _SIDO_CANONICAL.get(admin_tokens[0], admin_tokens[0])
    sa.admin_addr = " ".join(admin_tokens)
    sa.san = "2" if is_san else "1"

    # 2) 지번 파싱 (prefix 매칭: 접미사 분리)
    if rest:
        first = rest[0]
        mj = _JIBUN_PREFIX_RE.match(first)
        if mj and mj.group(2):
            if mj.group(1) == "산":
                sa.san = "2"
            sa.bun1 = _pad4(mj.group(2))
            sa.bun2 = _pad4(mj.group(3) or "")
            # 토큰의 지번 이후 접미사(외/번지 등)는 잔여로 회수
            suffix = first[mj.end():]
            rest = ([suffix] if suffix else []) + rest[1:]

    # 3) 다필지 여부가 명확하면 AddrEtc
    remainder_text = " ".join(rest)
    if _DAPILJI_RE.search(remainder_text):
        md = _DAPILJI_RE.search(remainder_text)
        sa.addr_etc = md.group(0)

    # 4) 잔여 → 호/동/건물명 (명확할 때만)
    _structure_remainder(sa, rest)
    return sa


def _structure_remainder(sa: StructuredAddress, rest: list[str]) -> None:
    if not rest:
        return
    remainder = " ".join(rest)

    # `617-21,22,23,28`: 첫 지번은 이미 BUN1/BUN2에 있으므로 나머지만
    # 운영 DB의 추가필지 Building 형식으로 보존한다.
    duplicate_base_then_san = re.fullmatch(
        r"\d{1,5}-\d{1,5}\s*,\s*(산\d{1,5}(?:-\d{1,5})?(?:\s*,\s*\d{1,5})+)",
        remainder,
    )
    if duplicate_base_then_san:
        values = re.findall(r"산?\d{1,5}(?:-\d{1,5})?", duplicate_base_then_san.group(1))
        sa.building = ",".join(values)
        return

    repeated_lots = re.fullmatch(
        r"(\d{1,5})-(\d{1,5})((?:\s*,\s*\d{1,5})+)", remainder)
    if repeated_lots and _pad4(repeated_lots.group(1)) == sa.bun1:
        extras = re.findall(r"\d{1,5}", repeated_lots.group(3))
        base_no = str(int(sa.bun1))
        sa.building = ",".join(f"{base_no}-{value}" for value in extras)
        sa.addr_etc = "1"
        return

    # `322, 323, 324번지 건물명`: 운영 DB는 첫 지번을 BUN1로 두고
    # 추가 지번을 Building에 붙여 저장한다.
    multi_lots = re.fullmatch(
        r"\s*,?\s*(\d{1,5}(?:\s*,\s*\d{1,5})+)\s*번지(?:\s+.*)?", remainder)
    if multi_lots:
        values = re.findall(r"\d{1,5}", multi_lots.group(1))
        sa.building = "".join(values)
        sa.addr_etc = "1"
        return

    # `건물명지하2층제비203호`처럼 표 셀 추출이 붙어서 나온 명확한 상세주소.
    compact = re.fullmatch(
        r"(.+?)(지하\d+층|지상\d+층|제?\d+층)(제?([가-힣]?)(\d+)호)", remainder)
    if compact:
        sa.building_nm = compact.group(1).strip()
        floor = compact.group(2)
        unit_prefix = compact.group(4)
        sa.dong = unit_prefix
        sa.ho = compact.group(5)
        unit = f"{unit_prefix}{sa.ho}호"
        sa.building = f"{sa.building_nm} {floor} {unit}".strip()
        return

    san_extra_lots = re.fullmatch(
        r"(산\d{1,5}(?:-\d{1,5})?)(?:\s*,\s*(\d{1,5}))+",
        remainder,
    )
    if san_extra_lots:
        values = re.findall(r"(?:산)?\d{1,5}(?:-\d{1,5})?", remainder)
        sa.building = ",".join(values)
        return

    # `395-17,395-30`처럼 추가필지가 '본번-부번' 전체형으로 콤마로 이어지는 양식
    # (주지번 395-17 은 이미 BUN1/BUN2 로 추출됨 → 잔여는 ',395-30'). 앞(주)본번과 같으면
    # '-부번', 다르면 '본번-부번' 으로 Building 에 보존하고 다필지 플래그를 세운다.
    comma_full_lots = re.fullmatch(
        r"\s*,\s*(\d{1,5}-\d{1,5}(?:\s*,\s*\d{1,5}-\d{1,5})*)\s*", remainder)
    if comma_full_lots:
        main_bon = str(int(sa.bun1)) if sa.bun1 else ""
        parts = []
        for lot in re.split(r"\s*,\s*", comma_full_lots.group(1)):
            bon, bu = lot.split("-", 1)
            if main_bon and str(int(bon)) == main_bon:
                parts.append(f"-{bu}")
            else:
                parts.append(lot)
        sa.building = ",".join(parts)
        sa.addr_etc = "1"
        return

    # `812-20,32,45`처럼 같은 본번의 추가 부번이 쉼표로 이어지는 양식.
    extra_lots = re.fullmatch(r"\s*,?\s*(\d{1,5}(?:\s*,\s*\d{1,5})+)\s*", remainder)
    if extra_lots:
        values = re.findall(r"\d{1,5}", extra_lots.group(1))
        sa.building = ",".join(f"-{value}" for value in values)
        sa.addr_etc = "1"
        return

    # 호
    # `231호, 232호, 233호, 234호`처럼 개별 호가 쉼표로 여러 개 이어지는 형식은
    # 운영 DB의 범위 표기(첫~끝)로 축약하고 다필지/다세대 플래그를 세운다.
    multi_ho = re.search(
        r"(\d{1,5})\s*호\s*,\s*\d{1,5}\s*호(?:\s*,\s*\d{1,5}\s*호)*", remainder)
    range_ho = _HO_RANGE_RE.search(remainder)
    multi_alpha_ho = [
        m.group(1).upper()
        for m in _MULTI_ALPHA_HO_RE.finditer(remainder)
        if m.group(1)
    ]
    if multi_ho:
        nums = [int(n) for n in re.findall(r"(\d{1,5})\s*호", multi_ho.group(0))]
        sa.ho = f"{min(nums)}~{max(nums)}"
        sa.addr_etc = "1"
    elif range_ho:
        sa.ho = f"{range_ho.group(1)}~{range_ho.group(2)}"
    elif len(multi_alpha_ho) >= 2 and any(re.search(r"[A-Z]", v) for v in multi_alpha_ho):
        sa.ho = ",".join(multi_alpha_ho)
    else:
        mho = _HO_RE.search(remainder)
        # 건물명 뒤에 '동 호'가 접미사 없이 공백 숫자 2개로 오는 형식
        # (예: '힐탑트레져 2 502' → 동=2, 호=502). 두 토큰은 맨숫자이고 그 앞은 건물명(숫자만
        # 아닌 토큰)이어야 한다. 표준 'N동 M호'/'M호'로 이미 잡혔으면 이 분기는 타지 않는다.
        two_bare_unit = (
            len(rest) >= 3
            and re.fullmatch(r"\d{1,4}", rest[-2])
            and re.fullmatch(r"\d{2,5}", rest[-1])
            and not re.fullmatch(r"[\d\-,]+", rest[-3])
        )
        if mho:
            sa.ho = mho.group(1)
        elif two_bare_unit:
            sa.dong = rest[-2]
            sa.ho = rest[-1]
        elif len(rest) >= 2 and re.fullmatch(r"\d{2,5}", rest[-1]):
            # 일부 우리은행 주소는 마지막 호수의 `호`가 생략된다.
            if any(re.search(r"아파트|센터|빌딩|타워|프라자|상가|하임|휴", t)
                   for t in rest[:-1]):
                sa.ho = rest[-1]

    floor_label = ""
    mfloor = _FLOOR_RE.search(remainder)
    if mfloor:
        floor_label = re.sub(r"\s+", "", mfloor.group(0))

    # 동 (호 앞의 'X동' 토큰). two_bare_unit 로 이미 동을 잡았으면 유지한다.
    for t in (rest if not sa.dong else ()):
        md = _DONG_RE.match(t)
        if md and "호" not in t:
            # 너무 일반적인 법정동 반복은 배제하기 어려우므로 명확 토큰만:
            # 건물 동은 보통 짧다(예: 제비동, 가동, 101동)
            name = md.group(1)
            name = re.sub(r"^제", "", name)
            if len(name) <= 4:
                sa.dong = name
            break

    # 건물명: 호/동/지번/다필지/콤마 토큰을 제외한 나머지 (한글/영문 포함)
    bld_tokens = []
    for t in rest:
        tc = t.strip(",")
        if not tc:
            continue
        if "호" in tc or _DONG_RE.match(tc):
            continue
        if (tc in ("외", "번지") or re.fullmatch(r"\d*필지", tc)
                or re.fullmatch(r"제?\d+층", tc)):
            continue
        if re.fullmatch(r"[\d\-]+", tc):
            continue
        bld_tokens.append(tc)
    if bld_tokens:
        sa.building_nm = " ".join(bld_tokens)

    # 명확히 식별된 건물명·동·호만 Building 상세로 조립한다.
    explicit = []
    if sa.building_nm:
        explicit.append(sa.building_nm)
    if sa.dong:
        explicit.append(f"{sa.dong}동")
    if floor_label:
        explicit.append(floor_label)
    if sa.ho:
        explicit.append(f"{sa.ho}호")
    if explicit:
        sa.building = " ".join(explicit)


# ───────────────────────────── 길이/인코딩 검증 ─────────────────────────────
def validate_addr_length(value: str, max_len: int = 40, codec: str | None = None) -> dict:
    """Addr 등 varchar 길이/인코딩 손실 검증.

    - codec 미지정: 실제 콜레이션 미확인 → status='provisional', 길이만 검사.
    - codec 지정: 인코딩 후 바이트 길이 및 round-trip 손실 검사.
    조용히 자르지 않는다. 초과/손실이면 ok=False (해당 건 실패 처리 대상).
    """
    v = value or ""
    result = {"ok": True, "status": "provisional" if codec is None else "checked",
              "reason": "", "char_len": len(v), "byte_len": None, "max_len": max_len}

    if codec is None:
        if len(v) > max_len:
            result["ok"] = False
            result["reason"] = f"문자 길이 {len(v)} > {max_len} (provisional)"
        return result

    try:
        encoded = v.encode(codec)
    except UnicodeEncodeError as e:
        result["ok"] = False
        result["reason"] = f"인코딩 불가 문자 ({codec}): pos {e.start}"
        return result
    result["byte_len"] = len(encoded)
    # round-trip 손실/치환 검사
    if encoded.decode(codec, "replace") != v:
        result["ok"] = False
        result["reason"] = f"인코딩 round-trip 손실 ({codec})"
        return result
    if len(encoded) > max_len:
        result["ok"] = False
        result["reason"] = f"바이트 길이 {len(encoded)} > {max_len} ({codec})"
    return result


# ───────────────────────────── RegHist 조회 (미실행) ─────────────────────────────
def lookup_reghist(conn, admin_addr: str, *, table: str = "APW_RegHist") -> dict:
    """행정주소 토큰으로 APW_RegHist 조회 → Reg/Eub 등. 고정 SQL + 바인딩만 사용.

    이번 작업에서는 실제로 호출하지 않는다(DB 미연결). 호출 시에도 table 은 allowlist
    검증을 거친다. 값은 모두 `?` 로 바인딩한다.
    """
    if table not in ALLOWED_REGHIST_TABLES:
        raise ValueError(f"허용되지 않은 RegHist 테이블: {table}")
    empty = {"Reg": "", "Eub": "", "matched": False}
    tokens = [t for t in (admin_addr or "").split() if t]
    if not tokens:
        return empty

    cur = conn.cursor()
    # 고정 SQL: 테이블명은 allowlist 상수, 값은 전부 바인딩.
    sql = (
        "SELECT TOP 5 REG, EUB, NAME, AS1, AS2, AS3, AS4 "
        f"FROM {table} "
        "WHERE FUSE = ? AND AS1 LIKE ? AND AS2 LIKE ?"
    )
    params = ["1", f"{tokens[0]}%", f"{tokens[1] if len(tokens) > 1 else ''}%"]
    cur.execute(sql, params)
    rows = cur.fetchall()
    if not rows:
        return empty
    reg = (rows[0][0] or "").strip()
    eub = (rows[0][1] or "").strip()
    return {"Reg": reg, "Eub": eub, "matched": True}
