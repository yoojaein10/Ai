"""신한은행 담보(`TBNKSHG24DAMB`) 필드 매핑.

화면 항목명은 `recon/fields_shinhan_damb.md`, 콤보 선택지는 `recon/combo_shinhan.md`
에서 실제 화면을 읽어 수집한 것이다. 화면이 바뀌면 이 파일만 고친다.

물건 1건 = 화면의 `물건순번` 1개. mullist 행 하나가 물건 하나에 대응한다.
mullist 가 없으면(신한 건의 32%) 담보종류·담보용도를 비워둔다 — 사용자 결정.
"""
from __future__ import annotations

import re
from decimal import ROUND_DOWN, Decimal

from ..codes import shinhan as codes
from ..model import DocumentContext
from ..parse.characteristics import LEASE_UNKNOWN
from ..parse.cost import representative
from ..parse.mullist import MullistRow

# 표가 없을 때 쓰는 기본값(사용자 확정).
DEFAULT_CHARACTERISTIC = "아니오"
DEFAULT_LEASE = LEASE_UNKNOWN
CHECKLIST_ANSWER = "1"          # 신한 점검항목 13개는 전부 1(=예)

# 점검항목은 라벨이 길고 화면마다 문구가 조금씩 달라 라벨로 못 찾는다.
# 드라이버가 `TcxComboBox`(비 DB 바인딩) 컨트롤을 순서대로 채우게 한다.
CHECKLIST_CONTROL_CLASS = "TcxComboBox"

_CHARACTERISTIC_FIELDS = (
    ("매매/분양", "sale"),
    ("튼상가", "open_wall_shop"),
    ("오픈상가", "open_shop"),
    ("공부/현황 불일치", "mismatch"),
    ("제시외건물,종물/부합물", "extra_building"),
    ("미등기 부동산", "unregistered"),
    ("별도 등기 존재", "separate_registry"),
)


def _money(value: Decimal | None) -> str | None:
    """화면은 콤마를 자동으로 붙이므로 숫자만 넣는다."""
    if value is None:
        return None
    return format(value.quantize(Decimal(1)) if value == value.to_integral() else value, "f")


def _unit_price(row: MullistRow) -> str | None:
    """평가단가 = 감정평가액 ÷ 사정면적 (토지 물건).

    비용층 대표단가(cost.unit_price)는 문서 하나에 하나뿐이라 다물건 건에서
    물건별 단가를 못 집는다. 화면 규칙은 물건별 `감정평가액 ÷ 사정면적` 이고
    실측상 정확히 정수로 떨어진다. 건물(집합상가 등)은 화면상 0/공란이라 비운다.
    """
    if not row.is_land or not row.amount or not row.area_assessed:
        return None
    try:
        return format((row.amount / row.area_assessed).quantize(Decimal(1)), "f")
    except (ArithmeticError, ValueError):
        return None


def _area(value: Decimal | None) -> str | None:
    """면적은 소수 2자리 고정 + **버림**이다(실측: 11.717 → 11.71, 54.6 → 54.60)."""
    if value is None:
        return None
    return format(value.quantize(Decimal("0.01"), rounding=ROUND_DOWN), "f")


def _digits(value: str | None) -> str | None:
    """등기번호는 화면에 하이픈 없이 숫자만 들어간다."""
    if not value:
        return None
    return re.sub(r"\D", "", value) or None


def _floor_no(address: str | None) -> str | None:
    """소재지의 `제9층` 에서 해당층수를 뽑는다(mullist 에는 층 정보가 없다)."""
    if not address:
        return None
    match = re.search(r"제\s*(\d+)\s*층", address)
    return match.group(1) if match else None


def header_fields(context: DocumentContext) -> dict[str, str | None]:
    """물건과 무관한 화면 하단 필드(작성자·금액·수수료)."""
    parties = context.parties
    account = context.account
    fee = context.fee
    return {
        "대표,지사장": parties.boss,
        "평가사명1": parties.appraiser(0),
        "평가사명2": parties.appraiser(1),
        "평가사명3": parties.appraiser(2),
        "심사자": parties.reviewer,
        "총감정가액": _money(context.total_amount),
        "기준시점": context.price_point_date,
        "현장답사일": context.survey_date,
        "순수수료": _money(fee.net),
        "실   비": _money(fee.expense_with_vat),
        "감정평가료": _money(fee.total),
        "수수료입금계좌번호": account.number if account else None,
        "계좌입금자명": account.holder if account else None,
        "사업등록번호": context.business_number,
    }


def characteristic_fields(context: DocumentContext) -> dict[str, str]:
    """물건특성 8종. 의견서 표가 없으면 기본값으로 채운다."""
    found = context.characteristics
    fields = {
        label: getattr(found, key) or DEFAULT_CHARACTERISTIC
        for label, key in _CHARACTERISTIC_FIELDS
    }
    fields["임대"] = found.lease or DEFAULT_LEASE
    return fields


def property_fields(
    context: DocumentContext,
    row: MullistRow,
    combos: dict[str, frozenset[str]] | None = None,
) -> dict[str, str | None]:
    """물건 1건 → 화면 필드.

    combos 에 실제 콤보 목록을 주면 목록에 없는 값은 None 이 되어 비워진다
    (엉뚱한 값을 넣느니 비우는 편이 안전하다).
    """
    allowed = combos or {}
    outline = context.outline
    jibun = context.jibun
    cost = representative(context.cost_layers)

    struct = category = None
    if row.is_building:
        struct = codes.building_struct(
            row.struct_or_category or outline.struct, allowed.get("건물구조(신)")
        )
    elif row.is_land:
        category = codes.land_category(row.struct_or_category, allowed.get("지목"))

    kind = codes.collateral_kind(row.collateral_kind, allowed.get("담보종류"))
    if row.is_land and category and (allowed.get("담보용도") is None or category in allowed["담보용도"]):
        # 토지 물건: 담보용도 = 지목(대지·공장용지·전·잡종지…). 두 기간 모두 일관(실측).
        # ※담보종류는 관례가 기간마다 뒤집혀(2504=지목 다수, 2509=건물유형 압도) 규칙화 불가
        #   → mullist 원본(건물유형) 유지. 다수(2509 등)·원본충실. 실무 확정 시 재조정.
        use = category
    else:
        use = codes.collateral_use(kind, allowed.get("담보용도"))

    zone = row.zone or outline.zone
    if allowed.get("용도지역구분(신)") is not None and zone not in allowed["용도지역구분(신)"]:
        zone = None

    return {
        "물건순번": row.seq_no,
        "담보종류": kind,
        "담보용도": use,
        "담보세부종류": row.object_kind,
        "용도지역구분(신)": zone,
        "건물구조(신)": struct,
        "지목": category,
        "소재지": row.address or outline.address,
        "번지구분": jibun.jibun_kind if jibun else None,
        "본번지": jibun.bun1 if jibun else None,
        "부번지": jibun.bun2 if jibun else None,
        "공부면적(수량)": _area(row.area_public),
        "사정면적": _area(row.area_assessed),
        "대지권면적": _area(outline.area_land_right),
        "감정평가액": _money(row.amount),
        "평가단가": _unit_price(row),
        "사용승인일": row.approval_date or outline.approval_date,
        "내용연수": _int(row.useful_years, cost.useful_years if cost else None),
        "잔존연수": _int(row.remaining_years, cost.remaining_years if cost else None),
        "총층수": _int(outline.ground_floors),
        "해당층수": _floor_no(row.address or outline.address),
        "총방수": None,         # 어떤 소스에도 없다
        "토지등기부번호": (_digits(row.registry_no)
                     or context.registry_no(kind="토지", seq_no=row.seq_no)
                     ) if row.is_land else None,
        "건물등기부번호": (_digits(row.registry_no)
                     or context.registry_no(kind="건물", seq_no=row.seq_no)
                     ) if row.is_building else None,
    }


def _int(*candidates: int | None) -> str | None:
    for value in candidates:
        if value is not None:
            return str(value)
    return None


def build(
    context: DocumentContext,
    combos: dict[str, frozenset[str]] | None = None,
) -> tuple[dict[str, str | None], ...]:
    """물건별 화면 필드 묶음. 헤더·물건특성은 모든 물건에 같은 값으로 붙인다."""
    header = header_fields(context)
    traits = characteristic_fields(context)
    if not context.has_mullist:
        # mullist 없는 32% — 물건 단위 값이 없으므로 헤더만 채운다.
        return ({**header, **traits},)
    return tuple(
        {**header, **traits, **property_fields(context, row, combos)}
        for row in context.properties
    )
