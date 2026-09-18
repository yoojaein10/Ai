"""기업은행 담보(`TBNKKIB24DAMB`) 필드 매핑.

국민(`kookmin`)과 구조가 비슷하다 — `mullist` 없이 명세표(`land_list`/`section_build`)가
물건 출처다. 다른 점: KB_* 테이블이 없어 소재지·물건종류를 의견서 개요(outline)에서 얻고,
평가금액을 **토지/건물/기계기구/기타**로 나눠 넣는다(기업 폼 특유).

화면 항목명은 실제 폼(TBNKKIB24DAMB)을 읽어 수집. 화면이 바뀌면 이 파일만 고친다.
"""
from __future__ import annotations

import re
import unicodedata
from decimal import ROUND_DOWN, Decimal

from ..codes import common
from ..model import DocumentContext
from ..parse import address, detail

FEE_SURCHARGE_DEFAULT = "미적용"

# 라벨이 없거나 두 칸이 나눠 쓰는 자리 — **위치**로 짚는다(`ui.form.between_labels`).
# 화면값 35건(`recon/ibk_screen.json`)으로 밴드 구성을 확인하고 켰다.
#
#  · `물건종류` 는 **라벨이 둘**이다 — 텍스트칸(단독주택·공장…)과 콤보(대지/건물/국산기계…).
#    `find_by_label` 은 **콤보**를 짚는다(실폼 2683 확인). 매핑값은 텍스트칸용이라 그대로
#    두면 엉뚱한 콤보로 흘러간다 → 위치로 텍스트칸을 직접 짚는다.
#    밴드 `담보구분`~`기준시점` 은 35/35 에서 4칸·같은 순서: 평가사명·순수수료·물건종류·(계산칸).
#  · `소재지` 는 자기 라벨이 없어 위쪽 `일련번호` 라벨을 빌려 쓴다. 밴드 안 순번은 변형마다
#    다르지만(토지형 [2] · 집합건물형 [3]) **가장 왼쪽**이라는 성질은 35/35 에서 유지된다.
#  · `법정동코드` 도 라벨이 없다. 밴드 [0] 이 34/35 — 나머지 1건은 기계·선박 문서라 배치가
#    통째로 다르다(그 칸이 `품 목 명`). 그래서 **부동산 물건일 때만** 낸다(`_REALTY_ONLY`).
BOX_KIND_TEXT = "물건종류@담보구분~기준시점[2]"
BOX_SITE = "소재지@일련번호~번지구분[왼쪽]"
BOX_LEGAL_CODE = "법정동코드@일련번호~번지구분[0]"

# 물건종류 — 의견서 이용상황/주용도를 화면 물건종류로. 확정된 것만 보정한다.
_KIND_MAP = {"공업용": "공장"}          # 실측 6건 일관(2613·2611·2596·2582·2581·2573·2537)

# 화면 물건종류는 **구체적인 물건 이름**(단독주택·공장·오피스텔·숙박시설)이다. 소스가
# 아래 둘 중 하나면 체계가 달라 옮길 수 없다 — 실측 23건에서 틀린 8건이 전부 여기였다.
_USAGE_TERM = re.compile(r"(용|나지|기타)$")   # 이용상황 감정평가 용어: 상업용·공업나지·공업기타
_COMPOUND = re.compile(r"[,()]|및")           # 복합 서술: '주택 및 근린생활시설'


def _property_kind(usage: str | None, building_use: str | None) -> str | None:
    """화면 물건종류. **확신 없으면 비운다**(사람이 고르게 한다).

    비우는 이유 — 이 칸은 콤보가 아니라 텍스트라 자동입력이 그대로 타이핑된다. 틀린 값을
    넣는 것보다 비워 두는 게 안전하다(국민 `kookmin.object_type` 과 같은 원칙).

        단독주택 · 공장 · 전            → 그대로 (실측 15건 화면과 일치)
        공업용                        → 공장   (확정 매핑)
        상업용 · 공업나지 · 공업기타      → 비움   (화면은 숙박시설/근린생활시설/공장/대(垈)
                                                — 같은 소스가 문서마다 다른 값이라 결정 불가)
        '주택 및 근린생활시설'           → 비움   (화면은 그중 하나만 고른다)
        '업무시설(오피스텔), 판매시설…'    → 비움   (화면 '오피스텔')
    """
    source = (usage or building_use or "").strip()
    if not source:
        return None
    if source in _KIND_MAP:
        return _KIND_MAP[source]
    if _COMPOUND.search(source) or _USAGE_TERM.search(source):
        return None
    return source


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


# 화면 콤보에 실제로 있는 항목만 낸다 — 없는 값을 내면 `--select` 가 목록을 다 훑고
# 못 찾아 그 칸이 빈 채로 남는다(틀린 항목을 고르지는 않는다). 목록은 실폼에서 수집한
# `recon/combo_TBNKKIB24DAMB.md` 그대로다.
#
# 농협과 다른 점 둘:
#   · **등급을 살린다** — 기업 콤보는 `제1종일반주거지역` 까지 있다(농협은 대분류만).
#   · 지목이 `대`가 아니라 **`대지`**, `철도용지`가 아니라 **`철도`**, `기타`가 있다.
ZONES = frozenset({
    "제1종전용주거지역", "제2종전용주거지역", "제1종일반주거지역", "제2종일반주거지역",
    "제3종일반주거지역", "준주거지역", "중심상업지역", "일반상업지역", "근린상업지역",
    "유통상업지역", "전용공업지역", "일반공업지역", "준공업지역", "보전녹지지역",
    "생산녹지지역", "자연녹지지역", "보전관리지역", "생산관리지역", "계획관리지역",
    "농림지역", "자연환경보전지역",
})

# 명세표 `JIMOK` 은 칸 폭 때문에 잘려 오기도 한다(`공장용지`→`장`, `주유소용지`→`주유소`).
# 목록에 없으면 비운다.
LAND_CATEGORIES = frozenset({
    "전", "답", "과수원", "목장용지", "임야", "광천지", "염전", "대지", "공장용지",
    "학교용지", "주차장", "주유소용지", "창고용지", "도로", "철도", "하천", "제방",
    "구거", "유지", "양어장", "수도용지", "공원", "체육용지", "유원지", "종교용지",
    "사적지", "묘지", "잡종지", "기타",
})


def zone_grade(text: str | None) -> str | None:
    """용도지역 — 콤보 목록에 있는 것만. `개발제한구역` 같은 용도**구역**은 목록에 없다.

    화면·소스 어느 쪽이든 전각 숫자(`제２종…`)가 섞이므로 반각으로 맞춰 비교한다.
    """
    name = common.zone_name(text)
    if not name:
        return None
    folded = unicodedata.normalize("NFKC", name)
    return folded if folded in ZONES else None


_ZONE_DONE = re.compile(r"(지역|구역|지구)")


def _complete_zone(*candidates: str | None) -> str | None:
    """용도지역 후보 중 **온전한 것**(…지역/구역/지구)을 우선.

    명세표 `YONGDO` 는 세로 줄바꿈으로 잘려 `제2종` 만 잡히는 건이 있다(실측 2546·2561).
    파서가 조각을 이어붙이지만 이어붙일 조각 자체가 없는 문서도 있어 개요로 물러선다.
    """
    for value in candidates:
        if value and _ZONE_DONE.search(value):
            return value
    return next((value for value in candidates if value), None)


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


def _public_area(item, assessed: Decimal | None) -> Decimal | None:
    """화면 `공부면적` — 그 물건(묶음) **전체**의 공부면적.

    묶음머리(일단지)의 `AREA1` 은 머리 필지 몫만 담기도 하고(2531) 묶음 총면적을 담기도
    한다(2412). 화면은 늘 묶음 전체를 원하므로 둘 중 큰 쪽을 쓴다. 묶음이 아니면
    `AREA1` 원값이 답이다(사정보다 클 수 있다 — 차액이 감정평가외).
    """
    if item is None:
        return assessed
    public = item.area_public
    if item.group_head and public is not None and assessed is not None:
        return max(public, assessed)
    return public if public is not None else assessed


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
    merged = False                      # 소분을 합쳤나 — 합쳤으면 단가가 하나가 아니다
    # ⚠️ `is_land`(테이블) 가 아니라 `kind`(블록 머리) 로 가른다 — `land_list` 에 건물 유닛이
    # 섞여 오기 때문이다(실측 2452: 단독주택 3개 층이 land_list 에 있어 is_land=True).
    # 테이블로 가르면 건물 유닛까지 블록 합산해 화면(유닛 하나)과 어긋난다.
    if item and item.kind == detail.UNIT_LAND and not item.group_head:
        block_a = item.area_assessed or Decimal(0)
        block_amt = item.amount or Decimal(0)
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
    # 기업 화면은 구조를 **원문 그대로** 쓴다(실측 2682 화면=`철근콘크리트조`) → to_gujo=False.
    struct = common.best_struct(
        item.struct if item else None, outline.struct,
        item.zone if item else None, to_gujo=False) if is_building else None
    _, unit_no = _floor_ho(item)

    # 기계·선박 전용 문서는 물건 영역 배치가 통째로 다르다(실측: [0] 칸이 `품 목 명`).
    # 그런 건에 순번 기반 위치 표기를 쓰면 **이웃 칸에 타이핑**하게 되므로 아예 안 낸다.
    realty = item_kind in (detail.UNIT_LAND, detail.UNIT_BUILDING)

    return {
        # 물건
        "일련번호": seq_no if (seq_no and str(seq_no).isdigit()) else "1",
        # 라벨이 겹쳐 콤보가 잡히므로 **텍스트칸을 위치로** 짚는다(위 BOX_ 주석).
        # 기계·선박 전용 문서(부동산 명세행이 없다)는 화면이 `국산기계`·`구축물` 처럼
        # 기계 어휘를 쓴다 — 개요의 이용상황으로는 못 낸다(실측 2416: 우리 공장 / 화면 국산기계).
        BOX_KIND_TEXT: (_property_kind(outline.usage, outline.building_use)
                        if realty else None),
        "담보구분": None,                       # 임대차포함 등 — 소스 확정 전 보류(사람 선택)
        # 구분건물 명세표(section_build)면 집합건물, land_list 의 건물 유닛이면 일반 건물.
        "부동산구분": ("토지" if is_land
                    else "집합건물" if (item and item.is_building)
                    else "건물" if item_kind == detail.UNIT_BUILDING else None),
        BOX_LEGAL_CODE: (jibun.legal_code if (jibun and realty) else None),
        # 화면은 시군구까지 받는다("서울특별시 강남구 수서동"). 개요 소재지는 토지 건에서
        # 시도·시군구가 빠지므로(`수서동 461-17`) 본문에서 찾은 완전주소를 먼저 쓴다.
        BOX_SITE: context.site_address or outline.address,
        "번지구분": jibun.jibun_kind if jibun else None,
        "본번지": main_no,
        "부번지": sub_no,
        # 건물 유닛 행에서는 JIMOK/YONGDO 열이 각각 건물용도·건물구조라 지목·용도지역이
        # 아니다(실측 2452: 지목칸='단독주택', 용도지역칸='철근'). 토지 물건에서만 쓴다.
        "공부지목": (common.land_category(item.category, LAND_CATEGORIES)
                  if (is_land and item and item.category) else None),
        # 명세표 값이 줄바꿈으로 잘렸으면(제2종…) 개요의 온전한 값으로 물러선다.
        "용도지역": zone_grade(
            _complete_zone(item.zone if (is_land and item) else None, outline.zone)),
        # 기업 화면은 공부면적=사정면적(일단지 총면적)이 항상 성립(실측 13건). 일단지면
        # head 필지 공부(item.area_public)가 아니라 블록합산(item_assessed)을 써야 맞는다.
        # 집합건물 상세 — 화면 라벨은 실폼(TBNKKIB24DAMB)에서 읽었다.
        # `동/호` 는 라벨 하나에 칸이 둘(동·호)이라 라벨로는 호를 못 짚는다 →
        # 위치기반 타겟팅 전까지 사람이 넣는다(우리 값은 아래 비고로만 남긴다).
        "건 물 명": address.building_name(outline.address),
        "건물구조": struct,
        "준공일자": outline.approval_date if is_building else None,
        # 건물 물건은 전용면적 칸을 쓴다. 두 칸은 **폼 변형마다 하나씩만** 있다
        # (토지형 32칸엔 `공부면적`, 건물형 37칸엔 `공부면적(전용면적)`) — 그래서
        # 물건 종류로 갈라 내면 그 폼에 있는 칸만 채우게 된다. 여기서도 테이블이 아니라
        # `kind` 를 본다(실측 2452: land_list 에 실린 단독주택도 건물형 폼이다).
        "공부면적(전용면적)": _area(item.area_public) if (is_building and item) else None,
        # 폼이 물건 종류에 따라 바뀐다 — 토지 건엔 `공부면적`, 구분건물 건엔
        # `공부면적(전용면적)` 만 있다(실폼 2683=32칸 / 2526=37칸).
        # 공부면적은 명세 AREA1 원값이다. 사정과 다를 수 있다(실측 2561 공부 277.70 /
        # 사정 267.75 — 차액 9.95 는 감정평가외 부분).
        # **묶음머리(일단지)** 의 AREA1 은 두 가지다 — 머리 필지 몫만 담기도 하고
        # (실측 2531: AREA1 1,428 / 블록합 2,906) 묶음 총 공부면적을 담기도 한다
        # (실측 2412: AREA1 3,181 / 사정 3,144.2, 차액은 감정평가외). 화면은 늘
        # **묶음 전체의 공부면적**을 원하므로 둘 중 **큰 쪽**이다.
        "공부면적": None if is_building else _area(_public_area(item, item_assessed)),
        "사정면적": _area(item_assessed),
        # 소분을 합친 물건은 단가가 하나가 아니다 — 화면도 0으로 둔다(실측 2516).
        "평가단가": _money(item.unit_price if (item and not merged) else None),
        "감정평가액": _money(item_amount),
        "총감정평가액": _money(context.total_amount),
        # 평가금액 분리(기업 특유). 없는 쪽은 0(화면도 0으로 표시).
        "토지평가금액": _money(land_amt),
        "건물평가금액": _money(build_amt),
        "기계기구평가금액": _money(machine_amt),
        "기타평가금액": _money(etc_amt),
        "등기소기준 고유번호": context.registry_no(
            kind=item_kind, seq_no=item.seq_no if item else None),
        # 작성자 — 기업 폼에는 **심사자 칸이 없다**(실폼 확인: 토지 32칸·구분건물 37칸
        # 어디에도 없음). 국민과 달라 넣지 않는다.
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
