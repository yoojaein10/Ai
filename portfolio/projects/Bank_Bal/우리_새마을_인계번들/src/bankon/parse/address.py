"""의견서 본문에서 **시군구까지 갖춘 소재지**를 찾는다.

화면 `소재지` 칸은 `서울특별시 강남구 수서동` 처럼 시도·시군구·동(리)까지를 받는데,
가진 소스는 죄다 한 토막씩 모자란다:

    의견서 `대상물건 개요` 소재지   `수서동 461-17`      ← 시도·시군구 없음(토지 건)
    명세표 ADDR 계층 조각 병합      `서울특별시 수서동`    ← 중간 시군구가 금액행에 섞여 유실
    apw REG/EUB 법정동코드          `1168011500`        ← 코드→명칭 표가 DB 에 없다

그런데 **`감정평가 개요` 본문**에는 완성된 주소가 그대로 적혀 있다(실측 2683
"서울특별시 강남구 수서동" = 화면값). 그래서 본문에서 행정구역 패턴을 훑어 고른다.

고르는 규칙 — 본문에는 주소가 아닌 것도 걸린다(실측 2516 `인천광역시 강화군 계획관리`
= '계획관리지역'의 앞부분이 '…리'로 끝나 걸림). 그래서 **이미 아는 동·리 이름으로
후보를 거른다**(개요 소재지·명세표에서 온다). 아는 이름이 없을 때만 가장 긴 후보를 쓴다.
"""
from __future__ import annotations

import re

# 주소에서 지번이 시작되는 낱말 — `900`, `815-1`, `산12`, 그리고 홀로 선 `산`(`산 12-3`).
# `산곡동` 처럼 산으로 시작하는 동 이름은 낱말 전체가 `산` 이 아니라서 걸리지 않는다.
_JIBUN_WORD = re.compile(r"^(산\d|\d|산$)")


def split_at_jibun(address: str | None) -> tuple[str | None, str | None]:
    """주소를 **지번 앞 / 지번부터**로 가른다. 지번이 없으면 (전체, 전체)."""
    words = re.split(r"\s+", (address or "").strip())
    words = [w for w in words if w]
    for index, word in enumerate(words):
        if _JIBUN_WORD.match(word):
            return (" ".join(words[:index]) or None, " ".join(words[index:]) or None)
    whole = " ".join(words) or None
    return whole, whole


def dong_part(address: str | None) -> str | None:
    """화면 `소재지` 칸 형태 — **지번 앞까지**(행정구역 + 법정동)만.

        경기도 의왕시 포일동 653 인덕원아이티밸리 씨동  →  경기도 의왕시 포일동
        경기도 이천시 마장면 양촌리 299-8외 19필지      →  경기도 이천시 마장면 양촌리

    `…동/리/가` 를 탐욕 매칭하면 **건물명의 `씨동`·`상가동`까지** 먹는다(실측 국민 28건).
    지번 앞에서 자르는 편이 정확하다 — 지번은 `본번지`/`부번지` 칸에 따로 들어간다.
    """
    return split_at_jibun(address)[0]


def after_jibun(address: str | None) -> str | None:
    """주소에서 **지번부터 뒤로** — 층·호·동 표기가 사는 자리."""
    return split_at_jibun(address)[1]


# 층·호·동 표기 — 여러 곳에서 쓰므로 **여기 한 곳**에만 둔다. 예전엔 매핑·검증도구·공부스캔에
# 각각 복사돼 있어 한 곳만 고쳐지고 나머지는 옛 규칙으로 남았다.
_FLOOR = re.compile(r"제\s*(\d+)\s*층")
# 호번호는 **가장 가까운 `제` 부터** 읽는다. 층/동과 호 사이에 공백이 없는 표기
# (`제4층제402호`)에서 앞의 `제` 부터 먹으면 `4층제402` 가 된다 — 실측 2345.
_HO = re.compile(r"제\s*([0-9A-Za-z가-힣][^제\s]*?)\s*호")
# 건물 동은 **`제…동` 표기일 때만** 잡는다. 안 그러면 소재지의 행정동('망월동')을
# 건물 동으로 오인한다(실측 2524 `제101동` = 화면 101).
# 이름이 `_DONG`(행정동 패턴)과 겹치지 않게 `_UNIT_DONG` 이다.
_UNIT_DONG = re.compile(r"제\s*([0-9A-Za-z가-힣]{1,6})\s*동(?![가-힣])")


def floor_of(text: str | None) -> str | None:
    found = _FLOOR.search(text or "")
    return found.group(1) if found else None


def ho_of(text: str | None) -> str | None:
    found = _HO.search(text or "")
    return found.group(1) if found else None


def dong_of(text: str | None) -> str | None:
    """건물 동 — `제101동` → `101`. 행정동(`망월동`)은 잡지 않는다."""
    found = _UNIT_DONG.search(text or "")
    return found.group(1) if found else None

# 광역자치단체 — 주소의 시작점.
_SIDO = (
    "서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시",
    "울산광역시", "세종특별자치시", "경기도", "강원특별자치도", "강원도", "충청북도",
    "충청남도", "전북특별자치도", "전라북도", "전라남도", "경상북도", "경상남도",
    "제주특별자치도",
)

# 시도 + (시·군·구)* + (읍·면·동·리·가)+ — 마지막 토막이 동/리다.
_FULL = re.compile(
    r"(?:" + "|".join(_SIDO) + r")"
    r"(?:\s+[가-힣]+[시군구])*"
    r"(?:\s+[가-힣0-9]+[읍면동리가])+"
)

# 개요 소재지에서 동·리 이름만 떼기: `수서동 461-17` → `수서동`, `양촌리 299-8외` → `양촌리`
_DONG = re.compile(r"([가-힣0-9]+[읍면동리가])(?=\s|$|\d)")


# 건물명은 소재지 뒤에 따옴표로 붙는다. 문서마다 따옴표 짝이 어긋나 있어(실측 2526 은
# 여는 게 `"` 인데 닫는 게 `“`) 종류를 가리지 않고 받는다.
_QUOTES = "\"'“”‘’＂"
_QUOTED = re.compile(f"[{_QUOTES}]([^{_QUOTES}]{{1,40}})[{_QUOTES}]")


def building_name(address: str | None) -> str | None:
    """개요 소재지에 따옴표로 붙은 건물명.

        서울특별시 성동구 성수동1가 656-1110외 12필지 "서울숲엘타워“   → 서울숲엘타워
        서울특별시 서초구 서초동 1316-5 "부띠크 모나코"                → 부띠크 모나코
        서울특별시 구로구 구로동 222-31번지 "지플러스타워"              → 지플러스타워

    구분건물 명세표(section_build) 표제부에도 건물명이 들어 있지만 워드랩으로 잘려
    있어(`서울숲`+`엘타워`) 띄어쓰기를 복원할 수 없다. 따옴표 쪽이 원문 그대로다.
    토지 건은 따옴표가 없어 None — 화면 건물명 칸도 비어 있다.
    """
    match = _QUOTED.search(address or "")
    if not match:
        return None
    name = match.group(1).strip()
    return name or None


def dong_names(*texts: str | None) -> tuple[str, ...]:
    """짧은 주소들에서 동·리 이름 후보를 뽑는다(뒤에 나온 것일수록 하위 행정구역)."""
    found: list[str] = []
    for text in texts:
        for match in _DONG.finditer(text or ""):
            name = match.group(1)
            if name not in found:
                found.append(name)
    return tuple(found)


def candidates(*texts: str | None) -> tuple[str, ...]:
    """주어진 글에서 완전주소 후보를 모은다(등장 순서, 중복 제거).

    의견서 본문뿐 아니라 명세표 계층주소도 그대로 넣는다 — 명세표가 온전하면
    (`경기도 성남시 수정구 시흥동`) 그게 가장 확실한 후보다.
    """
    found: list[str] = []
    for text in texts:
        for match in _FULL.finditer(text or ""):
            cleaned = re.sub(r"\s+", " ", match.group(0)).strip()
            if cleaned not in found:
                found.append(cleaned)
    return tuple(found)


_DISTRICT = re.compile(r"^((?:" + "|".join(_SIDO) + r")(?:\s+[가-힣]+[시군구])+)")


def _compose(candidate: str, dong: str) -> str | None:
    """후보에서 **시도·시군구만** 떼어 아는 동·리를 붙인다.

    본문에 대상물건 주소가 통째로 안 나오고 비교사례 주소만 나오는 건이 있다(실측
    2561: 대상은 마포구 서교동인데 본문 완전주소는 사례지인 합정동뿐). 사례는 같은
    시군구에서 고르므로 **시군구까지만 빌리고 동은 우리가 아는 값**을 쓴다.
    """
    match = _DISTRICT.match(candidate)
    return f"{match.group(1)} {dong}" if match else None


def full_address(body: str | None, *hints: str | None) -> str | None:
    """완전주소 하나를 고른다. `hints` = 이미 아는 주소(개요 소재지·명세 계층주소).

    힌트는 두 몫을 한다 — 어느 동·리가 대상인지 알려 주고(오검출 차단), 자기 자신이
    완전주소면 후보도 된다.

        >>> full_address("… 서울특별시 강남구 수서동 소재 …", "수서동 461-17")
        '서울특별시 강남구 수서동'
    """
    found = candidates(body, *hints)
    if not found:
        return None
    names = dong_names(*hints)
    for name in names:
        # 아는 동·리로 끝나는 후보 중 가장 상세한 것(= 가장 긴 것).
        matched = [text for text in found if text.endswith(name)]
        if matched:
            return max(matched, key=len)
    if names:                                   # 대상 주소가 본문에 통째로 없는 건
        composed = _compose(max(found, key=len), names[0])
        if composed:
            return composed
    return max(found, key=len)
