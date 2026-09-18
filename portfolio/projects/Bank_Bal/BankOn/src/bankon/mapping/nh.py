"""농협 담보(`TBNKNHB24DAMB`) 필드 매핑.

국민(`kookmin`)과 가장 닮았다 — `mullist` 없이 명세표(`land_list`/`section_build`)가 물건
출처이고, 표준지 3종·평가사명1~3·대표지사장·건물명/동/호/총층수를 쓴다. 다른 점:

  · **한 폼에 세 변형**이 있다(화면이 물건 종류·의뢰처에 따라 바뀐다).

        토지형   49칸 — 공부지목·용도지역·공부면적·'일단지등 기호'
        건물형   55칸 — 건물명·동·호·해당층수·총층수·건물구조·준공일자·
                        내용/잔존년수·'공부면적(전용면적)'
        지역농협 65/71칸 — 위 + 수수료 **할인 블록** 7칸. 농협은행 건엔 없다.

  · 지목을 **원문 그대로** 쓴다(`대` → 화면도 `대`). 신한·국민은 `대지` 로 바꾼다.
  · 용도지역은 **대분류**만 쓴다(`제2종일반주거지역` → 화면 `일반주거지역`).
  · 건물구조는 명세표 **원문 표기**를 쓴다(`철근콘크리트조` 를 `…구조` 로 바꾸지 않는다).
  · `평가금액`(문서 총액)과 `감정평가액`(물건별)이 **다른 칸**이다.
  · `담보번호`·`소유자명`·`물건기호` 는 다른 은행에 없던 칸이다.

화면 항목명은 실폼 14건(`recon/fields_TBNKNHB24DAMB.md`, `recon/nh_screen.json`)에서 읽었다.
"""
from __future__ import annotations

import re
from decimal import ROUND_DOWN, Decimal

from ..codes import common
from ..model import DocumentContext
from ..parse import address, detail, round as round_parse
from ..sources.scan import identify as identify_gongbu

# 실비 절사 단위 — 지역농협 화면의 `실  비` 는 절사한 실비에 부가세를 붙인 값이다.
EXPENSE_UNIT = Decimal(1000)
VAT_RATE = Decimal("1.1")

# 용도지역 대분류 — 화면은 `제2종일반주거지역` 을 `일반주거지역` 으로 받는다(실측 2616·2497).
_ZONE_GRADE = re.compile(r"^제\s*\d+\s*종\s*")

# 라벨이 없거나 여러 칸이 `물건종류` 라벨을 나눠 쓰는 자리 — **위치**로 짚는다
# (`ui.form.between_labels`). `물건기호`~`번지구분` 사이 7칸의 구성은 실측 14건에서 동일하다.
#   0 물건종류(콤보) · 1 부동산구분(콤보) · 2 우편번호 · 3 법정동코드
#   4 소재지(짧은 표기) · 5 소재지(긴 표기) · 6 물건 표시
_BOX = "@물건기호~번지구분"
BOX_KIND = f"부동산구분{_BOX}[1]"
BOX_ZIP = f"우편번호{_BOX}[2]"                 # 소스에 없다(주소검색이 채운다) — 안 쓴다
BOX_LEGAL_CODE = f"법정동코드{_BOX}[3]"
BOX_SITE_SHORT = f"소재지(짧은표기){_BOX}[4]"   # 시도 축약형 — 우리는 정식 표기를 쓴다
BOX_SITE = f"소재지{_BOX}[5]"
BOX_DISPLAY = f"물건표시{_BOX}[6]"             # 지번+건물명+층/호 — display_text() (2026-09-11 전엔 비워 두고 사람이 적었다)
# 표준지소재지 입력칸은 라벨 **아래**(402,573)에 있는데 이 계통의 find_by_label 은 같은 줄 오른쪽(감정평가액)을 먼저 집는다
# (2026-09-07 발송완료 5건 드라이런: 현재=59,888,000). 표준지공시지가~총수익 밴드에서 유일하게 왼쪽(402)인 칸 — 3변형 모두 동일(정답지 실측).
BOX_STD_SITE = "표준지소재지@표준지공시지가~총수익[왼쪽]"

# 층·호·동 표기 해석은 `parse.address` 한 곳에만 둔다(복사본이 갈리지 않게).

# 지번 뒤 건물명 떼기 — 인계본(D:\AI\BankOn)에선 kookmin 과 공유했으나 이 계통의 kookmin 은 다른 구현이라 여기 둔다(2026-09-07 이식).
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


def _building_name_from(text: str | None) -> str | None:
    """`…동 <지번> [외] <건물명> <동/층/호>…` 문자열에서 건물명만 떼어낸다.

    국민은 `KB_Summary.addr`, 농협은 `apw_masterex.Address` 가 이 꼴이라 규칙을 공유한다.
    원문을 그대로 받는다 — 공백을 손대면 화면 표기(`… 세마역  AA02동`)와 어긋날 수 있어
    정리가 필요한 쪽(농협)에서 넣기 전에 정리한다.
    """
    if not text:
        return None
    match = _BUILDING_NAME.search(text)
    if not match:
        return None
    return match.group("name").strip() or None



def _money(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.quantize(Decimal(1)) if value == value.to_integral() else value, "f")


def _area(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.quantize(Decimal("0.01"), rounding=ROUND_DOWN), "f")


def _int(value) -> str | None:
    return None if value is None else str(value)


def is_local_coop(context: DocumentContext) -> bool:
    """지역·품목 농협인가(농협은행이 아닌가).

    지역농협 건만 화면에 **수수료 할인 블록**이 있고, 같은 `실  비` 칸의 뜻도 다르다.
    의뢰처는 감정평가표 머리말(`round0.custpart`)에 있다 — 예 `군자농협 시화지점장`.
    """
    client = round_parse.first(context.rounds).client or ""
    return bool(client) and not client.startswith("농협은행")


# 화면 용도지역 콤보의 실제 선택지(`recon/combo_TBNKNHB24DAMB.md`, 20종).
# 목록에 없는 값은 콤보에서 고를 수 없으니 아예 내지 않는다 — 실측 `개발제한구역` 이
# 그렇다(농협 화면은 그런 땅을 `자연녹지지역` 으로 적는다).
ZONES = frozenset({
    "전용주거지역", "일반주거지역", "준주거지역", "중심상업지역", "일반상업지역",
    "근린상업지역", "유통상업지역", "전용공업지역", "일반공업지역", "준공업지역",
    "보전녹지지역", "생산녹지지역", "자연녹지지역", "농림지역", "관리지역",
    "보전관리지역", "생산관리지역", "계획관리지역", "자연환경보전", "기타",
})


def zone_grade(text: str | None) -> str | None:
    """`제2종일반주거지역` → `일반주거지역`. 화면이 대분류만 받는다.

    콤보 선택지(`ZONES`)에 없으면 비운다 — 고를 수 없는 값이고, 명세표 `YONGDO` 열은
    건물 블록에서 구조·층 조각이 들어오는 자리라(`지2층`) 걸러 내지 않으면 그걸 타이핑한다.
    """
    name = common.zone_name(text)
    if not name:
        return None
    trimmed = _ZONE_GRADE.sub("", name).strip()
    return trimmed if trimmed in ZONES else None


# 법정지목 28종 — 화면은 콤보라 목록에 없는 값을 타이핑하면 안 된다. 명세표 `JIMOK` 은 칸
# 폭 때문에 잘려 오는 일이 있어('공장용지'→'장', '주유소용지'→'주유소') 화이트리스트로 막는다.
LAND_CATEGORIES = frozenset({
    "전", "답", "과수원", "목장용지", "임야", "광천지", "염전", "대", "공장용지",
    "학교용지", "주차장", "주유소용지", "창고용지", "도로", "철도용지", "제방", "하천",
    "구거", "유지", "양어장", "수도용지", "공원", "체육용지", "유원지", "종교용지",
    "사적지", "묘지", "잡종지",
})


def land_category(text: str | None) -> str | None:
    """공부지목 — 농협은 `대` 를 `대지` 로 바꾸지 않고 **원문 그대로** 쓴다(실측 5/5).

    법정지목이 아니면 비운다(잘린 값 방지).
    """
    name = (text or "").strip()
    return name if name in LAND_CATEGORIES else None


def _item_zone(item, outline) -> str | None:
    """명세표 값이 줄바꿈으로 잘렸으면 개요의 온전한 값으로 물러선다."""
    for value in ((item.zone if item else None), outline.zone):
        if value and re.search(r"(지역|구역|지구)", value):
            return value
    return (item.zone if item else None) or outline.zone


# 지번 앞/뒤 가르기는 은행 공용이다(`parse.address`) — 국민도 같은 규칙을 쓴다.
_dong_part = address.dong_part
_after_jibun = address.after_jibun


def site_address(context: DocumentContext, item) -> str | None:
    """화면 `소재지` — 그 **물건이 있는** 법정동까지.

    문서 대표 주소(`apw_masterex.ADDR`)는 다물건 건에서 다른 물건을 가리킬 수 있어
    (실측 2645: 대표=`경기도 의왕시 오전동`, 화면=`경기도 안양시 동안구 호계동`),
    물건 단위인 공부 스캔 주소를 먼저 본다. 스캔이 없는 건(지역농협)은 대표 주소.
    """
    scanned = context.gongbu_address(
        area=(item.area_public if item else None),
        location=(item.location if item else None),
        jibun=(item.jibun if item else None))
    return _dong_part(scanned) or context.site_address


def legal_code(context: DocumentContext, site: str | None) -> str | None:
    """법정동코드 — 물건 소재지가 문서 대표 소재지와 같을 때만 낸다.

    코드는 `apw_masterex` 의 **문서 단위** 값 하나뿐이라(.gam 에도 없다) 다물건 건에서
    다른 동에 있는 물건에 그대로 쓰면 틀린 코드를 넣는다. 그런 건은 사람이 채운다.
    """
    code = context.jibun.legal_code if context.jibun else None
    if not code:
        return None
    doc_site = _dong_part(context.site_address)
    if not (site and doc_site):
        return None
    return code if site.replace(" ", "") == doc_site.replace(" ", "") else None


def building_name(context: DocumentContext, item) -> str | None:
    """구분건물 건물명 — 지번 뒤 ~ 첫 동/층/호 앞을 떼어낸다(국민과 같은 규칙).

    소스를 물건에 가까운 순서로 본다:
      1. **공부 스캔 주소** — 물건 단위라 다물건 문서에서도 그 물건 이름이 나온다
      2. `apw_masterex.Address` — 문서 대표라 다물건이면 다른 물건일 수 있다
      3. 의견서 개요 소재지(따옴표 안 → 위치 기반)

    실측 14건 중 13건 화면과 일치(못 맞은 1건은 개요에 공백이 하나 더 있는 `경희궁 유보라`).
    """
    def squeezed(text: str | None) -> str | None:
        """DB·의견서 문자열은 칸 맞추느라 공백이 여러 칸 들어 있다 — 하나로 줄여 넘긴다."""
        return re.sub(r"\s+", " ", text).strip() if text else None

    scanned = context.gongbu_address(
        area=(item.area_public if item else None),
        location=(item.location if item else None),
        jibun=(item.jibun if item else None))
    for text in (scanned, context.site_full, context.outline.address):
        name = _clean_building_name(_building_name_from(squeezed(text)))
        if name:
            return name
    return _clean_building_name(address.building_name(context.outline.address))


# 건물명이 아닌 것들 — 지번 뒤에서 이름을 떼다 보면 층·동·호 표기나 지번 조각을 집어
# 올 때가 있다(실측: `제4층`·`101동`·`s0`·`10` 이 건물명 칸에 들어갔다).
_NOT_A_NAME = re.compile(r"^(제?\s*\d+\s*층|제?\s*[0-9A-Za-z]{1,4}\s*동|제?\s*\S{1,8}\s*호)$")
# 건물명은 한글 이름이다. 한글이 두 자도 안 되면 이름이 아니라 조각이다.
_NAME_HANGUL = re.compile(r"[가-힣]")
# 이름 끝에 붙은 동 번호 — 화면은 단지 이름만 쓴다(실측 `퍼스트포레2동` → `퍼스트포레`).
_TRAILING_DONG = re.compile(r"(?<=.{2})\s*제?\s*\d+\s*동$")


def _clean_building_name(name: str | None) -> str | None:
    if not name:
        return None
    trimmed = _TRAILING_DONG.sub("", name.strip()).strip()
    if not trimmed or _NOT_A_NAME.match(trimmed):
        return None
    if len(_NAME_HANGUL.findall(trimmed)) < 2:
        return None                       # `s0`·`10` 같은 조각 — 이름이 아니다
    return trimmed


def _floor_ho_dong(item, context) -> tuple[str | None, str | None, str | None]:
    """(해당층수, 호, 동) — 명세행 `제1층 제145호`, 물건표시 `… 제101동 …`.

    **지번 뒤부터만** 본다. 층·호·동 표기는 늘 지번 다음에 오는데, 앞쪽 주소에는
    `제기동` 처럼 `제…동` 꼴의 **법정동 이름**이 있어 건물 동으로 오인된다
    (실측 재현: `… 동대문구 제기동 892-51 제3층 제301호` → 동='기').
    """
    def tail(text: str | None) -> str | None:
        return _after_jibun(text)

    # 공부스캔(등기 표제부) 주소가 1순위 — `… 제이스턴스퀘어동 제1층 제4-102호` 처럼 늘 `제…` 정식 표기라
    # 명세·대표주소가 `이스턴스퀘어동 4-102호`(2672) / `105동 704호`(2820) 로 `제` 없이 적혀 못 읽던 건을 살린다
    # (사용자 제보 2026-09-11: 동·호·해당층수를 사람이 매번 보충했다).
    scanned = _scanned_building_address(context, item)
    texts = [t for t in (tail(scanned),
                         tail(item.location if item else None),
                         tail(item.note if item else None),
                         tail(context.site_full)) if t]
    floor = ho = dong = None
    for text in texts:
        floor = floor or address.floor_of(text)
        ho = ho or address.ho_of(text)
    for text in (tail(scanned), tail(context.site_full), tail(item.location if item else None)):
        dong = dong or address.dong_of(text)
    return floor, ho, dong


def _scanned_building_address(context: DocumentContext, item) -> str | None:
    """이 물건의 공부스캔 **건물 행** 주소(없으면 아무 행). 토지 행(`천호동 580`)엔 층·호가 없어 건물 행을 먼저 본다."""
    rows = identify_gongbu(
        context.gongbu,
        area=(item.area_public if item else None),
        location=(item.location if item else None),
        jibun=(item.jibun if item else None))
    return (next((r.address for r in rows if r.address and r.is_building), None)
            or next((r.address for r in rows if r.address), None))


def display_text(context: DocumentContext, item, *, is_land: bool,
                 building: str | None, dong: str | None, floor: str | None, ho: str | None) -> str | None:
    """화면 `물건표시` 칸 — 지번부터 층·호까지(`580 강동중흥에스클래스 제이스턴스퀘어동 제1층 제4-102호`).

    발송본 실측(2672·2820, 2026-09-11): 사람이 이 칸을 공부스캔 주소의 지번 뒤 그대로 적어 보냈다.
    스캔 주소가 있으면 그 지번 뒤를 쓰고, 없으면 지번·건물명·동·층·호를 `제…` 표기로 조립한다.
    토지형은 지번만(2739 발송본 `657-97`).
    """
    jibun = (item.jibun if item else None)
    if is_land:
        return jibun.strip().rstrip(",") if jibun else None
    scanned = _after_jibun(_scanned_building_address(context, item))
    if scanned and (address.ho_of(scanned) or address.floor_of(scanned)):
        return re.sub(r"\s+", " ", scanned).strip()
    parts = [jibun.strip().rstrip(",") if jibun else None, building,
             f"제{dong}동" if dong and not (building or "").endswith(f"{dong}동") else None,
             f"제{floor}층" if floor else None,
             f"제{ho}호" if ho else None]
    text = " ".join(p for p in parts if p)
    return text or None


def _group_span(context: DocumentContext, item) -> str | None:
    """`일단지등 기호` — 묶음(일단지) 머리행이면 `기호 1~3` 처럼 범위를 적는다.

    묶음 머리 뒤로 이어지는 '금액 없는 **연속 번호** 필지행'이 같은 묶음이다
    (실측 2399: NO=1 머리 + NO=2·3 → `기호 1~3`).

    한 표에 묶음이 둘 이상일 수 있어(실측 2458) **다음 묶음 머리에서 멈춘다**. 번호가
    이어지지 않아도 멈춘다 — 다른 묶음까지 삼키면 틀린 범위를 적게 된다.
    """
    if not (item and item.group_head and item.seq_no and item.seq_no.isdigit()):
        return None
    rows = list(context.details)
    try:
        start = rows.index(item)
    except ValueError:
        return None
    last = int(item.seq_no)
    for row in rows[start + 1:]:
        if row.amount is not None or row.group_head:
            break                                  # 다음 물건 / 다음 묶음 머리
        if not row.seq_no:
            continue
        if not row.seq_no.isdigit() or int(row.seq_no) != last + 1:
            break                                  # 번호가 안 이어지면 다른 묶음
        last = int(row.seq_no)
    return f"기호 {item.seq_no}~{last}" if last != int(item.seq_no) else None


def _following(details, item):
    """`item` 바로 뒤에 이어지는 행들(순서대로)."""
    index = next((i for i, row in enumerate(details) if row is item), None)
    return [] if index is None else list(details[index + 1:])


def _group_members(details, item):
    """묶음 머리 뒤로 이어지는 **연속 번호 필지행**들(자기 자신 포함).

    다음 묶음 머리나 금액 있는 행에서 멈춘다 — 한 표에 묶음이 둘 이상 올 수 있다.
    """
    members = [item]
    if not (item.seq_no or "").isdigit():
        return members
    last = int(item.seq_no)
    for row in _following(details, item):
        if row.amount is not None or row.group_head:
            break
        if not row.seq_no:
            continue
        if not row.seq_no.isdigit() or int(row.seq_no) != last + 1:
            break
        last = int(row.seq_no)
        members.append(row)
    return members


def _subdivisions(details, item):
    """필지 head 뒤의 **소분행**(번호 없이 금액이 붙은 행) — 다음 필지 전까지."""
    found = []
    for row in _following(details, item):
        if row.seq_no is not None:
            break
        if row.amount is not None:
            found.append(row)
    return found


def _total(values) -> Decimal | None:
    kept = [v for v in values if v is not None]
    return sum(kept, Decimal(0)) if kept else None


def _item_values(context: DocumentContext, item, is_land: bool):
    """(공부면적, 사정면적, 감정평가액) — 명세표가 세 가지 꼴로 온다.

    ① **일단지 묶음** — 머리행 AREA2 가 묶음 안 필지들의 AREA1 **합**이면 진짜 묶음이다.
       그때 AREA2·PRICE 는 묶음 전체 값이라 물건 값이 아니다 → AREA1 과 AREA1×단가.
       (실측 2399: 2,612+2,466+3,061 = 8,139 = AREA2 → 사정 2,612 · 2,612×235,000)

    ② **소분(한 필지를 나눠 적음)** — 뒤따르는 번호 없는 금액행들의 AREA2 합이 머리행
       AREA2 와 더해져 **AREA1 과 같아지면** 같은 필지의 조각이다 → 면적·금액을 합친다.
       (실측 1168: 2,940.9 + 181.1 = 3,122 = AREA1 → 사정 3,122 · 금액도 합)

    ③ 그 외 — AREA1/AREA2/PRICE 를 그대로 쓴다.
       ⚠ 괄호가 있어도 ①이 아닌 건이 있다(실측 1737: AREA1 2,105 / AREA2 2,120 인데
         묶음 안 필지 합은 2,387 → 화면은 AREA2 와 PRICE 를 그대로 쓴다).
       ⚠ 건물 유닛에도 괄호가 붙는다(층별 면적 묶음) — ①을 적용하면 안 된다.
    """
    if item is None:
        return (None, None, None)
    public, assessed, amount = item.area_public, item.area_assessed, item.amount
    rows = context.details

    if is_land and item.group_head:
        members = _group_members(rows, item)
        if len(members) > 1 and assessed is not None \
                and assessed == _total(m.area_public for m in members):
            unit_amount = (public * item.unit_price
                           if (public is not None and item.unit_price is not None) else amount)
            return (public, public, unit_amount)          # ① 일단지

    subs = _subdivisions(rows, item)
    if subs and public is not None:
        merged = _total([assessed] + [s.area_assessed for s in subs])
        if merged is not None and merged == public:
            return (public, merged, _total([amount] + [s.amount for s in subs]))   # ② 소분
    return (public, assessed, amount)                     # ③ 그대로


def _fee_values(context: DocumentContext) -> dict[str, str | None]:
    """수수료 칸들. 농협은 `수수료합계 = 절사1000(순수수료 + 실비)` 다(실측 14건).

        순수수료  SUSU            화면 `감정평가(순)수수료`
        실비      구성항목 합       화면 `실  비`  (농협은행 — 부가세 없음)
        수수료합계 SUSUSUM          = 절사1000(SUSU + 실비)
        부가가치세 TAX             = 수수료합계 × 10%
        감정수수료 TOTAL           = 수수료합계 + 부가가치세

    지역농협 화면은 같은 `실  비` 칸에 **부가세를 포함한** 값을 넣는다
    (실측 2445 112,700 → 112,000 × 1.1 = 123,200). 그래서 변형에 따라 달라진다.
    """
    fee = context.fee
    expense = fee.expense_net
    local = is_local_coop(context)
    if local and expense is not None:
        truncated = (expense // EXPENSE_UNIT) * EXPENSE_UNIT
        shown_expense = (truncated * VAT_RATE).quantize(Decimal(1))
    else:
        shown_expense = expense

    values: dict[str, str | None] = {
        "감정평가(순)수수료": _money(fee.net),
        "실  비": _money(shown_expense),
        # 이 사무소 감정서에 특별용역비가 붙은 건이 없다(코퍼스 전건 0). 화면도 0 또는 공란.
        "특별용역비": "0",
        "부가가치세": _money(fee.vat),
        "감정수수료": _money(fee.total),
    }
    if not local:
        return values
    # 지역농협 전용 — 절사 전/후를 따로 보여 준다.
    before = None if (fee.net is None or expense is None) else fee.net + expense
    values.update({
        "추가 할인(증) 여부": None,          # 화면 '없음' 이 기본. 소스가 없어 사람이 고른다
        "할인(증) 사유": None,
        "할인(증) 후 순수수료": _money(fee.net),
        "실비합계(절사 전)": _money(expense),
        "감정료합계(절사 전)": _money(before),
        "감정료합계(절사 후)": _money(fee.subtotal),
        "대출 실행시 청구수수료": _money(fee.total),
    })
    return values


def build(context: DocumentContext, seq_no: str | None = None) -> dict[str, str | None]:
    """농협 담보 화면 — 물건 하나(기본은 첫 물건)."""
    outline = context.outline
    jibun = context.jibun
    parties = context.parties
    standard = context.standard_land
    head = round_parse.first(context.rounds)

    property_rows = tuple(r for r in context.details if r.is_land or r.is_building)
    item = detail.for_sequence(property_rows, seq_no)
    is_land = bool(item and item.kind == detail.UNIT_LAND)
    is_building = bool(item and item.kind == detail.UNIT_BUILDING)

    area_public, area_assessed, amount = _item_values(context, item, is_land)
    item_site = site_address(context, item)
    # 의견서가 현장별로 여러 장인 문서(다현장)는 준공일자·층수·구조·용도지역이 물건마다 다르다
    # (실측 2645: 대표 의견서=의왕 오전동 2003-12-13/12층, 화면 물건=안양 호계동 2021-03-03/21층).
    # 현장이 하나뿐인 보통 문서는 대표 = context.outline 이라 종전과 값이 같다.
    outline = context.site_for(item.jibun if item else None, item_site).outline

    floor_no, unit_no, dong_no = _floor_ho_dong(item, context)
    main_no, sub_no = _split_jibun(item.jibun if item else None)
    if main_no is None and jibun is not None:
        main_no, sub_no = jibun.bun1, jibun.bun2

    # 화면 `평가금액` 은 **감정평가표의 총액**(round_price)이다 — 문서 총액(gam_info.price)이
    # 아니다. 표가 여러 장이면 표마다 총액이 다를 수 있고 화면이 어느 표를 보는지 못 가르므로,
    # 표별 총액이 갈리면 비운다(실측 2645: 표 2장이지만 둘 다 338,000,000 이라 채운다).
    amounts = {r.amount for r in context.rounds if r.amount is not None}
    if len(amounts) == 1:
        document_total = amounts.pop()
    elif amounts:                        # 표마다 총액이 갈린다 → 어느 표인지 못 가르므로 비운다
        document_total = None
    else:                                # 표에 총액이 없으면 문서 총액으로 물러선다
        document_total = context.total_amount

    # 지역농협 건은 **작성자 콤보 6칸(대표,지사장·대표,지사장2·심사자·평가사명1~3)을 아예
    # 비워 둔다**(실측 2445·2388·2374 전건 공란 — 소스에는 값이 있는데도). 관례로 보고 따른다.
    coop = is_local_coop(context)

    def combo(value: str | None) -> str | None:
        return None if coop else value

    values: dict[str, str | None] = {
        # 작성자
        "담보번호": context.client_doc_no,
        "입력자성명": parties.sender,        # apw_masterex.Sendman → 직원표 EMP (실측 14/14)
        "입력자연락처": None,                # 이 DB 에 전화번호가 없다(BANK24 쪽 사용자 정보)
        "기준시점": context.price_point_date,
        "평가사명": parties.appraiser(0),   # 텍스트 칸이라 지역농협도 채워져 있다
        "대표,지사장": combo(parties.boss),
        "대표,지사장2": None,                 # 실측 14/14 공란
        "심사자": combo(parties.reviewer or head.reviewer),
        "평가사명1": combo(parties.appraiser(0)),
        "평가사명2": combo(parties.appraiser(1)),
        "평가사명3": combo(parties.appraiser(2)),
        # 물건 — `일련번호` 는 화면이 관리하는 앵커(form.ANCHOR_LABELS)라 우리가 쓰지 않는다.
        # 다물건 문서에서 우리 물건 순번과 화면 슬롯 번호가 다를 수 있어 값도 내지 않는다.
        "물건기호": item.seq_no if item else None,
        # 라벨이 없거나 겹치는 칸은 **위치**로 짚는다(`물건기호`~`번지구분` 사이 7칸 중).
        # 실측 14건에서 구성이 완전히 같다 — 0 물건종류 · 1 부동산구분 · 2 우편번호 ·
        # 3 법정동코드 · 4 소재지(짧) · 5 소재지(김) · 6 물건표시.
        BOX_KIND: item.kind if item else None,          # 토지 / 건물 (14/14 일치 확인)
        BOX_LEGAL_CODE: legal_code(context, item_site),
        BOX_SITE: item_site,
        # 화면 콤보는 `집합상가`·`아파트형공장`·`기타토지` 처럼 은행 분류라 소스에서 못 낸다
        # (실측 14건: 지목과 같은 건 2건뿐, 같은 지목 '대' 가 단독주택·상가·대 로 갈린다).
        "물건종류": None,
        "번지구분": jibun.jibun_kind if jibun else None,
        "본번지": main_no,
        "부번지": sub_no,
        # 등기번호는 **물건 면적**으로 공부스캔 행을 좁힌다 — 순번(No)은 물건과 어긋난다
        # (실측 2625: 408호·409호가 둘 다 No=3, 2399: 세 필지가 전부 No=1).
        "등기번호": context.registry_no(
            kind=item.kind if item else None, seq_no=item.seq_no if item else None,
            area=area_public, location=(item.location if item else None),
            jibun=(item.jibun if item else None)),
        # 소유자명은 **감정평가표 괄호 소유자(채무자)** 기준 — 등기 소유자가 아니다(2820: 등기 한국자산신탁 ↔ 화면 김찬양,
        # 담당자 지적 2026-09-11). 괄호가 없으면 등기 소유자.
        "소유자명": head.debtor or head.owner,
        "평가금액": _money(document_total),
        "감정평가액": _money(amount),
        # 단가는 **토지 명세행**의 것만 쓴다. land_list 의 건물 유닛행에도 DANGA 가 있어
        # 그대로 쓰면 건물형 화면(실측 전건 0/공란)에 엉뚱한 단가를 타이핑한다.
        # 건물형 화면은 `평가단가` 를 **0** 으로 적는다(발송본 2672·2820 실측 0, 2026-09-11).
        "평가단가": _money(item.unit_price if item else None) if is_land else ("0" if is_building else None),
        "사정면적": _area(area_assessed),
        "비   고": None,
        # 표준지 — 비교표준지표가 있는 건만 채워진다
        BOX_STD_SITE: standard.address,
        "표준지공시지가": _money(standard.price),
        "공시기준일": standard.base_date,
        # 수익환원법 — 실측 14건 모두 화면이 비어 있다. 소스도 확인된 게 없다.
        "총수익": None,
        "경비비율": None,
        "순이익": None,
        "환원이율": None,
    }
    values.update(_fee_values(context))

    if is_land:                              # 토지형 화면에만 있는 칸
        values.update({
            "공부지목": land_category(item.category if item else None),
            "용도지역": zone_grade(_item_zone(item, outline)),
            "공부면적": _area(area_public),
            # `일단지등 기호` 는 사람이 자유롭게 적는다 — 73건 순회에서 화면 표기가
            # `기호1)~6)` · `기호12)` · `1` 로 제각각이라 형식을 맞출 수 없다. 비운다.
            # (범위 자체는 `_group_span` 이 계산한다 — 표기 규칙이 정해지면 켜면 된다.)
            "일단지등 기호": None,
            BOX_DISPLAY: display_text(context, item, is_land=True, building=None,
                                      dong=None, floor=None, ho=None),
        })
    if is_building:                          # 건물형 화면에만 있는 칸
        name = building_name(context, item)
        values.update({
            "건물명": name,
            BOX_DISPLAY: display_text(context, item, is_land=False, building=name,
                                      dong=dong_no, floor=floor_no, ho=unit_no),
            "동": dong_no,
            "호": unit_no,
            "해당층수": floor_no,
            "총층수": _int(outline.ground_floors),
            # 화면은 **소스 원문 표기를 따른다**(`철근콘크리트조` 는 그대로) → to_gujo=False.
            # 사람이 치는 칸이라 흔들림이 있다 — 73건 순회 실측으로 두 방식을 재 봤다:
            #   원문 유지  … 소스=`…조` 인데 화면이 `…구조` 인 건 4건 불일치
            #   `…구조` 통일 … 소스=`…조` 이고 화면도 `…조` 인 건 7건 불일치
            # 원문 유지가 낫다(국민은 반대로 화면이 `…구조` 로 통일돼 있어 규칙이 다르다).
            "건물구조": common.best_struct(
                item.struct if item else None, outline.struct, to_gujo=False),
            "준공일자": outline.approval_date,
            "내용년수": "0",                  # 소스가 없다 — 화면은 전부 0 이라 0 을 적는다(발송본 2672·2820 실측, 2026-09-11)
            "잔존년수": "0",
            "공부면적(전용면적)": _area(area_public),
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
