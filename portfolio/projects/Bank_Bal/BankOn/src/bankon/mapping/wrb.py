"""우리은행 담보(`TBNKWRB24DAMB`) 필드 매핑.

농협+하나의 조합 — 명세표 물건 + 표준지·par_player 평가사(농협) + 계좌·완전주소(하나).
우리은행 특유:
  · **물건종류 42종 콤보**(단독주택·근린상가·공장·선박·어업권…) — 소스 이용상황/개요 매핑.
  · 세부물건종류 콤보(대지/건물) · 토지지목 28종('대지') · 용도 24종 축약(2종일주·개발제한).
  · **표준지 블록**(공시기준일·표준지공시지가·표준지소재지) — 농협과 같음.
  · **계좌번호** 칸(apw BankAccount).
  · 물건개요 텍스트칸: 토지현황·이용상황·구  조·용도지역(축약).
  · 라벨 없는 칸: 법정동코드(10자리)·소재지(완전) — 물건 2세트 selector 라 좌우 중복.
  · 작성자 콤보 6개(대표지사장·심사자·평가사명1~3) — 농협처럼 비활성/관례로 대개 비움.

화면 항목명·콤보는 실폼(`recon/fields_TBNKWRB24DAMB.md`, `combo_TBNKWRB24DAMB.md`)에서 읽었다.
"""
from __future__ import annotations

import re

from ..model import DocumentContext
from ..parse import detail
from .nh import (
    _area,
    _money,
    _floor_ho_dong,
    _item_values,
    building_name,
)

# 용도지역 → 우리 축약(24종). 실측 2668: 제2종일반주거지역→2종일주. 개발제한·미지정 등 포함.
_ZONE_WRB = {
    "제1종전용주거지역": "1종전주", "제2종전용주거지역": "2종전주",
    "제1종일반주거지역": "1종일주", "제2종일반주거지역": "2종일주",
    "제3종일반주거지역": "3종일주", "준주거지역": "준주거",
    "중심상업지역": "중심상업", "일반상업지역": "일반상업", "근린상업지역": "근린상업",
    "유통상업지역": "유통상업", "전용공업지역": "전용공업", "일반공업지역": "일반공업",
    "준공업지역": "준공업", "보전녹지지역": "보전녹지", "생산녹지지역": "생산녹지",
    "자연녹지지역": "자연녹지", "개발제한구역": "개발제한", "보전관리지역": "보전관리",
    "생산관리지역": "생산관리", "계획관리지역": "계획관리", "농림지역": "농림지역",
    "자연환경보전지역": "자연환경",
}
_ZONE_WRB_VALUES = frozenset(_ZONE_WRB.values())

# 토지지목 콤보(28종) — 우리은행은 `대지`(하나·수협은 '대'). 미등록은 안 낸다.
_LAND_WRB = frozenset({
    "전", "답", "과수원", "목장용지", "임야", "광천지", "염전", "대지", "공장용지",
    "학교용지", "주차장", "주유소용지", "창고용지", "도로", "철도", "제방", "하천",
    "구거", "유지", "양어장", "수도용지", "공원", "체육용지", "유원지", "종교용지",
    "사적지", "묘지", "잡종지",
})

# 물건종류 42종 — 소스 이용상황/주용도를 우리 콤보로. **순서 중요**: 구체·복합 용어를
# 먼저(아파트형공장→공장, 아파트형상가→상가(아파트형)). dict 는 삽입순 검사라 위가 우선.
# 확정 매핑만(없으면 비움=사람선택). 상업용은 문서마다 화면표기가 갈려 확정분만.
_KIND_WRB = {
    "아파트형공장": "공장(공장재단포함)", "공장": "공장(공장재단포함)",  # 아파트형'공장'
    "상가(아파트형)": "상가(아파트형)", "아파트형": "상가(아파트형)",
    "다가구주택": "다가구주택", "다세대주택": "다세대주택", "연립주택": "연립주택",
    "근린주택": "근린주택", "단독주택": "단독주택", "아파트": "아파트",
    "오피스텔": "오피스텔", "사무실": "사무실", "업무시설": "사무실",
    "숙박시설": "모텔", "여관": "여관,여인숙", "호텔": "호텔", "병원": "병원",
    "창고": "창고", "주유소": "주유소(충전소)",
    "선박": "선박", "어업권": "어업권", "차량": "차량", "기계기구": "기계기구",
    # 근린생활시설+주택 복합 → 근린상가(실측 2668). (주택 계열보다 뒤 — 순수주택 먼저 잡게.)
    "근린생활시설": "근린상가",
}


def zone_wrb(text: str | None) -> str | None:
    """용도지역 → 우리 축약. 이미 축약형(2종일주)이면 그대로, 정식명이면 변환."""
    name = (text or "").strip()
    if not name:
        return None
    if name in _ZONE_WRB_VALUES:
        return name                        # 이미 축약형(소스가 축약으로 오기도 함)
    return _ZONE_WRB.get(name)


def land_wrb(text: str | None) -> str | None:
    name = (text or "").strip()
    if name == "대":
        return "대지"                      # 명세표 '대' → 우리 콤보 '대지'
    return name if name in _LAND_WRB else None


def kind_wrb(usage: str | None, building_use: str | None) -> str | None:
    """물건종류 42종 콤보 — 확정 매핑만. usage·building_use 를 **둘 다** 본다(이용상황이
    '주상용' 처럼 콤보에 없어도 건물용도 '근린생활시설' 로 잡히게). 상업용은 문서마다
    화면표기가 갈려 확정 매핑만 낸다(없으면 비움 = 사람 선택)."""
    for source in (usage, building_use):
        text = (source or "").strip()
        if not text:
            continue
        for key, val in _KIND_WRB.items():
            if key in text:
                return val
    return None


def _split_jibun(text: str | None) -> tuple[str | None, str | None]:
    if not text:
        return (None, None)
    m = re.match(r"^\s*(?:산\s*)?(\d+)(?:\s*-\s*(\d+))?", text)
    if not m:
        return (None, None)
    return (m.group(1).lstrip("0") or None, (m.group(2) or "").lstrip("0") or None)


# 법정동코드·소재지(라벨 없는 칸)는 **자동입력하지 않는다**. 실측(2668): 물건 2세트라 밴드에
# 법정동①②·소재지①② 4칸이 라벨 없이 섞여 있어 위치로 안전하게 못 짚는다(수협 P0-2 부류).
# 게다가 이 칸들은 감정사가 **주소검색으로 자동 채우는** 칸(화면에 이미 1117013100·한남동이
# 차 있음)이라 우리가 쓸 필요가 없다 — 위험만 크고 이득이 없어 제외한다. (필요 시 사람 확인.)


def build(context: DocumentContext, seq_no: str | None = None) -> dict[str, str | None]:
    """우리은행 담보 화면 — 물건 하나(화면 순번 정합). 다물건은 순번마다 반복."""
    outline = context.outline
    jibun = context.jibun
    fee = context.fee
    account = getattr(context, "account", None)
    standard = context.standard_land

    property_rows = tuple(r for r in context.details if r.is_land or r.is_building)
    item = detail.for_sequence(property_rows, seq_no)
    is_land = bool(item and item.kind == detail.UNIT_LAND)
    is_building = bool(item and (item.is_building or item.kind == detail.UNIT_BUILDING))
    rollup = detail.is_rollup_only(context.details)

    area_public, area_assessed, amount = _item_values(context, item, is_land)
    if rollup:
        area_public = area_assessed = amount = None

    main_no, sub_no = _split_jibun(item.jibun if item else None)
    if main_no is None and jibun is not None:
        main_no, sub_no = jibun.bun1, jibun.bun2

    zone = zone_wrb(item.zone if (is_land and item) else None) or zone_wrb(outline.zone)
    _, unit_no, dong_no = _floor_ho_dong(item, context)

    return {
        # 머리/수수료
        "담보구분": None,                    # 임대차포함 등 — 소스 미확정(사람 선택)
        "기준시점": context.price_point_date,
        "평가사명": (context.rounds[0].appraiser if context.rounds else None)
                  or context.parties.appraiser(0),
        "감정수수료": _money(fee.total),
        "순수수료": _money(fee.net),
        "실   비": _money(fee.expense_net),
        "부가세": _money(fee.vat),
        "계좌번호": re.sub(r"\D", "", account.number) if (account and account.number) else None,
        # 작성자 콤보 6개는 비활성/관례로 대개 비움 — 안 낸다(농협과 동일).
        # 물건 개요(텍스트)
        "토지현황": None,                    # '건대지' 등 — 소스 표기 미확정
        "이용상황": outline.usage,
        "구   조": (outline.struct or "").split("/")[0].strip() or None,   # 지붕 앞부분
        "용도지역": zone,                    # 텍스트칸(축약)
        # 물건 selector
        "세부물건종류": ("대지" if is_land else "건물" if is_building else None),
        "물건종류": kind_wrb(outline.usage, outline.building_use),   # 42종 콤보
        "번지구분": jibun.jibun_kind if jibun else None,
        "본번지": main_no,
        "부번지": sub_no,
        "건물명": building_name(context, item) if is_building else None,
        "동": dong_no if is_building else None,
        "호": unit_no if is_building else None,
        "감정평가액": _money(amount),
        "평가단가": _money(item.unit_price) if (is_land and item) else None,
        "사정면적": _area(area_assessed),
        "공부면적": _area(area_public),
        "토지지목": land_wrb(item.category) if (is_land and item) else None,
        "용도": zone,                        # 콤보(축약, 위 용도지역과 같은 값)
        "건물구조": None,                    # 소스 미확정(개요 구조는 위 구조칸)
        # 표준지 (농협과 같음)
        "공시기준일": standard.base_date if standard else None,
        "표준지공시지가": _money(standard.price) if standard else None,
        "표준지소재지": standard.address if standard else None,
        # 법정동코드·소재지는 자동입력 제외(위 주석) — 주소검색 자동생성 칸.
    }
