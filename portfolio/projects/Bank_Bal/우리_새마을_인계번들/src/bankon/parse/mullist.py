"""`.gam` 의 `mullist*` 테이블 파싱 — 신한은행 담보 전용.

`mullist` 는 제출처=신한은행 + 목적=제1금융권담보 건에만 존재한다(신한 건의 68%).
컬럼이 뱅크온라인 신한 폼과 거의 1:1 이라 사실상 전송용 테이블이다.

실측 일치율(신한 표본 120건, 콤보 목록과 직접 대조):
    MUL_GUBUN     → 담보세부종류      100%
    YG_AREA       → 용도지역구분(신)   100%
    DABO_JONG_SUB → 담보종류          92%
    JI_YOUNGDO    → 건물구조(신)/지목  98% (MUL_GUBUN 으로 분기)

`mullist` 가 없는 32% 는 담보종류·담보용도를 **비워둔다**(사용자 결정) — 근거가
약한 값을 채워 넣는 것보다 사람이 고르게 두는 편이 안전하다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .outline import to_iso_date

# 테이블명 = 'mullist' + 바인더번호(가변 자릿수): mullist0, mullist00, mullist1008 ...
_TABLE_NAME = re.compile(r"^mullist\d+$", re.IGNORECASE)

# 명세행 판별용 신호 컬럼. 하나라도 채워져 있어야 진짜 물건 행이다
# (빈 행·서식 행이 섞여 있어 GUBUN 만으로는 구분되지 않는다 — land_list 와 같은 문제).
_ROW_SIGNALS = ("NO", "DABO_JONG_SUB", "ADDR_NEW", "P_PRICE")


@dataclass(frozen=True)
class MullistRow:
    """뱅크온라인 신한 폼 한 물건(일련번호 하나)에 대응하는 행."""

    seq_no: str | None          # NO        → 물건순번
    mark: str | None            # SNO       → 기호(가·나·다)
    collateral_group: str | None    # DABO_JONG     (내부 분류, 폼에는 안 씀)
    collateral_kind: str | None     # DABO_JONG_SUB → 담보종류
    object_kind: str | None         # MUL_GUBUN     → 담보세부종류(토지/건물/기계기구)
    struct_or_category: str | None  # JI_YOUNGDO    → 건물구조(신) 또는 지목
    zone: str | None            # YG_AREA   → 용도지역구분(신)
    address: str | None         # ADDR_NEW  → 소재지
    area_public: Decimal | None     # GONG_AREA → 공부면적(수량)
    area_assessed: Decimal | None   # SA_AREA   → 사정면적
    amount: Decimal | None      # P_PRICE   → 감정평가액
    registry_no: str | None     # DUNG_NO   → 등기부번호
    ledger_no: str | None       # DAE_NO    → 대장번호
    useful_years: int | None    # DB_YEAR   → 내용연수
    remaining_years: int | None  # SUR_YEAR → 잔존연수
    approval_date: str | None   # USE_APP_DATE → 사용승인일

    @property
    def is_land(self) -> bool:
        return (self.object_kind or "").strip() == "토지"

    @property
    def is_building(self) -> bool:
        return (self.object_kind or "").strip() == "건물"


def _text(row: dict, key: str) -> str | None:
    value = row.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _decimal(row: dict, key: str) -> Decimal | None:
    text = _text(row, key)
    if text is None:
        return None
    try:
        return Decimal(text.replace(",", ""))
    except InvalidOperation:
        return None


def _int(row: dict, key: str) -> int | None:
    value = _decimal(row, key)
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, OverflowError):
        return None


def _is_detail_row(row: dict) -> bool:
    return any(_text(row, key) for key in _ROW_SIGNALS)


def parse_row(row: dict) -> MullistRow:
    return MullistRow(
        seq_no=_text(row, "NO"),
        mark=_text(row, "SNO"),
        collateral_group=_text(row, "DABO_JONG"),
        collateral_kind=_text(row, "DABO_JONG_SUB"),
        object_kind=_text(row, "MUL_GUBUN"),
        struct_or_category=_text(row, "JI_YOUNGDO"),
        zone=_text(row, "YG_AREA"),
        address=_text(row, "ADDR_NEW"),
        area_public=_decimal(row, "GONG_AREA"),
        area_assessed=_decimal(row, "SA_AREA"),
        amount=_decimal(row, "P_PRICE"),
        registry_no=_text(row, "DUNG_NO"),
        ledger_no=_text(row, "DAE_NO"),
        useful_years=_int(row, "DB_YEAR"),
        remaining_years=_int(row, "SUR_YEAR"),
        # 표기가 `2018.02.14` / `20230502` 로 섞여 있어 ISO 로 맞춘다.
        approval_date=to_iso_date(_text(row, "USE_APP_DATE")),
    )


def find_tables(tables: dict[str, list]) -> tuple[str, ...]:
    """gamexport 산출 테이블 중 mullist 계열 이름을 (정렬해) 돌려준다."""
    return tuple(sorted(name for name in tables if _TABLE_NAME.match(name)))


def parse(tables: dict[str, list]) -> tuple[MullistRow, ...]:
    """`.gam` 테이블 묶음에서 mullist 물건 행을 뽑는다.

    mullist 가 없으면 빈 튜플 — 호출측은 이때 담보종류·담보용도를 비워둔다.
    """
    rows: list[MullistRow] = []
    for name in find_tables(tables):
        for raw in tables.get(name) or ():
            if isinstance(raw, dict) and _is_detail_row(raw):
                rows.append(parse_row(raw))
    return tuple(rows)
