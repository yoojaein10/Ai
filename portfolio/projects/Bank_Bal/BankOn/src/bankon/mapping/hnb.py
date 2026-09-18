"""하나은행 담보(`TBNKHNB24DAMB`) 필드 매핑.

수협·기업과 뼈대가 같다(명세표 물건 + 순번 정합). 하나 특유:
  · **주소를 시도/구군/읍면동/리/번지로 완전 분할**(수협은 소재지 통합 + 법정동 2칸).
    라벨이 다 있어 위치밴드가 필요 없다.
  · **계좌번호**(apw `BankAccount`) 칸이 있다.
  · **건물용도**가 58종 콤보(점포및상가·일반주택…) — 소스 건물용도(근린생활시설 등)를
    번역표로 매핑한다(`recon/combo_TBNKHNB24DAMB.md`).
  · **물건종류 콤보에 '집합건물'이 없다** — 구분건물도 '건물'.
  · 물건 순번(`일련번호`) 2개는 앵커(화면·BANK24 관리) — 안 쓴다. 9-자리 serial 은 소스에
    없다(BANK24 자동생성).

화면 항목명·콤보는 실폼(`recon/fields_TBNKHNB24DAMB.md`, `combo_TBNKHNB24DAMB.md`)에서 읽었다.
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
    land_category,
)

# 건물용도 번역 — 소스 표기(의견서 건물용도) → 하나 콤보 58종. 콤보에 없는 값을 내면 자동
# 선택이 못 골라 빈칸으로 남으므로(틀린 값은 안 들어감) 확정된 것만 넣고 나머지는 비운다.
# 실측 2751: `근린생활시설, 판매시설` → 화면 `점포및상가`.
# 순서 중요 — **구체적/합성 용도를 먼저** 본다. 소스는 `공장(아파트형공장) 및 근린생활시설`
# 처럼 여러 용도를 나열하는데, 화면은 **주 용도**를 쓴다(실측 2722: 아파트형공장 / 2751:
# 근린생활시설→점포및상가). 뒤의 부수용도(근린생활시설)를 먼저 잡지 않도록 특정 용도가 앞에.
_USE_HNB = {
    "아파트형공장": "아파트형공장", "오피스텔": "오피스텔", "다세대주택": "다세대주택",
    "다가구주택": "다가구주택", "연립주택": "연립주택", "아파트": "아파트",
    "냉동창고": "냉동창고", "저온창고": "저온창고", "냉동공장": "냉동공장",
    "숙박시설": "여관", "여관": "여관", "호텔": "호텔", "병원": "병원",
    "빌라": "빌라/맨션", "단독주택": "일반주택",
    "근린생활시설": "점포및상가", "판매시설": "점포및상가", "상가": "점포및상가",
    "점포": "점포및상가", "업무시설": "사무실", "사무실": "사무실",
    "학교": "학교", "교육연구시설": "학교", "종교시설": "교회",
    "창고": "일반창고", "공동주택": "아파트", "공장": "일반공장", "주택": "일반주택",
}

# 하나 지목 콤보(29종) — '대'(대지 아님). 미확인은 안 낸다.
_LAND_HNB = frozenset({
    "전", "답", "과수원", "목장용지", "임야", "광천지", "염전", "대", "공장용지",
    "학교용지", "주차장", "주유소용지", "창고용지", "도로", "철도용지", "제방", "하천",
    "구거", "유지", "양어장", "수도용지", "공원", "체육용지", "유원지", "종교용지",
    "사적지", "묘지", "잡종지",
})


def _building_use(text: str | None, is_section: bool = False) -> str | None:
    """소스 건물용도 → 하나 콤보. 여러 용도면 **주 용도**(맨 앞·괄호 안)를 우선.

    화면은 나열된 용도 중 주 용도를 쓴다. 특히 **구분건물의 공장 = 아파트형공장**
    (지식산업센터 — 실측 2473 `공장,…` · 2722 `공장(아파트형공장)…` 둘 다 화면 아파트형공장).
    """
    if not text:
        return None
    # 괄호 안 구체용도(아파트형공장 등)를 먼저 본다.
    paren = re.search(r"\(([^)]+)\)", text)
    head = re.split(r"[,/]|및", text)[0].strip()
    # '공장'이 주 용도면 구분건물은 아파트형공장, 그 외는 일반공장.
    if head.startswith("공장") or "아파트형공장" in text:
        if "아파트형공장" in text or is_section:
            return "아파트형공장"
        return "일반공장"
    for cand in (paren.group(1) if paren else None, head, text):
        if not cand:
            continue
        for key, val in _USE_HNB.items():
            if key in cand:
                return val
    return None


def _land_hnb(text: str | None) -> str | None:
    name = (text or "").strip()
    return name if name in _LAND_HNB else None


def _addr_parts(site: str | None) -> tuple[str | None, str | None, str | None, str | None]:
    """소재지 → (시도, 구군, 읍면동, 리).

        서울특별시 성동구 옥수동         → (서울특별시, 성동구, 옥수동, None)
        경기도 부천시 원미구 상동         → (경기도, 부천시 원미구, 상동, None)   # 시+구
        충청북도 청원군 북이면 옥수리      → (충청북도, 청원군, 북이면, 옥수리)     # 읍/면+리
    """
    parts = [p for p in re.sub(r"\s+", " ", (site or "").strip()).split(" ") if p]
    sido = parts[0] if len(parts) > 0 else None
    gugun = emd = ri = None
    # 세종특별자치시는 구/군 계층이 없다 — 시도=세종…, 구군 공란, 읍면동=다음(읍면이면 리까지).
    if sido and sido.startswith("세종"):
        if len(parts) >= 3 and parts[1].endswith(("읍", "면")):
            emd, ri = parts[1], parts[2]
        elif len(parts) >= 2:
            emd = parts[1]
        return sido, None, emd, ri
    if len(parts) >= 4 and parts[1].endswith("시") and parts[2].endswith("구"):
        # 시 아래 구가 있는 도시(부천시 원미구·성남시 분당구…): 구군=시+구.
        gugun, emd = f"{parts[1]} {parts[2]}", parts[3]
        ri = parts[4] if len(parts) >= 5 else None
    elif len(parts) >= 4 and parts[2].endswith(("읍", "면")):
        gugun, emd, ri = parts[1], parts[2], parts[3]
    else:
        gugun = parts[1] if len(parts) > 1 else None
        emd = parts[2] if len(parts) > 2 else None
    return sido, gugun, emd, ri


def _clean_name(name: str | None) -> str | None:
    """건물명에서 뒤따르는 `제…동/층/호` 표기를 떼어 단지명만 남긴다."""
    if not name:
        return None
    trimmed = re.split(r"\s+제\s*", name)[0].strip()
    return trimmed or None


def _split_jibun(text: str | None) -> tuple[str | None, str | None]:
    if not text:
        return (None, None)
    m = re.match(r"^\s*(?:산\s*)?(\d+)(?:\s*-\s*(\d+))?", text)
    if not m:
        return (None, None)
    return (m.group(1).lstrip("0") or None, (m.group(2) or "").lstrip("0") or None)


def slots(context: DocumentContext) -> tuple:
    """하나 화면의 물건 행 순서 — **금액 앵커**(단가별 행) + **평가외 부분**(옥탑 등, 맨 뒤).

    실측 2871(잠실동 숙박시설, 담당자 완성본 5행): 토지 165.3 / 건물 1층 단가 540,000 /
    2~9층 756,000 / 지층 486,000 / 옥탑 12.25 '감정평가외'. 하나는 **단가마다 한 행**으로
    넣고 평가외도 한 행을 만든다(사용자 확인 2026-09-16).
    """
    rows = [r for r in context.details if r.is_land or r.is_building]
    anchors = [r for r in rows if r.amount is not None]
    if not anchors:
        return tuple(rows)
    return tuple(anchors) + tuple(getattr(context, "excluded_parts", ()) or ())


def _slot_item(context: DocumentContext, seq_no: str | None):
    """화면 순번 → 물건. 평가외 행까지 포함한 slots() 순서로 고른다."""
    rows = tuple(r for r in context.details if r.is_land or r.is_building)
    ordered = slots(context)
    if seq_no and str(seq_no).strip().isdigit() and len(ordered) >= 2:
        index = int(seq_no) - 1
        if 0 <= index < len(ordered):
            return ordered[index]
    return detail.for_sequence(rows, seq_no)


def _unit_use(context: DocumentContext) -> str | None:
    """명세 건물 유닛 머리의 `JIMOK` — 건물 블록에선 지목이 아니라 **건물 용도**다.

    의견서 개요가 깨져 건물용도를 못 읽는 건이 있다(2871: '연면적(㎡) (옥탑층 제외)' 가 들어온다).
    그때 명세의 '숙박시설' 로 콤보 '여관' 을 고를 수 있다.
    """
    for row in context.details:
        if row.kind == detail.UNIT_BUILDING and row.category:
            return row.category
    return None


def build(context: DocumentContext, seq_no: str | None = None) -> dict[str, str | None]:
    """하나 담보 화면 — 물건 하나(화면 순번에 정합). 다물건은 순번마다 반복 호출."""
    outline = context.outline
    jibun = context.jibun
    fee = context.fee
    account = getattr(context, "account", None)

    property_rows = tuple(r for r in context.details if r.is_land or r.is_building)
    item = _slot_item(context, seq_no)
    is_land = bool(item and item.kind == detail.UNIT_LAND)
    is_building = bool(item and (item.is_building or item.kind == detail.UNIT_BUILDING))
    # 집계형(rollup) .gam: 명세에 총액행만 있고 개별 호가 없다 → amount 가 건물 전체 합이라
    # 개별 호 감정평가액과 다르다. 면적·금액을 비운다(수협 ssb 와 같은 규칙, 감사 P0-B).
    rollup = detail.is_rollup_only(context.details)

    area_public, area_assessed, amount = _item_values(context, item, is_land)
    if rollup:
        area_public = area_assessed = amount = None
    floor_no, unit_no, dong_no = _floor_ho_dong(item, context)

    # 평가외 행(옥탑 등): 면적만 넣고 **단가 1 · 감정평가액 0**(실측 2871 5행).
    # 등기부고유번호·건물정보는 본 건물 것을 그대로 쓴다(화면도 같은 번호였다).
    excluded = bool(item is not None and item.excluded)
    registry_item = item
    if excluded:
        buildings = [r for r in property_rows
                     if r.amount is not None and (r.is_building or r.kind == detail.UNIT_BUILDING)]
        registry_item = buildings[-1] if buildings else item

    # 지번: 명세행 우선, 없으면 apw. 번지 칸엔 본번(부번 있으면 본-부).
    main_no, sub_no = _split_jibun(item.jibun if item else None)
    if main_no is None and jibun is not None:
        main_no, sub_no = jibun.bun1, jibun.bun2
    banji = f"{main_no}-{sub_no}" if (main_no and sub_no) else main_no

    sido, gugun, emd, ri = _addr_parts(context.site_address)
    cost = representative(context.cost_layers) if is_building else None

    return {
        # 머리/수수료
        "평가사명": (context.rounds[0].appraiser if context.rounds else None)
                  or context.parties.appraiser(0),
        "기준시점": context.price_point_date,
        "감정일자": context.price_point_date,      # 실측 2751: 감정일자=기준시점=2026-09-03
        # 하나 화면은 계좌번호를 숫자만 저장(하이픈 제거) — 실측 2722: 10391001691404.
        "계좌번호": re.sub(r"\D", "", account.number) if (account and account.number) else None,
        "총감정평가액": _money(context.total_amount),
        "순수수료": _money(fee.net),
        "반려사유": None,
        # 물건 순번 2개는 앵커(화면·BANK24 관리) — 안 쓴다.
        # 주소(완전분할 — 라벨 다 있어 위치밴드 불필요)
        "시도": sido,
        "구군": gugun,
        "읍면동": emd,
        "리": ri,
        "번지": banji,
        # 물건
        "물건종류": ("토지" if is_land else "건물" if is_building else None),  # 집합건물 옵션 없음
        "감정평가액": "0" if excluded else _money(amount),
        # 명세에 단가가 있으면 그대로(하나는 **단가별로 행을 나눈다** — 실측 2871 건물 540,000·756,000·486,000).
        # 단가가 없는 구분건물(2751·2746 등)은 화면이 0 을 표시한다. 평가외 행은 1(실측 2871 5행).
        "평가단가": ("1" if excluded
                  else _money(item.unit_price) if (item and item.unit_price is not None)
                  else "0" if is_building else None),
        "사정면적": _area(area_assessed),
        "공부면적": _area(area_public),
        "공부상지목": _land_hnb(item.category) if (is_land and item) else None,
        "실제지목": _land_hnb(item.category) if (is_land and item) else None,
        "등기부고유번호": context.registry_no(
            kind=registry_item.kind if registry_item else None,
            seq_no=registry_item.seq_no if registry_item else None,
            area=(registry_item.area_public if excluded else area_public),
            location=(registry_item.location if registry_item else None),
            jibun=(registry_item.jibun if registry_item else None)),
        # 건물 상세(건물 물건만). 건물명은 단지명만 — 뒤에 붙는 `제…동/층/호` 표기를 뗀다
        # (실측 2751: `옥수어울림 제근린생활시설동 제지3층` → `옥수어울림`).
        "건물명": _clean_name(building_name(context, item)) if is_building else None,
        "동": dong_no if is_building else None,
        "호": unit_no if is_building else None,
        # 의견서 개요가 깨져 용도를 못 읽으면 명세 건물 유닛의 용도로 폴백(2871 '숙박시설'→'여관').
        "건물용도": ((_building_use(outline.building_use or outline.usage,
                               is_section=bool(item and item.is_building))
                   or _building_use(_unit_use(context), is_section=bool(item and item.is_building)))
                  if is_building else None),
        "준공/제작일자": outline.approval_date if is_building else None,
        # 내용연수 — 원가법 산출표 대표층(결정단가 최대)의 내용연수(신한·기업·새마을과 같은 규칙, 실측 2871=50).
        "내용연수": (str(cost.useful_years) if (is_building and cost and cost.useful_years is not None)
                 else None),
    }
