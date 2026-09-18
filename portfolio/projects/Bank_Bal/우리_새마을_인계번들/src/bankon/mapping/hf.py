"""주택도시보증공사(HUG) 담보(`TBNKHUG24DAMB`) 필드 매핑.

농협(`nh`)과 가장 닮았다 — `mullist` 없이 명세표(`land_list`/`section_build`)가 물건
출처이고, 표준지·건물명/동/호·라벨 없는 소재지/법정동코드를 쓴다. 그래서 농협의 검증된
헬퍼(소재지·법정동·건물명·면적·층호·표준지·지목·용도지역)를 그대로 재사용한다.

농협과 다른 점:
  · **폼이 한 종류**다(동적 변형이 없다 — 46칸 폼 하나에 토지·건물 칸이 다 있다).
    물건이 토지면 건물 칸을, 건물이면 토지 칸을 비운다(fill-empty-only 라 안전).
  · 평가금액을 **나누지 않는다** — 화면은 `감정가액`(물건별) · `총감정평가액`(문서) 둘뿐.
    (기업의 토지/건물/기계 4분리가 없다.)
  · **수수료 할인 블록이 없다** — 순수수료·부가세·감정수수료·실비를 기업처럼 그대로.
  · HUG 고유 콤보 4칸(감정구분·할증할인여부·감정기관정산여부·수수료환불구분)은 소스가
    확정 안 돼 **비운다**(사람 선택). 정산수수료금액도 문서마다 달라 비운다.
  · **문서 종류가 둘**이다(실측 30건):
        HUG 인정 감정평가  purpose=`기타 담보`   — 정식 감정(의견서/명세 있음, ~80%)
        임대보증금보증 등    purpose=`HUG(시가참고)` — 경량 추출(의견서 없음)
    경량 건은 건물구조·준공일자·전용면적·표준지가 소스에 아예 없다 → 그 칸만 비고
    나머지(수수료·금액·주소·등기)는 그대로 채운다.

화면 항목명은 실폼(`recon/fields_TBNKHUG24DAMB.md`, `recon/hug_screen.json`)에서 읽었다.
"""
from __future__ import annotations

import re

from ..codes import common
from ..model import DocumentContext
from ..parse import detail
# 농협에서 검증된 헬퍼를 그대로 쓴다(한 곳에만 두어 규칙이 갈리지 않게).
from .nh import (
    _area,
    _floor_ho_dong,
    _item_values,
    _money,
    building_name,
    land_category,
    legal_code,
    site_address,
    zone_grade,
    _item_zone,
)

# 라벨이 없는 칸 — 실폼(0298)에서 값으로 확인했다. 위치 밴드는 실측을 더 쌓아 확정할
# 예정이라(농협은 14건으로 확정), 일단 값만 내고 verify 단계에서 위치로 짚는다.
#   소재지     TcxDBTextEdit  "서울특별시 금천구 가산동"
#   법정동코드  TcxDBTextEdit  "1154510100"
BOX_SITE = "소재지@본번~부번[소재지]"
BOX_LEGAL_CODE = "법정동코드@본번~부번[법정동]"


def build(context: DocumentContext, seq_no: str | None = None) -> dict[str, str | None]:
    """HUG 담보 화면 — 물건 하나(기본은 첫 물건)."""
    outline = context.outline
    jibun = context.jibun
    parties = context.parties
    fee = context.fee
    standard = context.standard_land

    property_rows = tuple(r for r in context.details if r.is_land or r.is_building)
    item = detail.for_sequence(property_rows, seq_no)
    is_land = bool(item and item.kind == detail.UNIT_LAND)
    is_building = bool(item and item.kind == detail.UNIT_BUILDING)

    area_public, area_assessed, amount = _item_values(context, item, is_land)
    item_site = site_address(context, item)

    floor_no, unit_no, dong_no = _floor_ho_dong(item, context)
    main_no, sub_no = _split_jibun(item.jibun if item else None)
    if main_no is None and jibun is not None:
        main_no, sub_no = jibun.bun1, jibun.bun2

    # 화면 `물건종류` 콤보는 토지/건물(실측 0298=건물). 명세 블록 머리(kind)로 낸다.
    kind_combo = item.kind if item else None                      # 토지 / 건물

    values: dict[str, str | None] = {
        # 수수료·머리 (gam_info 원시값 — 기업식, 할인 없음)
        "건 명": None,                       # 의뢰건명 — BANK24 가 의뢰정보에서 자동입력
        "감정구분": None,                     # 임대차미포함 등 — 소스 미확정(사람 선택)
        "감정수수료": _money(fee.total),
        "기준시점": context.price_point_date,
        "부가세": _money(fee.vat),
        "작성일자": context.price_point_date,   # 실측 0298: 작성일자=기준시점=2026-08-31
        "순수수료": _money(fee.net),
        "평가사성명": parties.appraiser(0),
        "총감정평가액": _money(context.total_amount),
        "실비": _money(fee.expense_net),        # 부가세 없는 구성항목 합(실측 0298=50,000)
        "특별용역비": "0",
        "할증할인여부": None,                  # HUG 수수료 콤보 — 소스 미확정(사람 선택)
        "감정기관정산여부": None,
        "수수료환불구분": None,
        "정산수수료금액": None,                # 문서마다 달라 비운다
        # 물건 — `물건일련번호` 는 화면 앵커라 쓰지 않는다(다물건 순번 어긋남 방지).
        "물건일련번호": None,
        "용 도": None,                        # 은행 분류 콤보(아파트/오피스텔) — 소스에서 못 냄
        "물건종류": kind_combo,               # 토지 / 건물
        "번지구분": jibun.jibun_kind if jibun else None,
        "본번": main_no,
        "부번": sub_no,
        "감정가액": _money(amount),
        "단 가": _money(item.unit_price if (item and is_land) else None),
        "등기고유번호": context.registry_no(
            kind=item.kind if item else None, seq_no=item.seq_no if item else None,
            area=area_public, location=(item.location if item else None),
            jibun=(item.jibun if item else None)),
        "건축물대장고유번호": None,            # 건축물대장 스캔 미보유 — 사람 입력
        "비고": None,
        # 라벨 없는 칸 — 위치로 짚는다(verify 단계에서 확정)
        BOX_SITE: item_site,
        BOX_LEGAL_CODE: legal_code(context, item_site),
        # 표준지 — 비교표준지표가 있는 건만(경량 건은 비어 있음)
        "표준지소재지": standard.address,
        "표준지공시지가": _money(standard.price),
        "표준지공시기준일": standard.base_date,
    }

    # 토지 물건 칸
    if is_land:
        values.update({
            "공부상지목": land_category(item.category if item else None),
            "사정지목": land_category(item.category if item else None),
            "용도지역": zone_grade(_item_zone(item, outline)),
            "공부면적": _area(area_public),
            "사정면적": _area(area_assessed),
        })
    else:
        # 집합건물/일반건물 — 공부면적=전용면적(AREA1), 사정면적(AREA2)
        values.update({
            "공부상지목": None,
            "사정지목": None,
            "용도지역": None,
            "공부면적": _area(area_public),
            "사정면적": _area(area_assessed),
        })

    # 건물 물건 칸(경량 건은 소스가 없어 자동으로 None)
    if is_building:
        values.update({
            "건물명": building_name(context, item),
            "동": dong_no,
            "호": unit_no,
            "건물구조": common.best_struct(
                item.struct if item else None, outline.struct, to_gujo=False),
            "준공일자": outline.approval_date,
            "내용연수": None,                 # 실측 화면 0 — 소스 없음(사람)
            "잔존연수": None,
        })
    else:
        values.update({
            "건물명": None, "동": None, "호": None, "건물구조": None,
            "준공일자": None, "내용연수": None, "잔존연수": None,
        })

    return values


def _split_jibun(text: str | None) -> tuple[str | None, str | None]:
    """명세행 지번 `299-2` → (본번 299, 부번 2)."""
    if not text:
        return (None, None)
    match = re.match(r"^\s*(?:산\s*)?(\d+)(?:\s*-\s*(\d+))?", text)
    if not match:
        return (None, None)
    return (match.group(1).lstrip("0") or None, (match.group(2) or "").lstrip("0") or None)
