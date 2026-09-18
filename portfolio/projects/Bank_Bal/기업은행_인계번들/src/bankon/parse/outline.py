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
# `지하1층 / 지상 6층`, `지하 1층\n지상 5층`, `23` 등
_BASEMENT = re.compile(r"지하\s*(\d+)")
_GROUND = re.compile(r"지상\s*(\d+)")
_PACKED_DATE = re.compile(r"(\d{8})")
_NUMBER = re.compile(r"-?[\d,]+(?:\.\d+)?")


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


def to_iso_date(text: str | None) -> str | None:
    """`2024.01.26` / `2018-12-26` / `2007년 9월 18일` / `20230502` → ISO."""
    if not text:
        return None
    match = _DATE.search(text)
    if not match:
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
    return Outline(
        **{key: raw[key] for key in _TEXT_FIELDS},
        floors_text=raw["floors"],
        approval_date=to_iso_date(raw["approval_date"]),
        **{key: to_decimal(raw[key]) for key in _DECIMAL_FIELDS},
        unit_count=to_int(raw["unit_count"]),
    )
