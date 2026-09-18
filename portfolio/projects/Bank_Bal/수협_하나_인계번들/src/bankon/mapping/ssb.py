"""수협(수산업협동조합) 담보(`TBNKSSB24DAMB`) 필드 매핑.

농협(`nh`)과 뼈대가 같다 — 명세표(`land_list`/`section_build`)가 물건 출처, 라벨 없는
소재지/법정동코드, 다물건 순번. 그래서 농협 헬퍼(소재지·법정동·건물명·지목)를 재사용한다.

농협과 다른 점(실측 2637 로 확인):
  · **평가사명 = `round0.par_player`** 다(apw manager 가 아니다 — 실측: apw=조경미 /
    화면=유승민=par_player). 감정평가표에 서명한 평가사를 화면이 쓴다.
  · **실비 = `expense_net` 원값**(기업식, 부가세 없음 — 실측 2637=56,000). 지역농협의
    부가세×1.1 보정을 하지 않는다.
  · **일단지 블록합** — 화면 공부/사정면적·감정평가액은 묶음 **전체** 값이다
    (실측 2637: head 36-1 공부 460 + 소분 41-3/9/13/61 = 722 = 화면 공부·사정;
     head amount 22,021,000,000 = 722×30,500,000 = 화면 감정평가액).
  · **용도지역이 수협 축약 코드**다(`제3종일반주거지역` → 화면 `3종일주`). 콤보 목록을
    실폼에서 떠서(`recon/combo_TBNKSSB24DAMB.md`) 확정할 것 — 지금은 확인된 것만 낸다.
  · **법정동코드가 두 칸**(시군구 5 + 읍면동 5 — 실측 11290 + 12500 = 성북구 안암동).
  · `기호`·`소유지분율`·`상세주소`·`감정평가액 결정의견` 은 다른 은행에 없던 칸이다.
  · **선박·어업권** 담보가 섞인다(수협 특유) — 부동산 매핑으로 안 되므로 별도(TODO).

화면 항목명은 실폼(`recon/fields_TBNKSSB24DAMB.md`, `recon/ssb_screen.json`)에서 읽었다.
"""
from __future__ import annotations

import re

from ..codes import common
from ..model import DocumentContext
from ..parse import detail, round as round_parse
from .nh import (
    _area,
    _money,
    _group_members,
    building_name,
    land_category,
    legal_code,
    site_address,
)

# 수협 용도지역 콤보 축약 — 규칙 기반(실폼 combo 목록으로 최종 확정 권장).
#   주거: 제N종일반주거지역 → `N종일주` / 제N종전용주거지역 → `N종전주` / 준주거지역 → `준주거`
#   그 외: `지역` 접미사만 뗀다 — 일반상업지역 → `일반상업`(실측 2583).
# 실측 확인: 1종일주(2641) · 3종일주(2637) · 일반상업(2583). 목록에 없는 값을 콤보에
# 내면 못 골라 빈칸으로 남을 뿐(틀린 값은 안 들어간다).
_ZONE_RESIDENTIAL = re.compile(r"제\s*(\d+)\s*종\s*(일반|전용)주거지역")

# 라벨 없는 칸 — `물건구분코드`~`번지구분` 밴드로 짚는다. 실폼 두 변형(토지 2637·2641·
# 2583·1068 / 집합물건 1066)에서 밴드 구성:
#   최상단 행(top≈391): 법정동 시군구(좌·5자리) · 읍면동(우·5자리)
#   그 아래: 등기번호(라벨 있음) · 소재지(최좌측) · …
# 법정동은 **최상단 행의 좌/우**(`위좌`/`위우`)로 짚는다 — 숫자 인덱스([0][1])는 폼변형마다
# 밴드 구성이 달라지면 어긋나(감사 P0-2, form.py 자기경고), '최상단 행 좌/우' 는 유지된다.
# 소재지는 밴드 최좌측이라 `왼쪽`.
BOX_SITE = "소재지@물건구분코드~번지구분[왼쪽]"
BOX_LEGAL_SGG = "법정동코드시군구@물건구분코드~번지구분[위좌]"     # 최상단행 왼쪽(시군구 5자리)
BOX_LEGAL_EMD = "법정동코드읍면동@물건구분코드~번지구분[위우]"     # 최상단행 오른쪽(읍면동 5자리)


# 수협 소재지는 **시도를 축약**한다(실측 2637·1066·1068: 서울특별시→서울, 인천광역시→인천).
_SIDO_SHORT = {
    "서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천",
    "광주광역시": "광주", "대전광역시": "대전", "울산광역시": "울산", "세종특별자치시": "세종",
    "경기도": "경기", "강원특별자치도": "강원", "강원도": "강원", "충청북도": "충북",
    "충청남도": "충남", "전라북도": "전북", "전북특별자치도": "전북", "전라남도": "전남",
    "경상북도": "경북", "경상남도": "경남", "제주특별자치도": "제주", "제주도": "제주",
}


def _short_sido(site: str | None) -> str | None:
    """소재지 앞 시도를 수협 축약형으로 — `서울특별시 강남구 대치동` → `서울 강남구 대치동`."""
    if not site:
        return site
    for full, short in _SIDO_SHORT.items():
        if site.startswith(full):
            return short + site[len(full):]
    return site


def zone_ssb(text: str | None) -> str | None:
    """용도지역 → 수협 축약. 주거는 `N종일주`/`N종전주`, 그 외는 `지역` 접미사 제거."""
    name = common.zone_name(text)
    if not name:
        return None
    name = name.strip()
    m = _ZONE_RESIDENTIAL.search(name)
    if m:
        return f"{m.group(1)}종{'일' if m.group(2) == '일반' else '전'}주"
    if name == "준주거지역":
        return "준주거"
    if name.endswith("지역") and ("상업" in name or "공업" in name or "녹지" in name
                                  or "관리" in name or "농림" in name or "자연환경" in name):
        return name[:-2]                          # 일반상업지역 → 일반상업
    return None


def _split_jibun(text: str | None) -> tuple[str | None, str | None]:
    if not text:
        return (None, None)
    match = re.match(r"^\s*(?:산\s*)?(\d+)(?:\s*-\s*(\d+))?", text)
    if not match:
        return (None, None)
    return (match.group(1).lstrip("0") or None, (match.group(2) or "").lstrip("0") or None)


def _block_values(context: DocumentContext, item, is_land: bool):
    """(공부면적, 사정면적, 감정평가액, 단가) — 수협은 일단지 **블록 전체** 값을 쓴다.

    묶음 머리면 공부는 묶음 필지들의 합, 사정·금액·단가는 머리행 값(이미 블록 전체다).
    (실측 2637: head 공부 460 + 소분 262 = 722 = 화면. head 사정 722·금액 220억 그대로.)
    """
    if item is None:
        return (None, None, None, None)
    public, assessed, amount, unit = (
        item.area_public, item.area_assessed, item.amount, item.unit_price)
    if is_land and item.group_head:
        members = _group_members(context.details, item)
        if len(members) > 1:
            summed = sum((m.area_public for m in members if m.area_public is not None),
                         type(public)(0) if public is not None else 0)
            public = summed or public
    return (public, assessed, amount, unit)


def build(context: DocumentContext, seq_no: str | None = None) -> dict[str, str | None]:
    """수협 담보 화면 — 물건 하나(기본은 첫 물건)."""
    outline = context.outline
    jibun = context.jibun
    fee = context.fee
    head = round_parse.first(context.rounds)

    property_rows = tuple(r for r in context.details if r.is_land or r.is_building)
    item = detail.for_sequence(property_rows, seq_no)
    # 집계형(rollup) .gam: 명세에 총액행만 있고 개별 물건(호·면적·감정가)이 없다(실측 2215).
    # 그때 amount 는 건물 전체 합이라 화면의 개별 호 감정평가액과 다르다 → item 금액·면적을
    # 내지 않는다(kookmin 과 같은 규칙). 사람이 개별 호를 넣는다.
    rollup = detail.is_rollup_only(context.details)
    is_land = bool(item and item.kind == detail.UNIT_LAND)
    # 구분건물(section_build)=`집합물건(건물)`, land_list 건물 유닛=`건물`, 토지=`토지`.
    is_section = bool(item and item.is_building)                 # 집합물건(구분건물)
    is_building = bool(item and item.kind == detail.UNIT_BUILDING and not is_section)

    area_public, area_assessed, amount, unit_price = _block_values(context, item, is_land)
    # 집합물건(건물)은 **폼 변형이 다르다**(실폼 1066): 공부/사정면적·용도지역·평가단가 칸이
    # 없고 대신 **`건물면적`**(전용면적)·대지권비율·상세주소 칸이 있다. 그래서 전용면적을
    # `건물면적` 으로 내고 공부/사정/용도/단가는 비운다.
    building_area = _area(area_public) if is_section else None
    item_site = site_address(context, item)

    main_no, sub_no = _split_jibun(item.jibun if item else None)
    if main_no is None and jibun is not None:
        main_no, sub_no = jibun.bun1, jibun.bun2

    # 법정동코드 두 칸으로 분할(시군구 5 + 읍면동 5). 문서 단위 코드라 물건 소재지가
    # 문서 대표와 같을 때만 낸다(농협 legal_code 규칙 재사용).
    code = legal_code(context, item_site)
    code_sgg = code[:5] if (code and len(code) == 10) else None
    code_emd = code[5:] if (code and len(code) == 10) else None

    values: dict[str, str | None] = {
        # 수수료 (기업식 원값 — 할인·부가세보정 없음)
        "순수수료": _money(fee.net),
        "부가세": _money(fee.vat),
        "감정수수료": _money(fee.total),
        "실   비": _money(fee.expense_net),        # 실측 2637=56,000 (부가세 없음)
        "특별용역비": "0",
        # 평가사명 = 감정평가표 서명자(round0.par_player) 우선. 비어 있으면 apw 평가사로
        # 폴백(실측 2637=par_player 유승민 / 1310=par_player 없어 apw 신상우=화면).
        "평가사명": head.appraiser or context.parties.appraiser(0),
        # 물건 — `일련번호` 는 화면 앵커라 쓰지 않는다.
        "기   호": item.seq_no if item else None,
        # 콤보: 토지 / 집합물건(건물)=구분건물 / 건물=land_list 건물유닛 (실측 2609·2637·2660)
        "물건구분코드": ("토지" if is_land else "집합물건(건물)" if is_section
                    else "건물" if is_building else None),
        "번지구분": jibun.jibun_kind if jibun else None,
        "본번지": main_no,
        "부번지": sub_no,
        # 아래 면적·용도·단가는 **토지/일반건물 폼**의 칸. 집합물건 폼엔 없어 비운다.
        "용도지역": None if is_section else (
            zone_ssb(item.zone if (is_land and item) else None) or zone_ssb(outline.zone)),
        "공부면적": None if (is_section or rollup) else _area(area_public),
        "사정면적": None if (is_section or rollup) else _area(area_assessed),
        "건물면적": None if rollup else building_area,   # 집합물건 폼 전용(전용면적)
        # 평가단가는 **토지 물건에서만**(농협 nh.py 와 동일 — 일반건물 화면은 단가 0/공란).
        "평가단가": _money(unit_price) if (is_land and not rollup) else None,
        "감정평가액": None if rollup else _money(amount),
        "등기번호": context.registry_no(
            kind=item.kind if item else None, seq_no=item.seq_no if item else None,
            area=area_public, location=(item.location if item else None),
            jibun=(item.jibun if item else None)),
        "소유지분율": None,                         # 지분 담보 — 소스 미확정(사람/전액)
        "상세주소": None,                           # `외 N필지` — 표기 규칙 확정 TODO
        "감정평가액 결정의견": None,
        # 라벨 없는 칸 (소재지는 시도 축약)
        BOX_SITE: _short_sido(item_site),
        BOX_LEGAL_SGG: code_sgg,
        BOX_LEGAL_EMD: code_emd,
    }
    # 수협 폼엔 건물명·건물구조 칸이 없다(27칸). 넣지 않는다.
    return values
