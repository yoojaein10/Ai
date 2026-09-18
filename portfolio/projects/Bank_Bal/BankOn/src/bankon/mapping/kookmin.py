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
from ..parse import buildings, detail
from ..parse import units as unit_table
from ..parse.cost import representative

CHECKLIST_ANSWER = "아니오"      # 점검항목 기본값 — KB_Summary_Chk 가 없을 때만 쓴다
CHECKLIST_COUNT = 20            # a1~a12 + b1~b5 + c1~c3
FEE_SURCHARGE_DEFAULT = "미적용"  # 수수료할증적용

# 평가방법 라디오(물건 패널, **물건마다** 있다) — 물건구분으로 정한다(사용자 확정 2026-09-14, 2822 제보):
#   토지건물·토지·건물 = 구분소유외물건(원가평가) / 구분건물(호) = 구분소유물건(거래사례).
#   종전 '원가법 산출표가 있으면 원가평가'는 구분건물에 산출표가 없어 우연히 맞았을 뿐이다.
#   ⚠️ '거례사례'는 오타가 아니라 **은행 화면 캡션 그대로**다(2822 발송완료 폼 컨트롤 덤프 reports/probe_radio_20260914_141022.log —
#   TcxDBRadioGroupButton '구분소유물건(거례사례)'). by_text 는 정확 일치라 '거래사례'로 고치면 못 찾는다(2026-09-14 실측).
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


_STRUCT_ROOF = re.compile(r"\s*/\s*")
_STRUCT_PAREN = re.compile(r"\s*[（(].*$")             # '(평스라브)','((철근)콘크리트)' 꼬리
_STRUCT_KEEP = frozenset({"연와조", "석조", "와가", "초가"})  # '구조' 변형이 없는 표기


def _struct_only(text: str | None) -> str | None:
    """`철근콘크리트조 / 슬라브지붕` → `철근콘크리트구조`.

    화면 `건물구조` 칸에는 구조만 들어간다(지붕·괄호부기 제거). 명세표는 사람이
    직접 타이핑해 접미사가 `…조`/`…구조` 로 들쭉날쭉이라 화면 표기(`…구조`)로
    정규화한다(실측: 0636 철근콘크리트조→철근콘크리트구조, 0658 이미 구조=멱등,
    0668 일반철골구조). '연와조·석조'처럼 `구조` 변형이 없는 표기는 예외로 둔다.
    """
    if not text:
        return None
    head = _STRUCT_ROOF.split(text)[0]          # 지붕 제거
    head = _STRUCT_PAREN.sub("", head).strip()  # 괄호 부기 제거
    head = common._join_split_suffix(head)      # `철골철근콘크리트구 조`(2829 공부스캔 비고) → `…구조`
    if not head:
        return None
    if head.endswith("구조") or head in _STRUCT_KEEP:  # 멱등 + 예외
        return head
    return re.sub(r"조$", "구조", head) if head.endswith("조") else head


def _best_struct(*candidates: str | None) -> str | None:
    """구조 후보 중 완전한 값(…조/…구조로 끝)을 우선, 없으면 첫 유효값.

    명세표 gujo 는 word-wrap 으로 조각날 수 있어(철골철근/콘크리트구조 두 줄), 조각이면
    의견서 개요(outline.struct)의 완전한 값으로 폴백한다. 둘 다 조각이면 최선값(잡음).
    """
    cleaned = [_struct_only(c) for c in candidates]
    for value in cleaned:
        if value and (value.endswith("구조") or value in _STRUCT_KEEP):
            return value
    return next((value for value in cleaned if value), None)


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


# 층 표기 — 지하도 잡는다. `제3층`·`제지1층`·`제지하2층` → 3 · 지1 · 지2 (실측 2788 화면 `지1`).
_FLOOR_TOKEN = r"(지하?\s*\d+|\d+)"


def _floor_text(token: str | None) -> str | None:
    """층 표기 정리 — `지하 1` → `지1`, ` 12 ` → `12`. 화면 `건물 층수` 칸 표기(실측 2788 `지1`)."""
    if not token:
        return None
    text = re.sub(r"\s+", "", token)
    return re.sub(r"^지하", "지", text) or None


def floor_number(text: str | None) -> str | None:
    """화면 `총층수/층수` **오른쪽 칸**(해당 층) — 숫자만, 지하는 음수.

    라벨 하나에 칸이 둘이다: 왼쪽=건물 총층수, 오른쪽=이 물건이 있는 층. 종전엔 왼쪽만 채워
    오른쪽이 빈 채로 저장됐다(2804 담당자 제보 '구분건물 층수 누락', 2026-09-10).
    담당자 완성본 실측: 2742 `12`→12 · 2715 `1`→1 · 2804 `1`→1 · 2788 `지1`→**-1**.
    """
    token = _floor_text(text)
    if not token:
        return None
    match = re.match(r"^(지)?(\d+)$", token)
    if not match:
        return None
    return f"-{match.group(2)}" if match.group(1) else match.group(2)


def _floor_no(address: str | None) -> str | None:
    """`제3층 제301호` 에서 해당 층(3). 지하는 `제지1층` → `지1`."""
    if not address:
        return None
    match = re.search(r"제\s*" + _FLOOR_TOKEN + r"\s*층", address)
    return _floor_text(match.group(1)) if match else None


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


_FLOOR_HO = re.compile(r"제\s*" + _FLOOR_TOKEN + r"\s*층\s*제\s*([0-9가-힣\-]+?)\s*호")
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
                    return _floor_text(m.group(1)), m.group(2)
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
    """문서 대표 평가방법 — 구분건물(집합건물 호)만 거래사례, 나머지(토지건물·토지·건물)는 원가평가.

    물건구분(gam_info.category)이 '구분건물'이면 거래사례. '토지건물구분건물' 같은 혼합은 토지 필지가 물건이 되므로 원가평가.
    물건구분이 없으면 명세 구성으로 — 토지 필지 없이 호(구분건물 명세)만이면 거래사례.
    """
    category = (context.gam_category or "").replace(" ", "")
    if category:
        return METHOD_COMPARISON if (category == "구분건물" or ("구분건물" in category and "토지" not in category)) else METHOD_COST
    has_units = any(r.is_building and r.amount is not None for r in context.details)
    return METHOD_COMPARISON if (has_units and not _land_items(context)) else METHOD_COST


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


# 점검항목 20개 콤보(TcxComboBox) — 오른쪽 패널. recon/fields_kb_damb.md 의 1158 은 **화면 절대 x**이고 _in_region 은
# 창 상대 x(스크린샷 기준 ≈895, 물건 패널 170~440·세부 615~880 과 같은 기준). 위→아래 = a1~a12, b1~b5, c1~c3.
CHECKLIST_CONTROL_CLASS = "TcxComboBox"
CHECKLIST_REGION = (880, 1000)


def plan_checklist(currents: list[str], answers: tuple[str, ...]) -> list[tuple[int, str, str, str]]:
    """점검항목 콤보 계획 — [(순번, action, 넣을값, 현재값)]. 은행 기본값 '아니오'와 다른 것만 고른다(항상 덮어씀:
    .gam KB_Summary_Chk 가 근거. 2715 c3 '취약담보 여부'=예 를 안 넣어 업무팀이 손봄, 2026-08-31).
    콤보 수가 20이 아니면 화면 구성이 다른 것 → 빈 계획(안 건드림)."""
    if len(currents) != len(answers):
        return []
    plan = []
    for i, (cur, ans) in enumerate(zip(currents, answers)):
        if (cur or "").strip() == ans:
            plan.append((i, "일치", ans, cur))
        else:
            plan.append((i, "선택(덮어씀)" if (cur or "").strip() else "선택", ans, cur))
    return plan


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


def _kb_expense_total(fee) -> Decimal | None:
    """국민 '실비-총액' = 실비 구성합을 **1,000원 절사** 후 ×1.1 (실측 2418: 227,900→227,000→249,700 = gam_info
    SILBISUM+SILBITAX / 2590: 107,500→107,000→117,700). 현장조사서 라벨도 '(절사전 금액입력)'."""
    base = fee.expense_net
    if base is None:
        return None
    cut = (base / 1000).to_integral_value(rounding="ROUND_DOWN") * 1000
    return (cut * fee.VAT_RATE).quantize(Decimal(1))


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
        "실비-총액": _money(_kb_expense_total(fee)),
        "수수료할증적용": FEE_SURCHARGE_DEFAULT,
        "수수료입금계좌번호": account.number if account else None,
        "계좌입금자명": account.holder if account else None,
        "사업등록번호": context.business_number,
        "現 기준시점": context.price_point_date,
        "감정평가액 결정의견": context.opinion_conclusion,
        # 물건
        "일련번호": "1",
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
        # 같은 라벨의 **오른쪽 칸** — 이 물건이 있는 층(지하 음수). 종전엔 안 채워 빈 채 저장됐다(2804 제보).
        "총층수/층수@2": None if (item and item.is_land) else floor_number(floor_no or _floor_no(_address(context))),
        "건물 층수": floor_no or _floor_no(_address(context)),
        "호": unit_no or _unit_no(_address(context)),
        # 표준지 — 담보 건에서는 약 20%만 채워진다(비교표준지 표가 있는 건).
        "표준지소재지": standard.address,
        "표준지공시지가": _money(standard.price),
        "공시기준일": standard.base_date,
        # 토지·동 단위 건물은 채우지 않는다(사용자 결정). 구분건물 호 물건은 _build_units 에서 개요 '건물의 규모'로.
        "총세대수": None,
        "비   고": ("집계 구분건물 — 개별 물건 명세가 .gam 에 없음(수기 입력)"
                 if rollup_only else None),
    }


# ═══════════════════════════════════════════════════════════════════════
# 2단 구조(물건 → 세부내역) — 실화면 정찰 2026-08-26 (recon/fields_kb_damb.md 하단)
# ═══════════════════════════════════════════════════════════════════════

# 창 왼쪽 기준 x 범위. 같은 라벨(일련번호·번지구분·본번지·부번지·공부면적·사정면적·평가단가·감정평가액·등기번호)이
# 물건 패널(가운데)과 세부내역 패널(오른쪽)에 둘 다 있어 구역으로 가른다.
REGIONS = {"물건": (170, 440), "세부": (615, 880)}

# 라벨 없는 칸 — 기준 라벨 입력칸 좌상단 기준 (dx, dy). 정찰 덤프 창 상대좌표 실측.
POSITIONAL = {
    "물건:법정동코드": ("건물명", 0, -110, "TcxDBTextEdit"),      # 주소검색 버튼 옆 코드칸(@515,307 ← 건물명 @625,307)
    "물건:소재지": ("건물명", -126, -88, "TcxDBTextEdit"),        # @537,181
    "물건:표준지소재지": ("건물명", -126, 150, "TcxDBTextEdit"),   # 라벨 아래 칸(@775,181) — 라벨 오른쪽 매칭이 등기번호를 집던 버그
    "물건:비   고": ("건물명", -126, 231, "TcxDBTextEdit"),
    "세부:법정동코드": ("공부지목", 0, -129, "TcxDBTextEdit"),     # 토지 세부 @492,749 ← 공부지목 콤보 @621,749
    "세부:소재지": ("공부지목", -125, -103, "TcxDBTextEdit"),      # @518,624
}

# 항상 덮어쓰는 칸(은행 선입력이 문서와 다를 수 있는 값). 나머지는 빈칸만.
# Bank24 는 물건 행을 추가하면 **직전 행 값을 복사**해 온다 — 빈칸만 채우는 기본 규칙으로는 그 값이 남는다
# (2513 실측 2026-09-17: 물건 3 부번지가 물건 2 의 '16' 그대로, 우리 값 '17' 이 안 들어감).
# 물건을 식별하는 칸과 문서 대표값(표준지 3칸)은 문서 쪽이 항상 옳으므로 덮어쓴다.
ALWAYS_OVERWRITE = frozenset({
    "물건:일련번호", "물건:물건종류", "물건:법정동코드", "물건:번지구분", "물건:본번지", "물건:부번지", "물건:소재지",
    "물건:표준지소재지", "물건:표준지공시지가", "물건:공시기준일",
})

_HEADER_KEYS = ("대표,지사장", "평가사명1", "평가사명2", "평가사명3", "심사자", "감정평가(순)수수료",
                "(순)수수료-부가가치세", "감정평가(순)수수료 총액", "실비-총액", "수수료할증적용",
                "사업등록번호", "現 기준시점", "감정평가액 결정의견")
_OBJECT_KEYS = ("일련번호", "물건종류", "법정동코드", "번지구분", "본번지", "부번지", "소재지", "건물명", "동",
                "건물 층수", "호", "표준지소재지", "표준지공시지가", "공시기준일", "총층수/층수", "총층수/층수@2",
                "총세대수", "비   고")
_HEAD_SEQ = re.compile(r"^[가-힣]$")          # 건물 동 머리행 NO: 가·나·다…


_KB_ZONE_ALIAS = {
    "개발제한구역": "개발제한",   # 콤보 항목명은 '개발제한'(2754 발송본 대조 2026-09-07 — '개발제한구역' 은 항목 없음으로 거부됐다)
}


def _kb_zone(zone: str | None) -> str | None:
    """국민 용도지역 콤보는 '지역' 꼬리가 없다('자연녹지', '계획관리' — 실화면 2608·2647). 용도구역은 별칭표로."""
    if not zone:
        return None
    text = re.sub(r"\s+", "", zone)
    if text in _KB_ZONE_ALIAS:
        return _KB_ZONE_ALIAS[text]
    return re.sub(r"지역$", "", text) or None


def _building_blocks(context: DocumentContext) -> list[tuple[detail.DetailRow, list[detail.DetailRow]]]:
    """명세표에서 건물 동 머리행('가','나'…)과 그 뒤 금액 있는 층행들을 묶는다."""
    rows = list(context.details)
    blocks = []
    for i, row in enumerate(rows):
        if row.seq_no and _HEAD_SEQ.match(row.seq_no):
            body = []
            for nxt in rows[i + 1:]:
                if nxt.seq_no is not None:
                    break
                if nxt.amount is not None:
                    body.append(nxt)
            blocks.append((row, body))
    return blocks


def _land_items(context: DocumentContext) -> list[detail.DetailRow]:
    return [r for r in context.details if r.seq_no and r.seq_no.isdigit() and r.is_land]


def _cost_for(context: DocumentContext, mark: str | None):
    for layer in context.cost_layers:
        if layer.mark == mark:
            return layer
    return representative(context.cost_layers)


# 규칙 A(사용자 결정 2026-08-26): 필지 1개 = 물건 1개, 물건종류 콤보 = 지목. 실물 2418(19필지=19물건)과 일치.
# 콤보 114개 중 지목에 해당하는 값만. '대'와 '공장용지'는 한 항목('대/ 공장용지').
OBJECT_TYPE_BY_CATEGORY = {
    "대": "대/ 공장용지", "대지": "대/ 공장용지", "공장용지": "대/ 공장용지", "전": "전", "답": "답", "임야": "임야", "잡종지": "잡종지",
    "과수원": "과수원", "도로": "도로", "구거": "구거", "하천": "하천", "제방": "제방", "염전": "염전", "유지": "유지",
    "유원지": "유원지", "사적지": "사적지", "묘지": "묘지", "광천지": "광천지", "학교용지": "학교용지",
    "철도용지": "철도용지", "수도용지": "수도용지", "공원용지": "공원용지", "공원": "공원용지", "체육용지": "체육용지",
    "종교용지": "종교용지", "목장용지": "목장용지", "양어장": "기타대지", "창고용지": "기타대지", "주차장": "기타대지",
    "주유소용지": "기타대지",
}


def object_type_from_category(category: str | None) -> str | None:
    """지목 → 물건종류 콤보(규칙 A). 모르는 지목은 None(사람이 고름)."""
    name = common.land_category(category) or (category or "").strip()
    return OBJECT_TYPE_BY_CATEGORY.get(name)


def _parcel_address(context: DocumentContext, item: detail.DetailRow) -> str | None:
    """필지 소재지 — land_list 의 location 은 계층 조각('경기도'/'이천시'/'마장면', 2418)이라
    읍면동/리로 끝나는 온전한 값일 때만 쓰고, 아니면 문서 대표 주소(KB_Summary.addr)."""
    loc = (item.location or "").strip()
    if loc and loc != "동소" and len(loc.split()) >= 3 and re.search(r"(동|리|읍|면|가)$", loc):
        return _address_only(loc)
    return _address_only(_address(context))


def _gongbu_building_area(context: DocumentContext, registry: str | None):
    """같은 등기번호의 공부스캔 층행 면적 합 = 화면 건물 공부면적(2418 306 1동 2275+39.55=2314.55, 308 583.76)."""
    if not registry:
        return None
    total = Decimal(0)
    hit = False
    for row in context.gongbu:
        if row.is_building and row.registry_no == registry and row.area is not None:
            total += row.area
            hit = True
    return total if hit else None


def _land_row(context: DocumentContext, item: detail.DetailRow, *, area_public, assessed, unit_price, amount,
              category=None, zone=None, registry=None) -> dict[str, str | None]:
    jibun = context.jibun
    main_no, sub_no = split_jibun(item.jibun)
    return {
        "_kind": "토지",
        "세부:법정동코드": jibun.legal_code if jibun else None,
        "세부:소재지": _parcel_address(context, item),
        "세부:번지구분": jibun.jibun_kind if jibun else None,
        "세부:본번지": main_no,
        "세부:부번지": sub_no,
        "세부:공부지목": common.land_category(category or item.category),
        "세부:용도지역": _kb_zone(zone or item.zone or context.outline.zone),
        # 공부면적이 명세표에 없으면 사정면적으로(평가외 필지 5-17·27-6 이 빈 채 저장됨 — 담당자 지시 2026-09-17).
        "세부:공부면적": _area(area_public if area_public is not None else assessed),
        "세부:사정면적": _area(assessed),
        # 금액 없는 필지(도로 등)는 단가 1·금액 0 — 실물 관례(2601·2703 담당자 입력, 사용자 정정 2026-08-28).
        "세부:평가단가": _money(unit_price) if unit_price is not None else ("1" if amount is None else None),
        "세부:감정평가액": _money(amount) if amount is not None else ("0" if unit_price is None else None),
        # 공부스캔이 있는데 그 필지가 없으면 비운다(다른 필지 번호를 집는 것보다 낫다 — 2418 308-2).
        "세부:등기번호": (registry if registry is not None
                      else _gongbu_land_registry(context, _parcel_key(item.jibun))
                      or (None if context.gongbu else context.registry_no(kind="토지", seq_no=item.seq_no))),
    }


def _land_details(context: DocumentContext, item: detail.DetailRow) -> list[dict[str, str | None]]:
    """필지 하나 → 토지 세부행 목록(실물 2418 관례).

    - 머리행 1행 + 뒤따르는 소분행(도로저촉 '현황 도로' 등, seq None)은 **각각 별도 행**(합산 안 함):
      공부면적·지목·등기번호는 필지 것, 사정면적·단가·감정가는 소분행 것(없으면 0).
    - 일단지 머리행(사정면적 > 공부면적)은 자기 공부면적만 사정면적으로, 감정가 = 단가 × 공부면적
      (흡수된 필지 몫은 _absorbed_row 가 따로 행을 만든다. 2418: 306 3181/951,119,000 + 308-2 1254/374,946,000).
    """
    rows = []
    assessed, amount = item.area_assessed, item.amount
    unit = item.unit_price
    if (item.area_public is not None and assessed is not None and assessed > item.area_public
            and unit is not None):
        assessed = item.area_public
        amount = (unit * assessed).quantize(Decimal(1))
    rows.append(_land_row(context, item, area_public=item.area_public, assessed=assessed,
                          unit_price=unit, amount=amount))
    if not item.group_head:
        for sub in _following_subrows(context.details, item):
            if not sub.is_land or (sub.area_assessed is None and sub.amount is None):
                continue
            rows.append(_land_row(context, item, area_public=item.area_public, assessed=sub.area_assessed,
                                  unit_price=sub.unit_price, amount=sub.amount or Decimal(0),
                                  registry=rows[0]["세부:등기번호"]))
    return rows


def _absorbed_row(context: DocumentContext, head: detail.DetailRow, item: detail.DetailRow) -> dict[str, str | None]:
    """일단지에 흡수된 필지(사정면적·감정가 없음) → 머리 필지 물건 안의 토지행. 감정가 = 머리 단가 × 공부면적."""
    unit = head.unit_price
    area = item.area_public
    amount = (unit * area).quantize(Decimal(1)) if unit is not None and area is not None else None
    return _land_row(context, item, area_public=area, assessed=area, unit_price=unit, amount=amount)


def _parcel_key(jibun: str | None) -> str | None:
    """지번 문자열 → 매칭 키. '306,' / '299-5 ' / '0299-0005' 를 '306' / '299-5' 로."""
    text = (jibun or "").strip().split(",")[0].strip()
    if not text:
        return None
    main_no, sub_no = split_jibun(text)
    if main_no is None:
        return text
    return f"{main_no}-{sub_no}" if sub_no else main_no


_ADDR_LAND = re.compile(r"(\d+(?:-\d+)?)\s*$")
# 건물 주소 실측: '299-3 1동' / '299-8 제1동' / '306외 1필지 2동' / '211-1 제2동호' / '211-1'(동은 비고 앞머리 '1동') / '108-3외 1필지'
_ADDR_BUILDING = re.compile(r"(\d+(?:-\d+)?)(?:\s*외\s*\d+\s*필지)?(?:\s*(?:제)?(\d+)\s*동호?)?\s*$")
_NOTE_DONG = re.compile(r"^(?:제)?(\d+)\s*동호?\s*")


def _gongbu_land_registry(context: DocumentContext, parcel: str | None) -> str | None:
    """공부스캔 토지 행을 지번으로 골라 등기번호(2418: 필지 16개 전부 있음)."""
    if not parcel:
        return None
    for row in context.gongbu:
        if not row.is_land or not row.address:
            continue
        m = _ADDR_LAND.search(row.address)
        if m and _parcel_key(m.group(1)) == parcel and row.registry_no:
            return row.registry_no
    return None


def _struct_from_note(note: str | None) -> str | None:
    """비고 '일반철골구조 경량판넬지붕 1층 …' → '지붕' 단어 앞까지('철골조 및 경량철골조'도 그대로)."""
    if not note:
        return None
    text = _NOTE_DONG.sub("", note.strip())
    words = []
    for w in text.split():
        if w.endswith("지붕"):
            break
        words.append(w)
    struct = " ".join(words).strip()
    return struct if struct and (struct.endswith("구조") or struct.endswith("조")) else None


def _gongbu_buildings(context: DocumentContext, parcel: str | None) -> list[tuple[int | None, str | None, str | None]]:
    """필지의 공부스캔 건물들 → [(동번호, 등기번호, 구조)] (같은 등기번호는 층행이라 1개로)."""
    found: dict[str, tuple[int | None, str | None, str | None]] = {}
    for row in context.gongbu:
        if not row.is_building or not row.address or not row.registry_no:
            continue
        m = _ADDR_BUILDING.search(row.address)
        if not m or _parcel_key(m.group(1)) != parcel:
            continue
        if row.registry_no in found:
            continue
        dong = m.group(2)
        if dong is None and row.note:
            nm = _NOTE_DONG.match(row.note.strip())
            dong = nm.group(1) if nm else None
        found[row.registry_no] = (int(dong) if dong else None, row.registry_no, _struct_from_note(row.note))
    return list(found.values())


def _building_details(context: DocumentContext) -> list[dict[str, str | None]]:
    rows = []
    ordinal: dict[str | None, int] = {}
    blocks = [(h, b) for h, b in _building_blocks(context) if b]
    # 공부스캔 층합계(2418 306 1동 2275+39.55)는 등기번호가 그 동만의 것일 때만 믿는다. 한 등기번호에 동이 여럿이면(2823 3동
    # 모두 1154-1996-108929) 합계 495 가 동마다 들어가 틀린다 → 명세표 공부면적 그대로(담당자 정정 2026-09-14: 198/198/99).
    registry_of: list[str | None] = []
    seen: dict[str | None, int] = {}
    for head, _body in blocks:
        parcel = _parcel_key(head.jibun)
        seen[parcel] = seen.get(parcel, 0) + 1
        scanned = _gongbu_buildings(context, parcel)
        hit = next((b for b in scanned if b[0] == seen[parcel]), None) or (scanned[seen[parcel] - 1] if seen[parcel] <= len(scanned) else None)
        registry_of.append(hit[1] if hit else context.registry_no(kind="건물"))
    shared = {r for r in registry_of if r and registry_of.count(r) > 1}
    for head, body in blocks:
        if not body:
            continue
        area_pub = sum((r.area_public or Decimal(0)) for r in body)
        area_ass = sum((r.area_assessed or Decimal(0)) for r in body)
        amount = sum(r.amount for r in body)
        cost = _cost_for(context, head.seq_no)
        unit = (amount / area_ass).quantize(Decimal(1)) if area_ass else None
        parcel = _parcel_key(head.jibun)
        # 동별 등기번호·구조 = 공부스캔 건물 행(주소 '…299-3 1동'). 필지 안 n번째 동 = 동번호 n(없으면 n번째 행).
        ordinal[parcel] = ordinal.get(parcel, 0) + 1
        nth = ordinal[parcel]
        scanned = _gongbu_buildings(context, parcel)
        hit = next((b for b in scanned if b[0] == nth), None) or (scanned[nth - 1] if nth <= len(scanned) else None)
        registry = hit[1] if hit else context.registry_no(kind="건물")
        info = buildings.by_mark(context.buildings, head.seq_no)     # 의견서 '2. 건물' 표(기호별)
        struct = (hit[2] if hit else None) or _best_struct(head.struct, info.struct if info else None, context.outline.struct)
        approval = (info.approval_date if info else None) or context.outline.approval_date
        rows.append({
            "_kind": "건물",
            "_parcel": parcel,   # 소재 필지(명세표 머리행 지번, '306,' 꼴은 첫 필지) — 물건 매칭용
            "_use": (info.use if info else None) or context.outline.building_use,   # 물건종류(건물 있는 물건) 판정용
            "세부:건물구조": struct,
            "세부:준공일자": approval,      # 기호별 사용승인일자(의견서 2.건물 표) → 없으면 개요값
            "세부:내용년수": _int(cost.useful_years if cost else None),
            "세부:잔존년수": _int(cost.remaining_years if cost else None),
            "세부:공부면적(전용면적)": _area((area_pub or None) if registry in shared
                                    else (_gongbu_building_area(context, registry) or area_pub or None)),
            "세부:사정면적": _area(area_ass or None),
            "세부:평가단가": _money(unit),
            "세부:감정평가액": _money(amount),
            "세부:등기번호": registry,
        })
    return rows


# ── 구분소유(집합건물 호실) — 실물 2669(1호)·2585(7호) 덤프 2026-08-26 ─────────────────────
# 호 1개 = 물건 1개(물건종류 = 건물 용도별 콤보), 세부 = 건물 1행(전용면적=사정면적, 호별 비준가액, 호별 전유부분 등기번호,
# 구조·준공일). 단가·내용/잔존연수는 0(비움), 표준지 칸 비움, 동은 수기. 총세대수는 개요 '건물의 규모'(2026-09-09).
_UNIT_TYPE = (
    ("아파트", "아파트(주상복합아파트포함)"), ("오피스텔", "오피스텔"), ("다세대", "다세대주택"), ("연립", "연립주택"),
    ("지식산업", "지식산업센터(아파트형공장)"), ("아파트형공장", "지식산업센터(아파트형공장)"),
    ("근린생활", "집합상가-근린(점포)상가"), ("업무", "빌딩(사무실)"),
)
# 층은 지하도 잡는다 — `제?\s*(\d+)` 는 `제지1층` 에서 `1` 만 집어 지하를 지상으로 만든다(실측 2788 공부스캔
# `제지1층 제비108호` → 종전 층 `1`, 화면은 `지1`). 지하를 놓치면 층수 칸에 +1 이 들어간다(오른쪽 칸은 -1 이어야 한다).
_UNIT_ADDR = re.compile(r"제?\s*(지하?\s*\d+|\d+)\s*층\s*제?\s*([0-9A-Za-z가-힣\-]+)\s*호")


def unit_object_type(building_use: str | None) -> str | None:
    """구분소유 물건종류 — 의견서 개요 건물용도 키워드(2669 근린생활시설→집합상가-근린). 모르면 None(사람이 고름;
    2585 판매시설은 담당자가 '도·소매시장'). 호별 표 용도('제2종근린 생활시설 (…)')처럼 공백이 끼어도 본다."""
    text = (building_use or "").split(",")[0].replace(" ", "")   # 복합용도('판매시설, 창고시설, 업무시설…')는 첫 용도만 본다
    for key, combo in _UNIT_TYPE:
        if key in text:
            return combo
    return None


def _unit_scans(context: DocumentContext) -> list[dict]:
    """공부스캔 건물 행(호별 전유부분) → [{registry, floor, ho, struct, area}] 순서대로(같은 등기번호 1개)."""
    out, seen = [], set()
    for row in context.gongbu:
        if not row.is_building or not row.registry_no or row.registry_no in seen:
            continue
        seen.add(row.registry_no)
        m = _UNIT_ADDR.search(row.address or "")
        note = re.sub(r"^전유부분\s*", "", (row.note or "").strip())
        out.append({"registry": row.registry_no, "floor": _floor_text(m.group(1)) if m else None,
                    "ho": m.group(2) if m else None,
                    "struct": _struct_only(note) if note else None, "area": row.area})
    return out


def _build_units(context: DocumentContext, first_obj: dict) -> list[dict]:
    units = [r for r in context.details if r.is_building and r.amount is not None]
    if not units:
        first_obj["_details"] = []
        return [first_obj]
    scans = _unit_scans(context)
    outline = context.outline
    objects = []
    for n, u in enumerate(units, start=1):
        # 물건종류는 **호별 표(개요)의 그 호 용도**가 우선(2715: 건물 전체 '업무시설(사무소), 근린생활시설' → 빌딩(사무실)로
        # 넣었으나 호는 '제2종근린생활시설' → 업무팀 '집합상가-근린(점포)상가', 2026-08-31). 없으면 건물 전체 용도.
        unit_row = unit_table.by_mark(context.units, u.seq_no)
        utype = unit_object_type((unit_row.use if unit_row and unit_row.use else None) or outline.building_use)
        scan = scans[n - 1] if n - 1 < len(scans) else None
        if scan and u.area_public is not None and scan["area"] is not None and scan["area"] != u.area_public:
            scan = next((sc for sc in scans if sc["area"] == u.area_public), scan)   # 순서 어긋나면 면적으로
        floor, ho = _floor_ho(context, u)
        floor = floor or (scan["floor"] if scan else None) or first_obj.get("물건:건물 층수")
        # 호는 **공부스캔(등기 표제부 `제지1층 제비108호`)이 가장 정확**하다 — 문서 대표주소 꼬리는 접두(비·씨·에이)를
        # 못 살리고(실측 2788 화면 `비108` ↔ 꼬리 `108`), 명세행이 없는 구분건물에선 그 꼬리로 물러서게 된다.
        ho = (scan["ho"] if scan else None) or ho or (first_obj.get("물건:호") if n == 1 else None)
        obj = dict(first_obj) if n == 1 else {f"물건:{k}": first_obj.get(f"물건:{k}") for k in
                                              ("법정동코드", "번지구분", "본번지", "부번지", "소재지", "건물명", "총층수/층수")}
        obj.update({f"물건:{k}": None for k in ("표준지소재지", "표준지공시지가", "공시기준일", "동", "비   고")})
        # 총세대수 = 의견서 개요 '건물의 규모'(2788 '102호' → 102, 호·세대 병기는 세대 우선, 사용자 요청 2026-09-09).
        # 건물 전체 값이라 호(물건)마다 같은 수. 규모 행이 없거나 층수만이면 None(수기).
        obj["물건:총세대수"] = _int(outline.total_units)
        obj["물건:일련번호"] = str(n)
        obj["물건:건물 층수"] = floor
        obj["물건:총층수/층수@2"] = floor_number(floor)   # 라벨 오른쪽 칸(해당 층, 지하 음수) — 호마다 다르다
        obj["물건:호"] = ho
        obj["물건:물건종류"] = utype
        # 은행이 '동' 칸에 건물명(잘린 '두산더랜드파')을 선입력해 두면 소재지 출력이 건물명 2번 → 지운다(2715, 2026-08-31).
        # 건물명과 무관한 값(사람이 넣은 실제 동)은 form.clear_fields 가 건드리지 않는다.
        obj["_clear"] = {"물건:동": first_obj.get("물건:건물명")}
        struct = _best_struct(scan["struct"] if scan else None, _struct_only(u.struct), outline.struct)
        obj["_details"] = [{
            "_kind": "건물",
            "세부:건물구조": struct,
            "세부:준공일자": outline.approval_date,
            "세부:내용년수": None, "세부:잔존년수": None, "세부:평가단가": None,
            "세부:공부면적(전용면적)": _area(u.area_public),
            "세부:사정면적": _area(u.area_assessed or u.area_public),
            "세부:감정평가액": _money(u.amount),
            "세부:등기번호": scan["registry"] if scan else context.registry_no(kind="건물"),
        }]
        objects.append(obj)
    return objects


def build_kb(context: DocumentContext) -> tuple[dict[str, str | None], list[dict]]:
    """국민 화면 2단 — 규칙 A: (헤더 필드, 물건 목록).

    물건 = 명세표 토지 필지(순번 숫자·금액 있음) 하나당 1개. 물건 dict 는 '물건:' 키 + `_details`(세부내역 목록).
    - 물건종류 콤보 = 지목(OBJECT_TYPE_BY_CATEGORY), 세부 = 그 필지 토지 1행.
    - 건물 동('가','나'…)은 첫 물건(본 필지)의 세부에 토지 뒤로 붙인다(화면 순서 토지→건물).
    - 표준지·건물명·층·호 등 문서 대표값은 첫 물건에만.
    - 토지 필지가 없는 문서 = 구분소유: 호 1개 = 물건 1개, 세부 건물 1행(_build_units).
    """
    base = build(context, None)
    header: dict[str, str | None] = {k: base.get(k) for k in _HEADER_KEYS}
    header["평가방법"] = base.get("평가방법")     # 문서 대표값(참고용) — 실제 라디오는 물건마다 `_method` 로 누른다(2822, 2026-09-14)
    # 계좌 2칸은 발송 실물(2608·2647)에서 비어 있음 — 현장조사서 쪽 항목이라 작성폼엔 넣지 않는다.

    first_obj: dict = {f"물건:{k}": base.get(k) for k in _OBJECT_KEYS}
    first_obj["물건:일련번호"] = "1"
    buildings = _building_details(context)
    lands = _land_items(context)
    if not lands:
        # 토지 필지 없음 = 구분소유(집합건물 호실) — 호별 물건. (동 단위 건물 블록이 있으면 종전처럼 첫 물건에)
        if buildings:
            first_obj["_details"] = buildings
            first_obj["_method"] = METHOD_COST                 # 동 단위 건물(구분소유 아님) = 원가평가
            return header, [first_obj]
        units = _build_units(context, first_obj)
        for obj in units:
            obj["_method"] = METHOD_COMPARISON                 # 호(구분소유물건) = 거래사례 — 2822 는 7호 전부
        return header, units

    objects: list[dict] = []
    jibun = context.jibun
    absorbed_by: dict[int, list] = {}
    for item in lands:
        # 사정면적·감정가 둘 다 없는 필지 = 직전 일단지 머리 필지에 흡수(2418 308-2 → 306) → 그 물건 안 토지행.
        if item.area_assessed is None and item.amount is None:
            if objects:
                head_item = objects[-1]["_item"]
                objects[-1]["_details"].append(_absorbed_row(context, head_item, item))
            continue
        # 감정평가외 필지(도로 등, PRICE 칸이 글자)도 **본번·부번이 다르면 왼쪽 물건 1개**다(단가 1·금액 0 세부행 포함).
        # 사용자 확정 2026-09-17(2881 담당자 완성본 1.png: 512-5 대 / 512-2 전 / 512-6 도로 = 물건 3개).
        # 종전엔 2823 담당자가 물건을 지우고 세부행으로 옮긴 걸 따라 직전 물건에 흡수했는데, 규칙 A(필지 1개 = 물건 1개)와
        # 어긋나 2881 에서 물건이 1개만 생겼다. 여러 필지를 물건 하나로 합치는 건 담당자가 직접 한다.
        n = len(objects) + 1
        rows = _land_details(context, item)
        land = rows[0]
        if n == 1:
            obj = dict(first_obj)
        else:
            obj = {f"물건:{k}": None for k in _OBJECT_KEYS}
            obj["물건:법정동코드"] = jibun.legal_code if jibun else None
            obj["물건:번지구분"] = jibun.jibun_kind if jibun else None
            obj["물건:소재지"] = land["세부:소재지"]
            # 표준지 3칸은 문서 대표값이라 물건마다 같다 — 종전엔 첫 물건에만 들어가 2~4 가 비었다(담당자 지시 2026-09-17).
            for key in ("표준지소재지", "표준지공시지가", "공시기준일"):
                obj[f"물건:{key}"] = base.get(key)
        obj["물건:일련번호"] = str(n)
        obj["물건:본번지"] = land["세부:본번지"]
        obj["물건:부번지"] = land["세부:부번지"]
        obj["_parcel"] = _parcel_key(item.jibun)
        obj["_category"] = item.category
        obj["_item"] = item
        obj["_details"] = rows
        obj["_method"] = METHOD_COST                           # 토지 필지 물건(토지건물·토지) = 원가평가
        objects.append(obj)
    # 건물 동은 소재 필지 물건의 세부에(실물 2418: 299-5 물건에 3행, 308 물건에 2행). 못 찾으면 첫 물건.
    by_parcel = {o["_parcel"]: o for o in objects if o.get("_parcel")}
    for b in buildings:
        target = by_parcel.get(b.get("_parcel")) or objects[0]
        target["_details"].append({k: v for k, v in b.items() if k != "_parcel"})
    for obj in objects:
        # 토지만인 물건(도로·답 등)은 지목(실물 2418). 건물이 붙는 물건은 용도 콤보(실물 2601·2703 '일반공장',
        # 사용자 정정 2026-08-28) — 지목 공장용지면 '일반공장', 아니면 건물 용도 키워드로. 모르면 None(사람이 고름).
        if all(d.get("_kind") == "토지" for d in obj["_details"]):
            obj["물건:물건종류"] = object_type_from_category(obj["_category"]) or obj.get("물건:물건종류")
        else:
            uses = [d.get("_use") for d in obj["_details"] if d.get("_kind") == "건물"]
            obj["물건:물건종류"] = building_object_type(obj["_category"], uses[0] if uses else None)
        for d in obj["_details"]:
            d.pop("_use", None)
        obj.pop("_item", None)
    return header, objects


# 건물이 붙는 물건의 물건종류 콤보 — 지목 우선(공장용지→일반공장), 그다음 의견서 건물 용도 키워드.
# 2703: 지목 공장용지 + 용도 제2종근린생활시설 → 담당자 '일반공장'(사용자 정정 2026-08-28).
_BUILDING_TYPE_BY_CATEGORY = {"공장용지": "일반공장", "창고용지": "일반창고", "학교용지": "학교", "종교용지": "교회",
                              "주유소용지": "주유소", "축사용지": "축사"}
_BUILDING_TYPE_BY_USE = (
    ("공장", "일반공장"), ("창고", "일반창고"), ("축사", "축사"), ("동·식물", "축사"), ("동식물", "축사"),
    ("단독주택", "단독주택"), ("다가구", "다가구주택"), ("다세대", "다세대주택"), ("연립", "연립주택"),
    ("아파트", "아파트(주상복합아파트포함)"), ("근린생활", "일반상가-근린(점포)상가"), ("업무", "빌딩(사무실)"),
    ("숙박", "여관(모텔)"), ("교육연구", "학교"), ("종교", "교회"), ("의료", "병원"), ("주유소", "주유소"),
    ("자동차관련", "자동차정비공장"), ("노유자", "노인의료복지시설"), ("장례", "장례식장"),
)


def building_object_type(land_category: str | None, building_use: str | None) -> str | None:
    """건물 있는 물건의 물건종류 콤보. 지목 → 용도 키워드 순. 모르면 None(사람이 고름)."""
    cat = common.land_category(land_category) if land_category else None
    if cat in _BUILDING_TYPE_BY_CATEGORY:
        return _BUILDING_TYPE_BY_CATEGORY[cat]
    # 표 셀 안에서 줄바꿈된 용도('제2종근린 생활시설 (제조업소)', 2513)는 공백을 떼야 키워드가 맞는다.
    # unit_object_type 은 종전부터 떼고 있었다 — 여기만 빠져 있었다(2026-09-17).
    text = (building_use or "").split(",")[0].replace(" ", "").replace("\n", "")
    for key, combo in _BUILDING_TYPE_BY_USE:
        if key in text:
            return combo
    return None
