"""기업은행 담보(`TBNKKIB24DAMB`) 필드 매핑.

국민(`kookmin`)과 구조가 비슷하다 — `mullist` 없이 명세표(`land_list`/`section_build`)가
물건 출처다. 다른 점: KB_* 테이블이 없어 소재지·물건종류를 의견서 개요(outline)에서 얻고,
평가금액을 **토지/건물/기계기구/기타**로 나눠 넣는다(기업 폼 특유).

화면 항목명은 실제 폼(TBNKKIB24DAMB)을 읽어 수집. 화면이 바뀌면 이 파일만 고친다.
"""
from __future__ import annotations

import re
from decimal import ROUND_DOWN, Decimal

from ..codes import common
from ..model import DocumentContext
from ..parse import address, detail

FEE_SURCHARGE_DEFAULT = "미적용"

# 물건종류 — 이용상황(outline.usage)을 화면 물건종류로. 대부분 그대로지만 확정 매핑만 보정.
# ('공업용'→'공장'은 5건+ 일관. 상업용→숙박/근생 등은 문서마다 달라 매핑 못 함 → 그대로.)
_KIND_MAP = {"공업용": "공장"}


def _property_kind(usage: str | None, building_use: str | None) -> str | None:
    source = usage or building_use
    if not source:
        return None
    return _KIND_MAP.get(source.strip(), source)


def _money(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.quantize(Decimal(1)) if value == value.to_integral() else value, "f")


def _area(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.quantize(Decimal("0.01"), rounding=ROUND_DOWN), "f")


def split_jibun(text: str | None) -> tuple[str | None, str | None]:
    if not text:
        return (None, None)
    match = re.match(r"^\s*(?:산\s*)?(\d+)(?:\s*-\s*(\d+))?", text)
    if not match:
        return (None, None)
    return (match.group(1).lstrip("0") or None, (match.group(2) or "").lstrip("0") or None)


_FLOOR_HO = re.compile(r"제\s*(\d+)\s*층\s*제\s*([0-9A-Za-z가-힣][0-9A-Za-z가-힣\-]*)\s*호")


def _floor_ho(item) -> tuple[str | None, str | None]:
    """(해당 층, 호) — 구분건물 명세행의 `제7층 제703호` 에서. 토지·일반건물은 (None, None).

    `parse.detail._section_build_objects` 가 유닛의 층/호 표기를 `location` 에 담아 준다.
    """
    for text in ((item.location, item.note, item.struct) if item else ()):
        match = _FLOOR_HO.search(text or "")
        if match:
            return match.group(1), match.group(2)
    return (None, None)


def _following_subrows(details, item):
    """필지 head 뒤의 seq_no=None 소분행(다음 필지 전까지) — kookmin 과 동일 규칙."""
    idx = next((i for i, row in enumerate(details) if row is item), None)
    if idx is None:
        return
    for row in details[idx + 1:]:
        if row.seq_no is not None:
            return
        yield row


def _amounts_by_kind(details) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """물건행 금액을 (토지, 건물, 기계기구, 기타)로 나눈다.

    기계=detail_machin. 기타=선박·차량·동산 등(app_ship/detail_ship/movables/car). 둘 다
    부동산(land_list/section_build)이 아니다. 부동산은 **명세 블록 머리**(`row.kind`)로
    가른다 — 토지 명세표는 필지를 숫자로, 그 지상 건물을 한글 한 글자로 번호매기고,
    금액행은 머리에서 종류를 물려받는다(`parse.detail._unit_kind_of`).

    ⚠️ 예전엔 지목 문자열에 토지 지목이 들어 있는지로 갈랐는데, 금액행에는 지목 칸이
       비어 있는 경우가 62%라 대부분 건물로 흘렀다(실측 2516: NO=1 '대' 필지의 접도구역
       소분행 111,780,000 이 토지인데 건물로 집계). 블록 머리 기준이 정확하다.

        실측 2531: 토지 3,283,780,000 · 건물 425,487,100 · 기계 69,400,000
        실측 2471: 모터보트 552,232,000 = 기타
    """
    land = building = machine = etc = Decimal(0)
    for row in details:
        if row.amount is None:
            continue
        if row.table.lower().startswith("detail_machin"):
            machine += row.amount
        elif not row.is_land and not row.is_building:
            etc += row.amount                   # 선박·차량·동산 = 기타
        elif row.kind == detail.UNIT_BUILDING:
            building += row.amount
        else:
            land += row.amount
    return land, building, machine, etc


def build(context: DocumentContext, seq_no: str | None = None) -> dict[str, str | None]:
    """기업은행 담보 화면 — 물건 하나(기본은 첫 물건)."""
    outline = context.outline
    jibun = context.jibun
    parties = context.parties
    fee = context.fee
    # 물건①은 토지/건물(주물건)에서 고른다 — 기계기구(detail_machin)는 별도 평가금액 칸으로
    # 빠지므로 물건순번 대상이 아니다(실측 2531: 기계가 첫 행이라 안 걸러내면 물건①로 오선택).
    property_rows = tuple(r for r in context.details if r.is_land or r.is_building)
    item = detail.for_sequence(property_rows, seq_no)

    # 토지 소분 블록 합산(일단지 아니면) — kookmin 과 동일.
    item_assessed = item.area_assessed if item else None
    item_amount = item.amount if item else None
    if item and item.is_land and not item.group_head:
        block_a = item.area_assessed or Decimal(0)
        block_amt = item.amount or Decimal(0)
        merged = False
        for row in _following_subrows(context.details, item):
            if row.amount is not None:
                block_a += row.area_assessed or Decimal(0)
                block_amt += row.amount
                merged = True
        if merged:
            item_assessed, item_amount = block_a, block_amt

    main_no, sub_no = split_jibun(item.jibun if item else None)
    if main_no is None and jibun is not None:
        main_no, sub_no = jibun.bun1, jibun.bun2

    land_amt, build_amt, machine_amt, etc_amt = _amounts_by_kind(context.details)
    # 물건 실제 종류 — 테이블이 아니라 명세 블록 머리 기준(land_list 에 건물이 섞인다).
    item_kind = item.kind if item else None
    is_land = item_kind == detail.UNIT_LAND
    is_section = bool(item and item.is_building)          # 구분건물(section_build)
    is_building = item_kind == detail.UNIT_BUILDING
    # 건물 유닛에서는 명세표 `YONGDO` 열이 용도지역이 아니라 **구조**다. 다만 세로
    # 줄바꿈으로 조각나므로(2452 '철근') 의견서 개요의 완전값을 우선한다.
    # 물건이 건물일 때만 채운다 — 기계·선박 전용 문서(2416)까지 개요 구조가 새면 안 된다.
    struct = common.best_struct(
        item.struct if item else None, outline.struct,
        item.zone if item else None) if is_building else None
    _, unit_no = _floor_ho(item)

    return {
        # 물건
        "일련번호": seq_no if (seq_no and str(seq_no).isdigit()) else "1",
        "물건종류": _property_kind(outline.usage, outline.building_use),
        "담보구분": None,                       # 임대차포함 등 — 소스 확정 전 보류(사람 선택)
        # 구분건물 명세표(section_build)면 집합건물, land_list 의 건물 유닛이면 일반 건물.
        "부동산구분": ("토지" if is_land
                    else "집합건물" if (item and item.is_building)
                    else "건물" if item_kind == detail.UNIT_BUILDING else None),
        "법정동코드": jibun.legal_code if jibun else None,
        # 화면은 시군구까지 받는다("서울특별시 강남구 수서동"). 개요 소재지는 토지 건에서
        # 시도·시군구가 빠지므로(`수서동 461-17`) 본문에서 찾은 완전주소를 먼저 쓴다.
        "소재지": context.site_address or outline.address,
        "번지구분": jibun.jibun_kind if jibun else None,
        "본번지": main_no,
        "부번지": sub_no,
        # 건물 유닛 행에서는 JIMOK/YONGDO 열이 각각 건물용도·건물구조라 지목·용도지역이
        # 아니다(실측 2452: 지목칸='단독주택', 용도지역칸='철근'). 토지 물건에서만 쓴다.
        "공부지목": (common.land_category(item.category)
                  if (is_land and item and item.category) else None),
        "용도지역": ((item.zone if (is_land and item) else None) or outline.zone),
        # 기업 화면은 공부면적=사정면적(일단지 총면적)이 항상 성립(실측 13건). 일단지면
        # head 필지 공부(item.area_public)가 아니라 블록합산(item_assessed)을 써야 맞는다.
        # 집합건물 상세 — 화면 라벨은 실폼(TBNKKIB24DAMB)에서 읽었다.
        # `동/호` 는 라벨 하나에 칸이 둘(동·호)이라 라벨로는 호를 못 짚는다 →
        # 위치기반 타겟팅 전까지 사람이 넣는다(우리 값은 아래 비고로만 남긴다).
        "건 물 명": address.building_name(outline.address),
        "건물구조": struct,
        "준공일자": outline.approval_date if is_building else None,
        # 구분건물만 전용면적 칸을 쓴다(토지 건은 화면도 비어 있다).
        "공부면적(전용면적)": _area(item.area_public) if (is_section and item) else None,
        "공부면적": _area(item_assessed),
        "사정면적": _area(item_assessed),
        "평가단가": _money(item.unit_price if item else None),
        "감정평가액": _money(item_amount),
        "총감정평가액": _money(context.total_amount),
        # 평가금액 분리(기업 특유). 없는 쪽은 0(화면도 0으로 표시).
        "토지평가금액": _money(land_amt),
        "건물평가금액": _money(build_amt),
        "기계기구평가금액": _money(machine_amt),
        "기타평가금액": _money(etc_amt),
        "등기소기준 고유번호": context.registry_no(
            kind=item_kind, seq_no=item.seq_no if item else None),
        # 작성자
        "심사자": parties.reviewer,
        "평가사명": parties.appraiser(0),
        # 수수료 (gam_info 원시값). 실비는 부가세 없이 구성항목 합(실측 2683=69,900).
        "순수수료": _money(fee.net),
        "부가세": _money(fee.vat),
        "감정수수료": _money(fee.total),
        "실   비": _money(fee.expense_net),
        "특별용역비": "0",
        "기준시점": context.price_point_date,
        "비  고": None,
    }
