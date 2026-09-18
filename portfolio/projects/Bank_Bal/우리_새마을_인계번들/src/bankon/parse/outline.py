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
# `8/12/2026` — gamexport(Delphi)가 **시스템 로캘**의 짧은 날짜로 찍는다. 원본 PC 는
# ISO 로 나왔지만 로캘이 다른 PC 에서 추출하면 이 꼴이 된다(실측 2526: 캐시=2026-08-12,
# 이 PC 재추출=8/12/2026). 정규화하지 않으면 날짜 칸에 이 문자열이 그대로 입력된다.
_SLASH_DATE = re.compile(r"\b(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{4})\b")
# `지하1층 / 지상 6층`, `지하 1층\n지상 5층`, `23` 등
_BASEMENT = re.compile(r"지하\s*(\d+)")
_GROUND = re.compile(r"지상\s*(\d+)")
_PACKED_DATE = re.compile(r"(\d{8})")
_NUMBER = re.compile(r"-?[\d,]+(?:\.\d+)?")
# 토지 특성표(감정평가 개요): `…이용상황</td><td>도로교통</td><td>형상\n지세</td>…` 데이터행에
# `광대세각</td><td>세장형\n평  지</td>`. 도로 어휘로 앵커 잡아 그 다음 칸을 형상+지세로 가른다.
_ROAD_ANCHOR = re.compile(
    r"<td>\s*(광대[가-힣]*|중로[가-힣]*|소로[가-힣]*|세로\([가불]\)|세각\([가불]\)|맹지)\s*</td>"
    r"\s*<td>([^<]*)</td>")
_ROADS = frozenset({"광대한면", "광대소각", "광대세각", "중로한면", "중로각지", "소로한면",
                    "소로각지", "세로(가)", "세각(가)", "세로(불)", "세각(불)", "맹지"})
_SHAPES = frozenset({"정방형", "가장형", "세장형", "사다리형", "삼각형", "역삼각",
                     "부정형", "자루형"})
_SLOPES = frozenset({"저지", "평지", "완경사", "급경사", "고지"})


def _land_features(section_body: str) -> tuple[str | None, str | None, str | None]:
    """토지 특성표에서 (도로, 형상, 지세). 없으면 None."""
    m = _ROAD_ANCHOR.search(section_body or "")
    if not m:
        return (None, None, None)
    road = m.group(1).strip()
    parts = [p.strip() for p in re.split(r"[\n\r]+", m.group(2)) if p.strip()]
    shape = parts[0] if parts else None
    slope = re.sub(r"\s+", "", parts[1]) if len(parts) > 1 else None
    return (road if road in _ROADS else None,
            shape if shape in _SHAPES else None,
            slope if slope in _SLOPES else None)


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
    road: str | None = None            # 도로교통(광대세각…) — 토지 특성표
    shape: str | None = None           # 형상(세장형…)
    slope: str | None = None           # 지세(평지…)

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


def _from_slash(text: str) -> str | None:
    """`8/12/2026` → `2026-08-12`.

    Delphi 기본 짧은 날짜는 **월/일/연** 이다. 앞자리가 12를 넘으면 그건 월일 수 없으니
    일/월로 읽는다(로캘이 유럽식인 PC 대비). 둘 다 12 이하면 월/일로 본다.
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


def parse(section_body: str | None) -> Outline:
    """`대상물건 개요` 본문(표 포함)에서 값을 뽑는다."""
    if not section_body:
        return Outline()

    raw = {
        key: lookup_all(section_body, labels, _ALL_LABELS - {normalize_label(l) for l in labels})
        for key, labels in LABELS.items()
    }
    road, shape, slope = _land_features(section_body)
    return Outline(
        **{key: raw[key] for key in _TEXT_FIELDS},
        floors_text=raw["floors"],
        approval_date=to_iso_date(raw["approval_date"]),
        **{key: to_decimal(raw[key]) for key in _DECIMAL_FIELDS},
        unit_count=to_int(raw["unit_count"]),
        road=road, shape=shape, slope=slope,
    )
