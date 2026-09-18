"""새마을금고 담보(`TBNKMGB24DAMB`) 필드 매핑.

농협 기반(명세표 물건 + 표준지 + par_player 평가사) + 새마을 특유:
  · **물건종류 4콤보**: 토지 / **토지+건물**(복합) / 집합건물 / 건물.
  · **용도지역 정식명**(제2종일반주거지역 — 축약 아님). land_list zone 그대로.
  · **토지 특성 3콤보**: 도로상태(광대세각…)·형상(세장형…)·지세(평지…) — 의견서 개요표에서.
  · 공부상지목 콤보('대' — 하나·수협식). 계좌번호(apw BankAccount).
  · 내용연수·잔존연수: 원가법 산출표 대표층(결정단가 최대) — 건물 있는 물건만.
  · 라벨 없는 칸: 법정동코드(10자리)·소재지(완전) — 위치밴드.

화면 항목명·콤보는 실폼(`recon/fields_TBNKMGB24DAMB.md`, `combo_TBNKMGB24DAMB.md`)에서 읽었다.
"""
from __future__ import annotations

import re

from ..model import DocumentContext
from ..parse import detail
from ..parse.cost import representative
from .nh import (
    _area,
    _money,
    _floor_ho_dong,
    _item_values,
    building_name,
)

# 공부상지목 콤보(28종). 새마을은 '대'(우리은행은 '대지'). 미등록은 안 낸다.
_LAND_MGB = frozenset({
    "전", "답", "과수원", "목장용지", "임야", "광천지", "염전", "대", "공장용지",
    "학교용지", "주차장", "주유소용지", "창고용지", "도로", "철도용지", "제방", "하천",
    "구거", "유지", "양어장", "수도용지", "공원", "체육용지", "유원지", "종교용지",
    "사적지", "묘지", "잡종지",
})

# 도로상태·형상·지세는 outline 파서(`outline.road/shape/slope`, 토지 특성표)에서 온다.


def land_mgb(text: str | None) -> str | None:
    name = (text or "").strip()
    return name if name in _LAND_MGB else None


def _struct_head(struct: str | None) -> str | None:
    """건물구조 — 지붕 표현을 뗀다. `A / 평스라브지붕`(슬래시) · `A (철근)콘크리트지붕`(공백+
    지붕) 두 꼴 모두. 슬래시 우선, 없으면 `…지붕` 직전까지. 콤마로 이어진 구조는 유지."""
    text = (struct or "").split("/")[0].strip()
    m = re.search(r"\s+\S*지붕", text)          # 공백 뒤 '…지붕' 조각 제거
    if m:
        text = text[:m.start()].strip()
    text = re.sub(r"\([^)]*\)", "", text).strip()   # 괄호주석 제거(예 (PEB))
    return text or None


def _kind_mgb(context: DocumentContext) -> str | None:
    """물건종류 4콤보 — **gam_info 물건구분**을 1차로 쓴다(가장 확실): 구분건물→집합건물,
    토지건물→토지+건물, 토지→토지, 건물→건물(실측 2756·2762). gam 구분이 없으면 명세
    구성으로 판정한다(⚠️ is_land/is_building 은 신뢰 못 함 — kind 문자열로)."""
    gc = (getattr(context, "gam_category", None) or "").strip()
    if "구분건물" in gc or "집합" in gc:
        return "집합건물"
    if "토지" in gc and "건물" in gc:
        return "토지+건물"
    if gc == "토지":
        return "토지"
    if gc == "건물":
        return "건물"
    rows = [r for r in context.details if (r.is_land or r.is_building)]
    kinds = {(getattr(r, "unit_kind", None) or r.kind or "") for r in rows}
    has_land = any("토지" in k for k in kinds)
    has_building = any(("건물" in k or "집합" in k) for k in kinds)
    if has_land and has_building:
        return "토지+건물"
    if has_land:
        return "토지"
    if has_building:
        return "건물"
    return None


def _split_jibun(text: str | None) -> tuple[str | None, str | None]:
    if not text:
        return (None, None)
    m = re.match(r"^\s*(?:산\s*)?(\d+)(?:\s*-\s*(\d+))?", text)
    if not m:
        return (None, None)
    return (m.group(1).lstrip("0") or None, (m.group(2) or "").lstrip("0") or None)


def _pick_item(rows: tuple, seq_no: str | None):
    """새마을 화면 순번 → 명세 물건. 화면은 명세를 **토지(숫자 seq) → 건물** 순으로 늘어놓아
    순번을 매긴다(실측 2568: 순번1=264토지, 순번2=263토지, 그 뒤 건물들). 그 순서열의
    N번째를 고른다. 순번이 없으면 detail.for_sequence(금액 anchor 기준)로 폴백."""
    if not seq_no or not str(seq_no).isdigit():
        return detail.for_sequence(rows, seq_no)
    n = int(seq_no)
    lands = [r for r in rows if "토지" in (getattr(r, "unit_kind", None) or r.kind or "")]
    builds = [r for r in rows if r not in lands]
    ordered = lands + builds
    return ordered[n - 1] if 1 <= n <= len(ordered) else detail.for_sequence(rows, seq_no)


def build(context: DocumentContext, seq_no: str | None = None) -> dict[str, str | None]:
    """새마을금고 담보 화면 — 물건 하나(화면 순번 정합). 다물건은 순번마다 반복."""
    outline = context.outline
    jibun = context.jibun
    fee = context.fee
    account = getattr(context, "account", None)
    standard = context.standard_land

    property_rows = tuple(r for r in context.details if r.is_land or r.is_building)
    item = _pick_item(property_rows, seq_no)
    is_land = bool(item and item.kind == detail.UNIT_LAND)
    is_building = bool(item and (item.is_building or item.kind == detail.UNIT_BUILDING))
    rollup = detail.is_rollup_only(context.details)

    area_public, area_assessed, amount = _item_values(context, item, is_land)
    if rollup:
        area_public = area_assessed = amount = None

    kind = _kind_mgb(context)
    rows = list(property_rows)
    is_land_row = lambda r: "토지" in (getattr(r, "unit_kind", None) or r.kind or "")
    unit_price = item.unit_price if item else None
    # 건물 정보칸(건물구조·사용승인일·준공일자) 대상 — 이 물건에 건물이 있으면. 통합형
    # (토지+건물)은 순번1 item 이 토지여도 건물이 포함되므로 kind 로 판정한다.
    _has_building = is_building or kind in ("집합건물", "토지+건물", "건물")

    # 일단지 member 토지(단가·금액 없음): 같은 블록 **머리(group_head)의 단가**를 공유하고
    # 화면 금액 = 자기 면적 × 머리단가(실측 2568: 263필지 28㎡ × 9,640,000 = 269,920,000).
    if (is_land and item and item.unit_price is None and item.amount is None
            and item.area_public is not None and not item.group_head):
        idx = rows.index(item)
        head = next((rows[j] for j in range(idx, -1, -1)
                     if is_land_row(rows[j]) and rows[j].group_head), None)
        if head and head.unit_price is not None:
            unit_price = head.unit_price
            area_public = area_assessed = item.area_public
            amount = item.area_public * head.unit_price

    # 통합/분리 판정 = **일단지 머리(group_head) 유무**(실측: 2762·2761 머리0=통합 /
    # 2568 머리1=분리). 일단지 블록(`<|>`)이 있으면 화면이 필지별로 나뉘므로 통합 안 함.
    has_block = any(r.group_head for r in rows if is_land_row(r))
    single = not has_block
    # 분리형(일단지 블록)은 물건종류도 **순번별**(item 기준). 통합형(single)은 문서 전체.
    if not single and item is not None:
        if is_land:
            kind = "토지"
        elif is_building:
            kind = "집합건물" if "구분" in (getattr(context, "gam_category", "") or "") else "건물"
    # 새마을 '토지+건물'(복합)은 한 물건에 **토지+건물을 통합**해 보여준다(실측 2762): 감정가액
    # =전체 총액, 면적=토지+건물 공부면적 합, 단가=토지 단가. 일단지 블록이 없을 때만.
    if kind == "토지+건물" and single and not rollup:
        amount = context.total_amount
        # 면적 합 = 토지 공부면적 + 건물 사정면적(실측 2762: 578.2 + 950.52 + 270.04 = 1798.76).
        areas = [(r.area_public if is_land_row(r) else r.area_assessed) for r in rows]
        areas = [a for a in areas if a is not None]
        if areas:
            area_public = sum(areas[1:], start=areas[0])
            area_assessed = area_public
        land = next((r for r in rows if is_land_row(r)), None)
        unit_price = land.unit_price if land else unit_price

    main_no, sub_no = _split_jibun(item.jibun if item else None)
    if main_no is None and jibun is not None:
        main_no, sub_no = jibun.bun1, jibun.bun2

    # 용도지역은 **정식명**(콤보가 정식). land_list zone 이 정식이면 그대로, 개요 축약이면 안 씀.
    zone = (item.zone if (is_land and item) else None) or None
    if zone and not zone.endswith(("지역", "구역")):
        zone = None                        # 축약형은 콤보에 없다 → 사람 선택
    road, shape, slope = outline.road, outline.shape, outline.slope
    _, unit_no, dong_no = _floor_ho_dong(item, context)
    # 내용연수·잔존연수 칸은 하나 — 의견서 원가법 산출표의 **대표층(결정단가 최대)** 값(신한·기업과 같은 규칙).
    # 건물이 있는 물건만. 원가표가 없으면(구분건물 거래사례 등) 비운다. 2847 빈칸 제보로 추가(2026-09-15).
    cost = representative(context.cost_layers) if _has_building else None

    return {
        # 머리/수수료
        "감정구분": None,                    # 임대차포함 등 — 소스 미확정(사람 선택)
        "감정수수료": _money(fee.total),
        "가격평가일자": context.price_point_date,
        "부가세": _money(fee.vat),
        "주용도": outline.usage,
        "순수수료": _money(fee.net),
        "평가사성명": (context.rounds[0].appraiser if context.rounds else None)
                    or context.parties.appraiser(0),
        "총감정평가액": _money(context.total_amount),
        "실비": _money(fee.expense_net),
        "특별용역비": "0",       # 칸이 있으면 0(전 은행 공통, 사용자 지시 2026-09-14)
        # 물건
        "물건종류": kind,
        "공부상지목": land_mgb(item.category) if (is_land and item) else None,
        "도로상태": road,
        "형상": shape,
        "지세": slope,
        "등기고유번호": context.registry_no(
            kind=item.kind if item else None, seq_no=item.seq_no if item else None,
            area=area_public, location=(item.location if item else None),
            jibun=(item.jibun if item else None)),
        "감정가액": _money(amount),
        "공부면적": _area(area_public),
        "사정면적": _area(area_assessed),
        "이용상황": outline.usage,
        "토지단가": _money(unit_price) if (is_land or kind == "토지+건물") else None,
        "번지구분": jibun.jibun_kind if jibun else None,
        "본번": main_no,
        "부번": sub_no,
        "건물명": building_name(context, item) if is_building else None,
        "동": dong_no if is_building else None,
        "호": unit_no if is_building else None,
        "건물구조": _struct_head(outline.struct) if _has_building else None,
        "내용연수": str(cost.useful_years) if cost and cost.useful_years is not None else None,
        "잔존연수": str(cost.remaining_years) if cost and cost.remaining_years is not None else None,
        "사용승인일": outline.approval_date if _has_building else None,
        "준공일자": outline.approval_date if _has_building else None,
        "용도지역": zone,
        # 표준지 (농협과 같음)
        "표준지공시기준일": standard.base_date if standard else None,
        "표준지소재지": standard.address if standard else None,
        "표준지공시지가": _money(standard.price) if standard else None,
    }
