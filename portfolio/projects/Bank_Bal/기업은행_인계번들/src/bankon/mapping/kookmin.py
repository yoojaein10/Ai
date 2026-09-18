"""국민은행 담보(`TBNKKBB24DAMB`) 필드 매핑.

신한과 다른 점:
  - 법정동코드를 **10자리 한 칸**으로 받는다(신한은 REG/EUB 두 칸)
  - 등기번호가 **하나**다(신한은 토지/건물 분리)
  - `mullist` 가 없다 → 담보종류·담보용도 같은 은행 코드 자체가 없고,
    대신 `물건종류` 콤보와 `평가방법` 라디오를 쓴다
  - 점검항목 20개는 전부 `아니오`(기본값 유지)

화면 항목명은 `recon/fields_kb_damb.md` 에서 실제 화면을 읽어 수집했다.
"""
from __future__ import annotations

import re
from decimal import ROUND_DOWN, Decimal

from ..model import DocumentContext
from ..codes import common
from ..parse import detail
from ..parse.cost import representative

CHECKLIST_ANSWER = "아니오"      # 점검항목 기본값 — KB_Summary_Chk 가 없을 때만 쓴다
CHECKLIST_COUNT = 20            # a1~a12 + b1~b5 + c1~c3
FEE_SURCHARGE_DEFAULT = "미적용"  # 수수료할증적용

# 평가방법 라디오 — 원가법 산출표가 있으면 원가평가, 없으면 거래사례.
METHOD_COST = "구분소유외물건(원가평가(복성식))"
METHOD_COMPARISON = "구분소유물건(거례사례)"

# 물건종류 라디오(토지/건물/기계기구) — 명세 유형에서 정한다.
OBJECT_LAND = "토지"
OBJECT_BUILDING = "건물"
OBJECT_MACHINE = "기계기구"


def _money(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.quantize(Decimal(1)) if value == value.to_integral() else value, "f")


def _plain(value: Decimal | None) -> str | None:
    return None if value is None else format(value.normalize(), "f")


def _int(value: int | None) -> str | None:
    return None if value is None else str(value)


def split_jibun(text: str | None) -> tuple[str | None, str | None]:
    """명세행 지번 `299-2` → (본번 299, 부번 2).

    `apw_masterex` 의 BUN1/BUN2 는 문서 **대표 지번**이라 물건이 여러 개면 어긋난다.
    명세행에 지번이 있으면 그쪽이 정확하다(실측: 화면 본번 299/부번 2 = 명세행 299-2).
    """
    if not text:
        return (None, None)
    match = re.match(r"^\s*(?:산\s*)?(\d+)(?:\s*-\s*(\d+))?", text)
    if not match:
        return (None, None)
    main = match.group(1).lstrip("0") or None
    sub = (match.group(2) or "").lstrip("0") or None
    return (main, sub)


def _area(value: Decimal | None) -> str | None:
    """면적은 소수 2자리 고정 + 버림(화면 표기와 같다)."""
    if value is None:
        return None
    return format(value.quantize(Decimal("0.01"), rounding=ROUND_DOWN), "f")


# 구조 표기 정규화는 은행 공통이라 `codes.common` 으로 옮겼다(기업도 쓴다).
_struct_only = common.struct_only
_best_struct = common.best_struct


def _address_only(text: str | None) -> str | None:
    """화면 `소재지` 칸에 맞춘 형태 — **동(리)까지만**.

    지번은 `본번지`/`부번지` 칸에 따로 들어가므로 소재지에서는 뗀다.
    `[도로명주소] …` 꼬리와 `외 19필지` 같은 꼬리도 함께 정리한다.

        KB_Summary.addr  경기도 이천시 마장면 양촌리 299-8외 19필지
        화면 소재지        경기도 이천시 마장면 양촌리
    """
    if not text:
        return None
    head = re.split(r"\[도로명주소\]", text)[0].strip()
    # 마지막 행정동(…동/리/가) 까지만 남긴다.
    # 탐욕 매칭 — 마지막 행정동까지 잡는다(비탐욕이면 `마장면` 에서 멈춘다).
    match = re.match(r"^(.*[동리가읍면])(?=\s|$)", head)
    if match:
        return match.group(1).strip()
    # 행정동 표기가 없으면 지번(숫자-숫자) 앞까지.
    return re.split(r"\s+\d", head)[0].strip() or None


def _floor_no(address: str | None) -> str | None:
    """`제3층 제301호` 에서 해당 층(3)."""
    if not address:
        return None
    match = re.search(r"제\s*(\d+)\s*층", address)
    return match.group(1) if match else None


def _unit_no(address: str | None) -> str | None:
    """`제3층 제301호` 에서 호(301)."""
    if not address:
        return None
    match = re.search(r"제\s*([0-9가-힣\-]+)\s*호", address)
    return match.group(1) if match else None


# 건물명 뒤에 오는 동/층/호 표시 — 여기서부터는 건물명이 아니다(동·호 칸에 따로 들어감).
_NAME_STOP = (
    r"제?\s*[0-9A-Za-z가-힣]{1,3}\s*동"          # 동 표시(3동·씨동=C동)
    r"|제?\s*\d+\s*층"                          # 층(제1층·8층)
    r"|제?\s*[0-9A-Za-z가-힣][0-9A-Za-z가-힣\-]*\s*호"   # 호(704-1호·118호·F0306호)
)
_BUILDING_NAME = re.compile(
    r"\d[\d\-]*\s+(?:외\s+)?"                    # 지번(+다물건 '외')
    r"(?P<name>\S.*?\S|\S)"                     # 건물명(최소 1자, 내부 공백 허용)
    r"(?=\s+(?:" + _NAME_STOP + r"))"           # 첫 동/층/호 앞에서 멈춘다
)


def _building_name(context: DocumentContext) -> str | None:
    """구분건물 소재지(`KB_Summary.addr`)에서 건물명만 떼어낸다.

    addr 은 `…동 <지번> [외] <건물명> [<동>] [<층>] <호>…` 꼴이다. 건물명은 지번(+다물건
    '외') 뒤부터 **첫 동/층/호 표시 앞**까지다. 동/층/호는 동·호 칸에 따로 들어가므로 뗀다.
    다물건이면 addr 이 `…외 <건물명> 제1층 제118호 외 제1층 제119호` 처럼 이어지지만 첫
    동/층/호에서 끊으므로 건물명만 남는다. 건물(호) 표시가 없으면(토지) None → 빈값.

        군포 당정동 1128 신라테크노빌   704-1호            → 신라테크노빌
        의왕 포일동 653 인덕원아이티밸리  씨동 8층 808호      → 인덕원아이티밸리
        은평 수색동 75 외 디엠씨 자이1단지 제1층 제118호 외… → 디엠씨 자이1단지
        안산 상록구 팔곡이동 368-18외 373-6                → None (토지)
    """
    addr = context.kb_summary.address
    if not addr:
        return None
    match = _BUILDING_NAME.search(addr)
    return match.group("name").strip() or None if match else None


_FLOOR_HO = re.compile(r"제\s*(\d+)\s*층\s*제\s*([0-9가-힣\-]+?)\s*호")
_TAIL_HO = re.compile(r"([0-9]+(?:-[0-9]+)?)\s*호\s*$")


def _floor_ho(context: DocumentContext, item) -> tuple[str | None, str | None]:
    """(건물 층수, 호) 회수 — 명세표 `제7층 제704-1호` 우선, 없으면 소재지 끝 `…호`.

    토지·다필지(층/호 없음)는 (None, None). 다물건은 해당 물건순번 행을 먼저 본다.
    """
    rows = context.details or ()
    # item 자신을 맨 앞에 둔다 — 다물건에서 유닛부호(seq_no='가')가 겹쳐도 그 물건의
    # 층/호(location)를 먼저 집도록(1752: 김포·고양 둘 다 '가'라 안 그러면 첫 호만 집힘).
    ordered = ([item] if item else []) \
        + [r for r in rows if item and r.seq_no == item.seq_no] + list(rows)
    for r in ordered:
        for f in (r.struct, r.location, r.category, r.note):
            if f:
                m = _FLOOR_HO.search(f)
                if m:
                    return m.group(1), m.group(2)
    addr = context.kb_summary.address
    if addr:
        m = _TAIL_HO.search(addr.strip())
        if m:
            return None, m.group(1)
    return None, None


# 부가세·총액은 순수수료를 **1,000원 단위로 버린 금액**을 기준으로 계산한다(실측).
#   4,322,455 → 4,322,000 → 부가세 432,200 → 총액 4,754,200
#   1,838,000 → 1,838,000 → 부가세 183,800 → 총액 2,021,800
FEE_BASE_UNIT = Decimal(1000)


def _fee_base(net: Decimal | None) -> Decimal | None:
    if net is None:
        return None
    return (net // FEE_BASE_UNIT) * FEE_BASE_UNIT


def _vat_of(net: Decimal | None) -> Decimal | None:
    """국민 화면의 부가세 — gam_info TAX 가 아니라 절사한 순수수료의 10%."""
    base = _fee_base(net)
    return None if base is None else (base * Decimal("0.1")).quantize(Decimal(1))


def _with_vat(net: Decimal | None) -> Decimal | None:
    """감정평가(순)수수료 총액 = 절사한 순수수료 + 부가세."""
    base, vat = _fee_base(net), _vat_of(net)
    return None if base is None or vat is None else base + vat


def appraisal_method(context: DocumentContext) -> str:
    """원가법 산출표가 있으면 원가평가로 본다(실측 담보 33%)."""
    return METHOD_COST if context.cost_layers else METHOD_COMPARISON


def object_type(context: DocumentContext, item) -> str | None:
    """`물건종류` **콤보**(114개) — 라디오와 별개다.

    ⚠️ 지목으로 유추해봤지만 신뢰할 수 없다 — 명세표가 토지뿐인 문서인데 화면은
    `일반상가-근린(점포)상가` 인 사례가 있었다(01-2606-3-1887). 반대로 순수 토지
    문서는 `답` 으로 맞았다(01-2607-3-2418). 규칙이 확정되기 전까지는 **비워두고**
    사람이 고르게 한다 — 틀린 값을 넣는 것보다 안전하다.
    """
    return None


def object_kind(context: DocumentContext) -> str | None:
    """물건종류 **라디오**(토지/건물/기계기구). 콤보와 다르다."""
    if context.has_mullist:
        first = context.properties[0].object_kind
        if first in (OBJECT_LAND, OBJECT_BUILDING, OBJECT_MACHINE):
            return first
    if context.outline.struct:
        return OBJECT_BUILDING
    if context.outline.category:
        return OBJECT_LAND
    return None


def _address(context: DocumentContext) -> str | None:
    """소재지 — `KB_Summary.addr` 가 가장 깔끔하다.

    `land_list` 의 주소는 `경기도`/`이천시`/`마장면` 처럼 계층 행으로 쪼개져 있어
    조합이 필요하지만, `KB_Summary.addr` 는 완성된 문자열이다.
    """
    first = context.properties[0] if context.has_mullist else None
    return (context.kb_summary.address
            or (first.address if first else None)
            or context.outline.address)


def checklist_answers(context: DocumentContext) -> tuple[str, ...]:
    """점검항목 20개 — 화면 위→아래 순서. 값이 없으면 기본값으로 채운다."""
    stored = context.kb_checks or ()
    return tuple(
        (stored[index] if index < len(stored) and stored[index] else CHECKLIST_ANSWER)
        for index in range(CHECKLIST_COUNT)
    )


def _following_subrows(details, item):
    """item(필지 head) 바로 뒤의 seq_no=None 소분행들을 준다(다음 필지 head 전까지).

    land_list 는 한 필지의 도로저촉·저가부분 등을 head 뒤 seq_no=None 행으로 잇는다.
    """
    idx = next((i for i, row in enumerate(details) if row is item), None)
    if idx is None:
        return
    for row in details[idx + 1:]:
        if row.seq_no is not None:      # 다음 필지 시작 → 블록 끝
            return
        yield row


def build(context: DocumentContext, seq_no: str | None = None) -> dict[str, str | None]:
    """국민은행 담보 화면 — 물건 하나(기본은 첫 물건).

    국민은 `mullist` 가 없어 **명세표(`land_list`/`section_build`)** 가 물건별
    값의 출처다. 명세행이 있으면 그쪽을 우선하고, 없을 때만 의견서 개요로 물러선다.
    """
    outline = context.outline
    jibun = context.jibun
    parties = context.parties
    fee = context.fee
    account = context.account
    standard = context.standard_land
    cost = representative(context.cost_layers)
    first = context.properties[0] if context.has_mullist else None
    item = detail.for_sequence(context.details, seq_no)
    # 집계형(rollup) .gam: 명세에 총액행만 있고 개별 물건(호·면적·감정가)이 없다
    # (round0_memo='집계명세표…', 개별명세는 별도 자식문서에만). 총액을 물건값으로
    # 오기입하지 않도록 item 을 비워 자동입력을 멈추고 수기 입력으로 넘긴다.
    rollup_only = (detail.is_rollup_only(context.details)
                   and "개호" in (context.kb_summary.address or ""))
    if rollup_only:
        item = None
    # 토지 명세 '묶음괄호' 머리행(AREA1RB='<')은 AREA2(사정)/PRICE(평가액)가
    # '묶음 합계'라 물건 고유값이 아니다. 물건 고유값 = 공부면적(AREA1)과
    # 공부면적×평가단가(실측 0668: 895→749, 22.3억→18.6억).
    item_assessed = item.area_assessed if item else None
    item_amount = item.amount if item else None
    # 토지 '소분 블록 합산': 필지 head + 뒤따르는 seq_no=None valued 소분행(도로저촉·
    # 저가부분 등, 다음 필지 전까지)의 AREA2/PRICE 를 합쳐 화면 사정/감정을 만든다
    # (실측 1258 396+44=440·1258 PRICE합, 0358 3310+4240=7550). 단, 일단지(AREA1 묶음
    # =group_head)면 head 필지 단독이 그 물건 값이라 합산하지 않는다(실측 1344·0033·0663
    # ·0916 화면=head raw AREA2). 0668형(등기 합병으로 head=AREA1)은 공부스캔이 있어야
    # 판별 가능해 .gam 만으론 못 잡는 잔여 케이스다.
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
    # 집계형: 명세표가 총액/비준가액만 담고 개별 물건은 KB_Con·gam_info.price 에 있다.
    con_usable = [c for c in context.con if not c.aggregated and c.amount is not None]
    anchors = [row for row in context.details if row.amount is not None]
    total = context.total_amount
    if (item and not rollup_only and len(con_usable) >= 2
            and item.amount is not None and item.amount == total):
        # 1214형: 명세앵커=문서총액(개별물건 없음), 개별물건은 KB_Con → 화면 순번으로 선택.
        cidx = (int(seq_no) - 1) if (seq_no and seq_no.isdigit()) else 0
        if 0 <= cidx < len(con_usable):
            con_item = con_usable[cidx]
            item_amount = con_item.amount
            if con_item.area is not None:
                item_assessed = con_item.area
    elif (item and not rollup_only and item.is_building and len(anchors) == 1
          and total is not None and item.amount is not None and item.amount != total):
        # 1563형: section_build 단일앵커가 비준가액(≠총액)이면 실제 감정=gam_info.price(총액).
        item_amount = total
    floor_no, unit_no = _floor_ho(context, item)
    # 지번은 명세행 우선(문서 대표 지번은 물건이 여러 개일 때 어긋난다).
    main_no, sub_no = split_jibun(item.jibun if item else None)
    if main_no is None and jibun is not None:
        main_no, sub_no = jibun.bun1, jibun.bun2

    return {
        # 작성자
        "대표,지사장": parties.boss,
        "평가사명1": parties.appraiser(0),
        "평가사명2": parties.appraiser(1),
        "평가사명3": parties.appraiser(2),
        "심사자": parties.reviewer,
        # 수수료 (gam_info 값이 있으므로 '자동계산' 버튼을 누를 필요가 없다)
        "감정평가(순)수수료": _money(fee.net),
        "(순)수수료-부가가치세": _money(_vat_of(fee.net)),
        "감정평가(순)수수료 총액": _money(_with_vat(fee.net)),
        "실비-총액": _money(fee.expense_with_vat),
        "수수료할증적용": FEE_SURCHARGE_DEFAULT,
        "수수료입금계좌번호": account.number if account else None,
        "계좌입금자명": account.holder if account else None,
        "사업등록번호": context.business_number,
        "現 기준시점": context.price_point_date,
        "감정평가액 결정의견": context.opinion_conclusion,
        # 물건 (일련번호=화면 물건순번. 다물건이면 채우는 물건과 같아야 한다)
        "일련번호": seq_no if (seq_no and str(seq_no).isdigit()) else "1",
        "물건종류": object_type(context, item),
        "평가방법": appraisal_method(context),
        "법정동코드": jibun.legal_code if jibun else None,
        "번지구분": jibun.jibun_kind if jibun else None,
        "본번지": main_no,
        "부번지": sub_no,
        "소재지": _address_only(_address(context)),
        "건물명": _building_name(context),
        "동": None,
        "건물구조": _best_struct(
            item.struct if item else None,
            first.struct_or_category if first and first.is_building else None,
            outline.struct),
        "공부지목": common.land_category(item.category) if item and item.is_land else None,
        "용도지역": item.zone if item else outline.zone,
        "준공일자": (first.approval_date if first else None) or outline.approval_date,
        "공부면적(전용면적)": _area((item.area_public if item else None)
                                or (first.area_public if first else None)
                                or outline.area_exclusive),
        "공부면적": _area((item.area_public if item else None)
                      or (first.area_public if first else None)),
        "사정면적": _area(item_assessed
                      or (first.area_assessed if first else None)
                      or outline.area_exclusive),
        "평가단가": _money((item.unit_price if item else None)
                       or (cost.unit_price if cost else None)),
        "감정평가액": None if rollup_only else _money(
            item_amount or (first.amount if first else None) or context.total_amount),
        "내용년수": _int((first.useful_years if first else None)
                     or (cost.useful_years if cost else None)),
        "잔존년수": _int((first.remaining_years if first else None)
                     or (cost.remaining_years if cost else None)),
        # mullist 가 없는 국민 건은 공부 스캔(T_SCAN_GONGBU)이 유일한 등기번호 소스다.
        # 등기번호는 물건 종류(토지/건물)까지 맞춰야 다른 물건 것을 집지 않는다.
        "등기번호": context.registry_no(
            kind=("토지" if item and item.is_land else "건물" if item and item.is_building else None),
            seq_no=item.seq_no if item else None),
        "총층수/층수": None if (item and item.is_land) else _int(outline.ground_floors),
        "건물 층수": floor_no or _floor_no(_address(context)),
        "호": unit_no or _unit_no(_address(context)),
        # 표준지 — 담보 건에서는 약 20%만 채워진다(비교표준지 표가 있는 건).
        "표준지소재지": standard.address,
        "표준지공시지가": _money(standard.price),
        "공시기준일": standard.base_date,
        # 채우지 않는 것(사용자 결정)
        "총세대수": None,
        "비   고": ("집계 구분건물 — 개별 물건 명세가 .gam 에 없음(수기 입력)"
                 if rollup_only else None),
    }
