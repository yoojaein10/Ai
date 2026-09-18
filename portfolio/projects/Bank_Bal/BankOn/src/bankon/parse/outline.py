"""의견서 `대상물건 개요` 표 → 물건 기본정보.

표 구조가 평가목적·물건종류마다 완전히 다르다(토지형/구분건물형/공장형…).
그래서 라벨을 찾아 오른쪽 값을 읽는다. 라벨 표기도 흔들려서 후보를 여러 개 둔다.

담보 495건 실측 출현율:
    소재지 97% · 사용승인일자 85% · 용도지역 52% · 이용상황 52% · 형상 50%
    층수 49% · 건물의 구조 47% · 전유면적 47% · 대지권면적 45% · 연면적 36%
(50%대가 낮아 보이는 건 파서 문제가 아니라 **토지가 포함된 건에만 나오는 항목**이라서다.)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .tables import lookup_all, normalize_label

LABELS: dict[str, tuple[str, ...]] = {
    "address": ("소재지", "소 재 지"),
    "road_address": ("도로명주소",),
    "zone": ("용도지역", "용도지역지구"),
    "usage": ("이용상황",),
    "category": ("지목", "지 목"),
    "building_use": ("주용도", "건물용도", "용도", "용 도"),
    "struct": ("건물의 구조", "건물구조", "구조", "구조/지붕"),
    "floors": ("층수", "층 수", "층", "건물의 규모", "규모"),
    # 구분건물 의견서는 '층수' 와 별도로 '건물의 규모' 행에 총 호/세대 수가 온다(2788 '102호').
    # floors 후보로도 남겨 둔다 — 층수 행이 없고 규모에 '지하2층 / 지상28층' 만 있는 건(DW 177건)이 있어서.
    "scale": ("건물의 규모", "규모"),
    "approval_date": ("사용승인일자", "사용승인일", "사용승인"),
    "area_exclusive": ("전유면적", "전유면적(㎡)"),
    "area_common": ("공용면적",),
    "area_supply": ("공급면적",),
    "area_land_right": ("대지권면적", "대지지분"),
    "area_total": ("연면적",),
    "area_land": ("토지면적",),
    "unit_count": ("세대수", "총세대수"),
    "public_price": ("개별공시지가", "개별공시지가(원/㎡)"),
}

# `2024.01.26` / `2018-12-26` / `2007.09.18` 등 → ISO
_DATE = re.compile(r"(\d{4})\s*[.\-년]\s*(\d{1,2})\s*[.\-월]\s*(\d{1,2})")
# `지하1층 / 지상 6층`, `지하 1층\n지상 5층`, `23` 등
_BASEMENT = re.compile(r"지하\s*(\d+)")
_GROUND = re.compile(r"지상\s*(\d+)")
_PACKED_DATE = re.compile(r"\b(\d{8})\b")   # r-문자열 필수: 전엔 \b 가 백스페이스로 들어가 8자리 날짜가 전부 None 이었다(2026-08-25)
_SLASH_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")   # gamexport 가 추출 PC 로캘로 찍은 `8/12/2026`(농협 인계본 표본 실측)
_NUMBER =re.compile(r"-?[\d,]+(?:\.\d+)?")
# '건물의 규모' 값 → 총세대수. DW gam_opinion 9,451건 분포(2026-09-09, reports/scale_values_20260909.json):
#   'N호' 계열 4,202 · 'N세대/가구' 3,303 · 'N호 / N세대' 병기 1,480 · 층수만 177 · '-'/'보통' 137 · 숫자만 65 · 기타 87
_SCALE_HOUSEHOLD = re.compile(r"(\d[\d,]*)\s*(?:세대|가구)")
_SCALE_UNIT = re.compile(r"(\d[\d,]*)\s*(?:개\s*)?(?:호실|호수|객실|호|실)")   # '25개호' · '총66개 호실' 도
_SCALE_BARE = re.compile(r"\s*(\d{1,3}(?:,\d{3})*|\d{1,5})\s*")
_PAREN = re.compile(r"\([^()]*\)")


@dataclass(frozen=True)
class Outline:
    """`대상물건 개요` 에서 읽어낸 값. 없는 항목은 None."""

    address: str | None = None
    road_address: str | None = None
    zone: str | None = None
    usage: str | None = None
    category: str | None = None
    building_use: str | None = None
    struct: str | None = None
    floors_text: str | None = None
    approval_date: str | None = None
    area_exclusive: Decimal | None = None
    area_common: Decimal | None = None
    area_supply: Decimal | None = None
    area_land_right: Decimal | None = None
    area_total: Decimal | None = None
    area_land: Decimal | None = None
    unit_count: int | None = None
    public_price: Decimal | None = None
    scale_text: str | None = None      # '건물의 규모' 원문('102호', '8세대', '1호 / 8세대', '지하2층 / 지상28층')
    road: str | None = None            # 도로교통(광대세각…) — 토지 특성표(새마을 도로상태 콤보, 인계본 이식 2026-09-10)
    shape: str | None = None           # 형상(세장형…)
    slope: str | None = None           # 지세(평지…)

    @property
    def total_units(self) -> int | None:
        """총세대수 — '건물의 규모' 에서 파생(total_units_from_scale). 없으면 '세대수' 라벨(unit_count)."""
        derived = total_units_from_scale(self.scale_text)
        return derived if derived is not None else self.unit_count

    @property
    def ground_floors(self) -> int | None:
        """총층수 — `지하1층 / 지상 6층` 에서 지상 층수."""
        return _pick_floor(self.floors_text, _GROUND)

    @property
    def basement_floors(self) -> int | None:
        return _pick_floor(self.floors_text, _BASEMENT)


def _pick_floor(text: str | None, pattern: re.Pattern[str]) -> int | None:
    if not text:
        return None
    match = pattern.search(text)
    if match:
        return int(match.group(1))
    # `23` 처럼 숫자만 있으면 지상 층수로 본다.
    if pattern is _GROUND:
        bare = re.fullmatch(r"\s*(\d{1,3})\s*(?:층)?\s*", text)
        if bare:
            return int(bare.group(1))
    return None


def total_units_from_scale(text: str | None) -> int | None:
    """'건물의 규모' 원문 → 총세대수(정수). 못 읽으면 None.

    - '8세대' / '12가구' → 8 / 12. 'N호' / 'N개호' / '총 938호수' / '35객실' → N.
    - 호·세대 병기('1호 / 8세대', '근린생활시설 44호 / 아파트 212세대') → **세대 우선**(2026-09-09 결정):
      호는 상가 몫, 세대가 건물 전체 규모라서.
    - 괄호 부기는 단지 전체라 뗀다: '79세대 (총 35개동, 3,391세대)' → 79.
    - 숫자만('148', '3,458') → 그 수. '0' 은 None.
    - 층수만('지하2층 / 지상28층') · '-' · '보통' · 날짜 등은 None(수기).
    """
    if not text:
        return None
    flat = _PAREN.sub("", text).strip()
    match = _SCALE_HOUSEHOLD.search(flat) or _SCALE_UNIT.search(flat)
    if match:
        return _positive(match.group(1))
    bare = _SCALE_BARE.fullmatch(flat)
    return _positive(bare.group(1)) if bare else None


def _positive(digits: str) -> int | None:
    value = int(digits.replace(",", ""))
    return value if value > 0 else None


def _from_slash(text: str) -> str | None:
    """`8/12/2026` → `2026-08-12`.

    Delphi 기본 짧은 날짜는 **월/일/연** 이다. 앞자리가 12를 넘으면 그건 월일 수 없으니
    일/월로 읽는다(로캘이 유럽식인 PC 대비). 둘 다 12 이하면 월/일로 본다(인계본 규칙, 2026-09-07 이식).
    """
    match = _SLASH_DATE.search(text)
    if not match:
        return None
    first, second, year = (int(g) for g in match.groups())
    month, day = (second, first) if first > 12 else (first, second)
    if not (1900 <= year <= 2200 and 1 <= month <= 12 and 1 <= day <= 31):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def to_iso_date(text: str | None) -> str | None:
    """`2024.01.26` / `2018-12-26` / `2007년 9월 18일` / `20230502` / `8/12/2026` → ISO."""
    if not text:
        return None
    match = _DATE.search(text)
    if not match:
        slashed = _from_slash(text)
        if slashed:
            return slashed
        # 구분자 없는 8자리(mullist USE_APP_DATE 에 섞여 있다).
        packed = _PACKED_DATE.search(text)
        if not packed:
            return None
        digits = packed.group(1)
        year, month, day = int(digits[:4]), int(digits[4:6]), int(digits[6:])
        if not (1900 <= year <= 2200 and 1 <= month <= 12 and 1 <= day <= 31):
            return None
        return f"{year:04d}-{month:02d}-{day:02d}"
    year, month, day = (int(g) for g in match.groups())
    if not (1900 <= year <= 2200 and 1 <= month <= 12 and 1 <= day <= 31):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def to_decimal(text: str | None) -> Decimal | None:
    if not text:
        return None
    match = _NUMBER.search(text)
    if not match:
        return None
    try:
        return Decimal(match.group(0).replace(",", ""))
    except InvalidOperation:
        return None


def to_int(text: str | None) -> int | None:
    value = to_decimal(text)
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, OverflowError):
        return None


_DECIMAL_FIELDS = (
    "area_exclusive", "area_common", "area_supply",
    "area_land_right", "area_total", "area_land", "public_price",
)
_TEXT_FIELDS = ("address", "road_address", "zone", "usage", "category",
                "building_use", "struct")

# 격자형 표(머리행+데이터행)에서 옆 칸 **머리글**을 값으로 집지 않도록 회피 목록을 둔다.
# 우리가 쓰는 라벨 전부 + 같은 머리행에 흔히 같이 오는 다른 컬럼명.
OTHER_HEADERS: tuple[str, ...] = (
    "기호", "기 호", "지번", "지 번", "면적", "면 적", "번호", "구분", "구 분",
    "도로교통", "형상지세", "형상", "지세", "비고", "비 고", "전용률",
    "대장번호", "등기번호", "호수", "호 수", "동", "층별용도", "단가", "금액",
    "소유자", "명칭", "수량", "단위",
)
_ALL_LABELS = frozenset(
    normalize_label(label)
    for label in (*(l for labels in LABELS.values() for l in labels), *OTHER_HEADERS)
)


# 토지 특성표(감정평가 개요): `…이용상황</td><td>도로교통</td><td>형상\n지세</td>…` 데이터행에
# `광대세각</td><td>세장형\n평  지</td>`. 도로 어휘로 앵커 잡아 그 다음 칸을 형상+지세로 가른다
# (새마을 도로상태·형상·지세 콤보 출처, 인계본 D:\AI\BankOn 2026-09-08 → 이식 2026-09-10).
_ROAD_ANCHOR = re.compile(
    r"<td>\s*(광대[가-힣]*|중로[가-힣]*|소로[가-힣]*|세로\([가불]\)|세각\([가불]\)|맹지)\s*</td>"
    r"\s*<td>([^<]*)</td>")
ROADS = frozenset({"광대한면", "광대소각", "광대세각", "중로한면", "중로각지", "소로한면",
                   "소로각지", "세로(가)", "세각(가)", "세로(불)", "세각(불)", "맹지"})
SHAPES = frozenset({"정방형", "가장형", "세장형", "사다리형", "삼각형", "역삼각",
                    "부정형", "자루형"})
SLOPES = frozenset({"저지", "평지", "완경사", "급경사", "고지"})


# 형상·지세 칸 표기는 문서마다 다르다(로컬 추출본 622건 실측 2026-09-15): '사다리\n평지'(축약, 2847 형상 빈칸 제보)·
# '사다리형/'(슬래시)·'사다리 평지'(한 줄)·'사다리형평  지'(붙음)·'세로장방형'·'완경사지'. 공백·슬래시를 걷고
# 앞에서부터 형상 → 나머지에서 지세를 찾아 콤보 이름으로 맞춘다. 순서가 중요하다(역삼각 먼저, 삼각형 뒤).
_SHAPE_WORDS: tuple[tuple[str, str], ...] = (
    ("정방형", "정방형"), ("가로장방형", "가장형"), ("가장형", "가장형"),
    ("세로장방형", "세장형"), ("세장형", "세장형"), ("사다리형", "사다리형"), ("사다리", "사다리형"),
    ("역삼각형", "역삼각"), ("역삼각", "역삼각"), ("삼각형", "삼각형"),
    ("부정형", "부정형"), ("자루형", "자루형"),
)
_SLOPE_WORDS: tuple[tuple[str, str], ...] = (
    ("완경사", "완경사"), ("급경사", "급경사"), ("평지", "평지"), ("저지", "저지"), ("고지", "고지"),
)


def _shape_slope(cell: str) -> tuple[str | None, str | None]:
    """형상·지세 칸 원문 → (형상, 지세) 콤보 이름. 못 알아보는 자리는 None."""
    flat = re.sub(r"[\s/]+", "", cell or "")
    shape = None
    for word, name in _SHAPE_WORDS:
        at = flat.find(word)
        if at == 0:                              # 형상은 칸 맨 앞에 온다
            shape, flat = name, flat[len(word):]
            break
    slope = next((name for word, name in _SLOPE_WORDS if flat.startswith(word)), None)
    if slope is None and shape is None:          # 형상을 못 읽었어도 끝에 붙은 지세는 살린다('-\n평지')
        slope = next((name for word, name in _SLOPE_WORDS
                      if flat.endswith(word) or flat.endswith(word + "지")), None)
    return (shape, slope)


def land_features(section_body: str | None) -> tuple[str | None, str | None, str | None]:
    """토지 특성표에서 (도로, 형상, 지세). 없거나 콤보 어휘 밖이면 그 자리는 None."""
    m = _ROAD_ANCHOR.search(section_body or "")
    if not m:
        return (None, None, None)
    road = m.group(1).strip()
    shape, slope = _shape_slope(m.group(2))
    return (road if road in ROADS else None,
            shape if shape in SHAPES else None,
            slope if slope in SLOPES else None)


def parse(section_body: str | None) -> Outline:
    """`대상물건 개요` 본문(표 포함)에서 값을 뽑는다."""
    if not section_body:
        return Outline()

    raw = {
        key: lookup_all(section_body, labels, _ALL_LABELS - {normalize_label(l) for l in labels})
        for key, labels in LABELS.items()
    }
    road, shape, slope = land_features(section_body)
    return Outline(
        **{key: raw[key] for key in _TEXT_FIELDS},
        floors_text=raw["floors"],
        approval_date=to_iso_date(raw["approval_date"]),
        **{key: to_decimal(raw[key]) for key in _DECIMAL_FIELDS},
        unit_count=to_int(raw["unit_count"]),
        scale_text=raw["scale"],
        road=road, shape=shape, slope=slope,
    )


# 구분건물 의견서는 개요에 용도지역이 없고 '감정평가액 결정' 섹션의 '도시계획 및 기타 공법관계' 셀에 문장으로 온다
# (2719 '기호(1, 2) 공히 도시지역, 준공업지역, 지구단위계획구역, …' / 2682 '제2종일반주거지역(제2종일반주거지역(남동구)), 가축사육제한구역…').
LEGAL_LABELS: tuple[str, ...] = ("도시계획 및 기타 공법관계", "도시계획및기타공법관계", "기타 공법관계", "공법관계")
_ZONE_WORD = re.compile(
    r"(제\s*[0-9０-９]\s*종)?\s*(전용|일반|준|근린|유통|중심|보전|생산|계획|자연)?\s*"
    r"(주거|상업|공업|녹지|관리|농림|자연환경보전)\s*지역")


def parse_legal(section_body: str | None) -> str | None:
    """'도시계획 및 기타 공법관계' 셀 원문(없으면 None)."""
    if not section_body:
        return None
    return lookup_all(section_body, LEGAL_LABELS, _ALL_LABELS)


def zone_from_text(text: str | None) -> str | None:
    """문장에서 첫 용도지역('준공업지역', '제2종일반주거지역')만 뽑는다. 괄호 부기·공백 제거."""
    if not text:
        return None
    flat = re.sub(r"\([^()]*\)", "", text)          # '제2종일반주거지역(…(남동구))' 의 안쪽 괄호부터 두 번 벗긴다
    flat = re.sub(r"\([^()]*\)", "", flat)
    m = _ZONE_WORD.search(flat)
    return re.sub(r"\s+", "", m.group(0)) if m else None
