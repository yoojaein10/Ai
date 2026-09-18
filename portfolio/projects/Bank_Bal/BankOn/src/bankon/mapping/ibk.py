"""기업은행 담보(`TBNKKIB24DAMB`) 필드 매핑 — 정찰 2026-08-28 (recon/fields_ibk_damb.md, 2704·2683 실측).

국민과 같은 2단 구조(헤더 + 왼쪽 물건 그리드)지만 **세부내역 그리드가 없다**: 물건 1개 = 가운데 물건 패널 +
오른쪽 탭 1장(토지/건물/기계기구 — 물건종류에 따라 같은 자리에 겹쳐 뜬다). 그래서 물건 분할 규칙이 국민과 다르다:

    ★ 명세표 **금액 있는 행 1개 = 물건 1개** (토지 필지·건물 층별 소분행 모두. 실물 2683: 대지 1 / 건물 1층 / 건물 지하층 = 3물건)
      — 화면 안내 "명세표 상의 사정 면적별로 물건을 추가하여 단가를 각각 입력(단가를 합산하여 기재 금지)".

수수료(실측 2704·2683, gam_info 와 동일):
    감정수수료 = TOTAL   순수수료 = SUSU   실 비 = 실비 구성항목 합(부가세 전; Fee.expense_net — SILBISUM 은 낡을 수 있음: 2683 69,000 vs 화면 69,900)
    부가세 = TAX(= (SUSU+실비) 1,000원 절사분의 10%)   특별용역비 = APW_Bill.YONGYEUK(costs 를 주면), 없으면 항상 '0'(기업 규칙, 2026-09-01)

라벨 키 규칙(form.REGIONS 로 패널을 가른다 — 창 상대 x):
    '헤더:물건종류'   헤더 텍스트칸(가운데 물건종류 콤보와 라벨이 같다)
    '물건:…'          가운데 물건 패널(일련번호·법정동코드·소재지·번지구분·본/부번지·물건종류·평가금액·부동산구분)
    '탭:…'            오른쪽 탭. 토지/건물 탭이 같은 라벨(사정면적·평가단가·감정평가액·비고)을 같은 자리에 겹쳐 두므로
                      **보이는 탭**(driver.find_by_label 이 숨은 컨트롤 제외)만 잡힌다 → 물건종류 콤보를 먼저 골라 탭을 바꾼 뒤 채운다.

미확정(콤보 목록 미수집 — list_combo_items --probe 뒤 손볼 것):
    - 물건 패널 '물건종류' 콤보: 목록 17개뿐(대지·건물·국산/도입 기계·기구·구축물·중기·자동차·선박·항공기·기타, 수집 2026-09-01
      recon/combo_ibk.md) → 토지는 지목과 무관하게 **항상 '대지'**(지목은 토지 탭 '공부지목' 29개 콤보에), 건물 '건물'.
    - 탭 '용도지역' 콤보: '…지역' 꼬리 있음(일반공업지역·자연녹지지역). 문서 '개발제한구역'은 담당자가 개요의 용도지역(자연녹지)으로
      바꿔 넣음(2683) → _ibk_zone 이 같은 규칙으로 바꾼다.
    - 헤더 '물건종류' 텍스트: 건물 있으면 개요 이용상황('단독주택'), 토지뿐이면 대표 지목('공장용지') — 2건 실측 기반 추정.
    - 기계기구 탭 항목 미정찰 → 기계기구 물건은 물건 패널 값만 낸다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from ..codes import common
from ..codes import common as common_codes
from ..model import DocumentContext
from ..parse import address as _address
from ..parse import buildings, detail
from ..parse import outline as outline_mod
from ..parse import units as unit_table
from ..parse.cost import representative
from .kookmin import _address_only, split_jibun

FORM_CLASS = "TBNKKIB24DAMB"

# 창 왼쪽 기준 x 범위(정찰 덤프 창 상대좌표: 헤더 라벨 x=17·393, 물건 패널 라벨 x=202, 탭 라벨 x=509).
REGIONS = {"헤더": (0, 190), "물건": (190, 500), "탭": (500, 810)}

# 라벨 없는 칸 — 기준 라벨 입력칸 좌상단 기준 (dx, dy). 본번지 칸 @323,328 기준.
POSITIONAL = {
    "물건:법정동코드": ("본번지", 0, -70, "TcxDBTextEdit"),      # 주소검색 버튼 옆 코드칸 @253,328
    "물건:소재지": ("본번지", -126, -48, "TcxDBTextEdit"),       # @275,202 (246폭)
}

# 항상 덮어쓰는 칸 — 아직 없음(빈칸만 채움). 은행 선입력 확인 뒤 추가.
ALWAYS_OVERWRITE = frozenset()

OBJECT_LAND, OBJECT_BUILDING, OBJECT_MACHINE = "토지", "건물", "기계기구"
# 기계기구 물건의 물건종류 콤보 = '국산기계'(업무팀 확정 2026-09-07 — 종전 '기계기구' 는 목록에 없어 거부, 2776). 도입기계 판별 규칙은 없음.
MACHINE_COMBO = "국산기계"

# 물건 패널 '물건종류' 콤보 목록(recon/combo_ibk.md, 2026-09-01): 대지·건물·국산기계·국산기구·국산구축물·국산중기·국산자동차·국산선박·
# 국산항공기·도입기계·도입기구·도입구축물·도입중기·도입자동차·도입선박·도입항공기·기타 — 지목 항목이 없다. 2706 LIVE 에서 '전'·'목장용지'가
# 콤보 항목 없음으로 거부돼 확인. 토지는 항상 '대지'(지목은 탭 '공부지목'), 기계기구는 국산/도입 판별 규칙이 없어 아직 '기계기구'(거부→수동).

# 명세 테이블 중 물건이 되는 패밀리(임대료 표 등은 제외).
_OBJECT_TABLES = ("land_list", "pbs_land", "section_build", "detail_machin")
_HEAD_SEQ = re.compile(r"^[가-힣]$")          # 건물 동 머리행 NO: 가·나·다…
_FLOOR_TEXT = re.compile(r"^(지하\s*\d*층?|지상\s*\d+층|\d+층|옥탑\s*\d*층?|지하층)$")
_ZONE_TAIL = ("지역", "구역", "지구")


def _money(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.quantize(Decimal(1)) if value == value.to_integral() else value, "f")


def _area(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.quantize(Decimal("0.01"), rounding=ROUND_DOWN), "f")


def _int(value: int | None) -> str | None:
    return None if value is None else str(value)


@dataclass(frozen=True)
class ObjectSpec:
    """물건 하나 = 명세표 금액 행 1개. head 는 그 행이 속한 머리행(필지 head / 건물 동 머리 '가')."""

    kind: str                      # 토지 | 건물 | 기계기구
    row: detail.DetailRow          # 금액 있는 행(면적·단가·감정가 출처)
    head: detail.DetailRow         # 지번·지목·구조 출처(소분행이면 머리행, 아니면 row 자신)


def _kind_of_table(table: str) -> str:
    name = table.lower()
    if name.startswith("detail_machin"):
        return OBJECT_MACHINE
    if name.startswith("section_build"):
        return OBJECT_BUILDING
    return OBJECT_LAND


def split_objects(rows: tuple[detail.DetailRow, ...]) -> list[ObjectSpec]:
    """명세표 → 물건 목록(금액 있는 행 1개 = 물건 1개).

    land_list 는 토지 필지(NO 숫자)와 건물 동 머리(NO 가/나…) 뒤에 seq None 소분행이 잇따른다:
      - 숫자 head 뒤 소분행(도로저촉 등) → 토지 물건(지번·지목은 head 것)
      - 한글 head 뒤 소분행(층별 1층/지하층, 2683) → 건물 물건(구조·준공일은 head 기호로 의견서 표에서)
    section_build(구분건물)·detail_machin 은 행 자체가 물건이다. 금액 없는 행(도로 등)은 물건으로 세지 않는다.
    """
    objects: list[ObjectSpec] = []
    head: detail.DetailRow | None = None
    head_kind: str | None = None
    for row in rows:
        if not row.table.lower().startswith(_OBJECT_TABLES):
            continue
        table_kind = _kind_of_table(row.table)
        if row.seq_no and row.seq_no.strip().isdigit():
            head, head_kind = row, table_kind
        elif row.seq_no and _HEAD_SEQ.match(row.seq_no.strip()):
            head, head_kind = row, (OBJECT_BUILDING if table_kind == OBJECT_LAND else table_kind)
        elif row.seq_no or head is None or table_kind != OBJECT_LAND:
            head, head_kind = row, table_kind      # 머리행 없는 표(기계·구분건물) — 행 자신이 머리
        if row.amount is None and not _excluded_parcel(row):
            continue
        kind = head_kind or table_kind
        if head is not None and head is not row and head.table != row.table:
            head, kind = row, table_kind
        objects.append(ObjectSpec(kind, row, head or row))
    return objects


_DONG_NO = re.compile(r"제?\s*(\d+)\s*동$")
_UNIT_DONG = re.compile(r"제?\s*(\d+)\s*동(?![가-힣])")     # 구분건물 주소의 '제101동'/'101동'(숫자 동만)
_YEARS = re.compile(r"\(\s*(\d+)\s*/\s*(\d+)\s*\)")           # 기계 명세 부기 '0.733(11/15)' = (잔존연수/내용연수)


def _dong_no(head: detail.DetailRow, info, context: DocumentContext) -> str | None:
    """건물 탭 '동/호'의 동 번호 — 명세 머리행 아래 지번 칸의 '제1동'/'1동'(숫자일 때만; '가동' 은 비움). 선택 칸이라 담당자마다 다름:
    2636 발송본은 채웠고 2706 발송본은 비웠음(2026-09-01 대조) → 명세표에 있으면 채우는 쪽으로. 의견서 건물표 꼬리로는 채우지 않는다."""
    seen = False
    for r in context.details:
        if not seen:
            seen = r is head
            continue
        if r.table != head.table or r.seq_no:
            break
        m = _DONG_NO.search((r.jibun or "").replace(" ", ""))
        if m:
            return m.group(1)
        if r.amount is not None:
            break
    return None


def _floor_label(row: detail.DetailRow) -> str | None:
    """건물 소분행의 층 표시('1층'/'지하층') — land_list 파서가 YONGDO 칸(zone)으로 읽는다(2683). 없으면 비고·소재지."""
    for text in (row.zone, row.note, row.location, row.category):
        t = (text or "").strip()
        if t and _FLOOR_TEXT.match(t):
            return t
    return None


_FULLWIDTH = str.maketrans('0REDACTED_CONFIGURE_LOCALLY789', "０１２３４５６７８９")


def _ibk_zone(zone: str | None, outline_zone: str | None, legal_text: str | None = None) -> str | None:
    """탭 '용도지역' 콤보 — '…지역' 꼬리 있음. 개발제한구역이면 개요의 다른 용도지역(자연녹지)으로(담당자 관례 2683).
    둘 다 없으면 의견서 공법관계 문장(legal_text)에서 첫 용도지역. 콤보 목록은 '제２종'처럼 **전각 숫자**(2682 실측)."""
    text = re.sub(r"\s+", "", zone or "")
    if not text or "개발제한" in text:
        tokens = [t for t in re.split(r"[\s,/·]+", outline_zone or "") if t and "개발제한" not in t]
        text = tokens[0] if tokens else ""
    if not text:
        text = outline_mod.zone_from_text(legal_text) or ""
    if not text:
        return None
    if not text.endswith(_ZONE_TAIL):
        text += "지역"
    return re.sub(r"제([0-9])종", lambda m: "제" + m.group(1).translate(_FULLWIDTH) + "종", text)


def object_combo(kind: str, category: str | None) -> str | None:
    """물건 패널 '물건종류' 콤보."""
    if kind == OBJECT_BUILDING:
        return "건물"
    if kind == OBJECT_MACHINE:
        return MACHINE_COMBO
    return "대지" if kind == OBJECT_LAND else None


# 헤더 '물건종류' 텍스트 — 건물 용도 키워드 → 은행 표기(발송 실물 2026-08-31: 2714 공장 / 2719 아파트형공장 / 2682·2684 근린생활시설 /
# 2683 단독주택). 여러 용도가 섞이면 앞선 키워드 우선(2682 '주택 및 근린생활시설'·2684 주택+근린 → 근린생활시설).
_HEADER_TYPE_BY_USE = (
    ("지식산업센터", "아파트형공장"), ("아파트형공장", "아파트형공장"), ("공장", "공장"), ("창고", "창고"),
    ("근린생활", "근린생활시설"), ("아파트", "아파트"), ("오피스텔", "오피스텔"), ("다세대", "다세대주택"), ("연립", "연립주택"),
    ("다가구", "다가구주택"), ("단독주택", "단독주택"), ("주택", "단독주택"), ("업무", "업무시설"), ("숙박", "숙박시설"),
)


def header_object_type(specs: list[ObjectSpec], context: DocumentContext) -> str | None:
    """헤더 '물건종류' 텍스트 — 건물 있으면 용도 키워드(의견서 개요 주용도 + 건물표·명세 머리행 용도), 토지뿐이면 대표 지목('공장용지')."""
    outline = context.outline
    if any(s.kind == OBJECT_BUILDING for s in specs):
        # 지목이 공장용지면 건물 용도가 근생이어도 '공장'(2714: 근린생활시설(제조업소) → 화면 '공장').
        # ⚠️이용상황 '공업용'만으로는 '공장'이 아니다 — 2818 실측(지목 대·이용상황 공업용·건물 제2종근린생활시설)에서
        # 화면은 '근린생활시설'이었다. 지목은 공부(등기)에서 오지만 이용상황은 감정사 판단이라 약한 신호다(2026-09-10).
        if any(s.kind == OBJECT_LAND and common.land_category(s.head.category) == "공장용지" for s in specs):
            return "공장"
        uses = [outline.building_use or ""] + [b.use or "" for b in context.buildings]             + [s.head.category or "" for s in specs if s.kind == OBJECT_BUILDING] + [outline.usage or ""]
        text = " ".join(uses).replace(" ", "")
        for key, name in _HEADER_TYPE_BY_USE:
            if key in text:
                return name
        return outline.usage or outline.building_use or None
    if any(s.kind == OBJECT_MACHINE for s in specs) and not any(s.kind == OBJECT_LAND for s in specs):
        return "기계기구"
    for s in specs:
        if s.kind == OBJECT_LAND and s.head.category:
            return common.land_category(s.head.category)
    return common.land_category(outline.category) if outline.category and len(outline.category) > 1 else None


def _parcel_jibun(spec: ObjectSpec, specs: list[ObjectSpec], context: DocumentContext) -> tuple[str | None, str | None]:
    """본/부번지 — 머리행 지번('461-17,') → 없으면 직전 토지 물건 지번 → 문서 대표 지번(APW)."""
    for text in (spec.head.jibun, spec.row.jibun):
        main_no, sub_no = split_jibun(text)
        if main_no:
            return main_no, sub_no
    for other in specs:
        if other.kind == OBJECT_LAND:
            main_no, sub_no = split_jibun(other.head.jibun)
            if main_no:
                return main_no, sub_no
    jibun = context.jibun
    return (jibun.bun1, jibun.bun2) if jibun else (None, None)


def _gongbu_for(spec: ObjectSpec, context: DocumentContext):
    """이 물건의 공부스캔 행 — **지번이 같은** 행. 다현장 문서는 물건마다 현장이 달라서
    문서의 첫 토지 행을 그냥 쓰면 다른 현장 주소가 들어간다(2818 삼성동 호가 김포 주소로 나옴)."""
    key = _address.jibun_key(spec.head.jibun) or _address.jibun_key(spec.row.jibun)
    if not key:
        return None
    for g in context.gongbu:
        if g.address and _address.jibun_key(_address.after_jibun(g.address)) == key:
            return g
    return None


def _object_address(spec: ObjectSpec, context: DocumentContext) -> str | None:
    """소재지(동까지) — 공부스캔 주소가 가장 온전(2683 명세 location 은 '서울특별시 수서동'으로 구가 빠짐).
    지번이 맞는 행을 먼저 보고(다현장), 없으면 종전대로 첫 토지 행."""
    mine = _gongbu_for(spec, context)
    if mine is not None:
        return _address_only(mine.address)
    for g in context.gongbu:
        if g.is_land and g.address:
            return _address_only(g.address)
    loc = (spec.head.location or "").strip()
    if _is_ditto_place(loc):
        # '동 소'(同所) = 같은 표 앞 토지와 같은 곳(2636 통합 명세표 건물 머리행) → 그 토지의 소재지
        loc = _land_location(context) or ""
    if loc and len(loc.split()) >= 3 and re.search(r"(동|리|읍|면|가)$", _address_only(loc) or ""):
        return _address_only(loc)
    for g in context.gongbu:
        if g.address:
            return _address_only(g.address)
    return _address_only(loc) or _address_only(context.kb_summary.address or context.outline.address)


def _is_ditto_place(text: str | None) -> bool:
    return (text or "").replace(" ", "") in ("동소", "同所", "상동")


def _land_location(context: DocumentContext) -> str | None:
    """같은 명세표의 첫 토지 물건 소재지(조각 병합된 온전한 것). 건물 머리행 '동 소' 승계용."""
    for d in context.details:
        if d.is_land and d.seq_no and d.seq_no.strip().isdigit() and d.location and not _is_ditto_place(d.location):
            return d.location
    return None


_STRUCT_OK = re.compile(r"(조|구조|스틸|판넬|패널)$")


def _struct_raw(text: str | None) -> str | None:
    """건물구조 — 기업 폼은 '벽돌조' 그대로(국민처럼 '…구조' 정규화 안 함, 실측 2683). 지붕('/ 슬래브지붕', '경량판넬지붕')과
    괄호 부기는 뗀다. 구조로 안 보이는 값(면적 '76.82', 층 '1층' 등 word-wrap 조각)은 None."""
    if not text:
        return None
    head = re.split(r"\s*/\s*", text)[0]
    head = re.sub(r"\s*[（(].*$", "", head).strip()
    words = [w for w in head.split() if not w.endswith("지붕")]
    head = " ".join(words).strip()
    return head if head and _STRUCT_OK.search(head) else None


def _pick_struct(*candidates: str | None) -> str | None:
    """구조 후보(의견서 건물표 → 명세 머리행 gujo → 머리행 YONGDO 칸(land_list 는 건물 구조가 여기로 옴) → 개요) 중 첫 유효값."""
    for c in candidates:
        value = _struct_raw(c)
        if value:
            return value
    return None


def _amount_sum(specs: list[ObjectSpec], kind: str) -> Decimal | None:
    values = [s.row.amount for s in specs if s.kind == kind and s.row.amount is not None]
    return sum(values, Decimal(0)) if values else None


def _excluded_parcel(row: detail.DetailRow) -> bool:
    """감정평가외 토지 필지(도로 등): NO·지번 있는 토지행인데 PRICE 가 글자. 은행 관례는 대지 행으로 등록하되 단가 1·감정평가액 0
    (2636 발송본 708-4 도로 258㎡·280㎡ — 국민 세부 토지행 관례와 같음)."""
    return (row.excluded and row.is_land and bool(row.seq_no) and row.seq_no.strip().isdigit()
            and (row.area_assessed is not None or row.area_public is not None))


def _group_area(head: detail.DetailRow, context: DocumentContext) -> Decimal | None:
    """일단지 묶음 머리행의 공부면적 = 머리 필지 + 묶음 안 후속 필지(NO 숫자·금액 없음·괄호 '|'/'>') 면적 합.
    2706 발송본: 1124(240) + 1124-1(2,292) 일단지 → 화면 공부면적 2,532(=사정면적)."""
    if not head.group_head or head.area_public is None:
        return head.area_public
    total, seen = head.area_public, False
    for r in context.details:
        if not seen:
            seen = r is head
            continue
        if r.table != head.table:
            break
        if not r.seq_no:
            continue
        if r.amount is None and r.group_member and not r.excluded and r.seq_no.strip().isdigit():
            total += r.area_public or Decimal(0)
            continue
        break
    return total


def _land_tab(spec: ObjectSpec, context: DocumentContext, site=None) -> dict[str, str | None]:
    row, head = spec.row, spec.head
    site = site or context.primary_site          # 물건이 속한 현장(다현장 문서에서만 갈린다)
    if row is head and _excluded_parcel(row):
        area = row.area_assessed if row.area_assessed is not None else row.area_public
        return {
            "탭:공부지목": common.land_category(head.category),
            "탭:용도지역": _ibk_zone(head.zone, site.outline.zone, site.legal_text),
            "탭:공부면적": _area(area), "탭:사정면적": _area(area),
            "탭:평가단가": "1", "탭:감정평가액": "0", "탭:비 고": None,
        }
    public = row.area_public if row.area_public is not None else head.area_public
    if row is head:
        public = _group_area(head, context)
    return {
        "탭:공부지목": common.land_category(head.category),
        "탭:용도지역": _ibk_zone(head.zone or row.zone, site.outline.zone, site.legal_text),
        "탭:공부면적": _area(public),
        "탭:사정면적": _area(row.area_assessed if row.area_assessed is not None else row.area_public),
        "탭:평가단가": _money(row.unit_price),
        "탭:감정평가액": _money(row.amount),
        # 소분행(도로저촉 등)은 그 내용을 비고에(실물 2704 토지 비고 빈칸).
        "탭:비 고": (row.category or row.note) if row is not head else None,
    }


def _building_tab(spec: ObjectSpec, context: DocumentContext, *, split_floors: bool = False,
                  site=None) -> dict[str, str | None]:
    """split_floors: 같은 동(머리행)이 층별 금액행 2개 이상으로 쪼개진 경우 → 비고에 층('1층'/'지하층', 2683). 1행뿐이면 비고 빈칸(2684)."""
    row, head = spec.row, spec.head
    site = site or context.primary_site
    assessed = row.area_assessed if row.area_assessed is not None else row.area_public
    info = buildings.by_mark(site.buildings, head.seq_no)
    same_mark = [c for c in context.cost_layers if c.mark == head.seq_no]
    # 같은 기호에 층/부속이 여럿이면 명세 단가와 같은 결정단가의 층(2706 '다': 1층 철파이프조 25/10 · 부속 시멘트블럭조 40/11).
    cost = (next((c for c in same_mark if c.unit_price is not None and c.unit_price == row.unit_price), None)
            or (same_mark[0] if same_mark else None) or representative(context.cost_layers))
    # 구조는 **명세표 머리행 표기 그대로**(2714 '블럭구조', 2684 '부록크조' — 의견서 표의 '블록구조'가 아님, 대조 2026-08-31).
    struct = _pick_struct(head.struct, head.zone, row.struct, info.struct if info else None, site.outline.struct)
    return {
        "탭:건물구조": struct,
        "탭:동/호": _dong_no(head, info, context),
        "탭:준공일자": (info.approval_date if info else None) or site.outline.approval_date,
        "탭:내용년수": _int(cost.useful_years if cost else None),
        "탭:잔존년수": _int(cost.remaining_years if cost else None),
        # 공부면적(전용면적) 칸에도 사정면적을 넣는다(2684: 공부 36.78·사정 60.33 → 화면 둘 다 60.33; 2683·2714 는 같은 값).
        "탭:공부면적(전용면적)": _area(assessed),
        "탭:사정면적": _area(assessed),
        "탭:평가단가": _money(row.unit_price),
        "탭:감정평가액": _money(row.amount),
        "탭:비 고": _floor_label(row) if split_floors else None,
    }


# ── 구분건물(section_build) — 발송 실물 2719(2호)·2682(6호) 덤프 2026-08-31 ─────────────────────────────
# ★호 1개 = 물건 2개: [건물](물건종류 '건물') + [대지](물건종류 '대지', 대지권) — 둘 다 부동산구분 '집합건물', 등기소기준 고유번호 =
#   그 호 전유부분 등기번호. 건물 탭: 구조(공부스캔 '전유부분 철근콘크리트조' 그대로)·준공일자·전용면적=사정면적·비준가액, 내용/잔존/단가 0(비움).
#   대지 탭: 공부지목 = 등기 토지 지목(공장용지/대), 용도지역 = 공법관계 문장(준공업지역/제２종일반주거지역), 공부면적=사정면적 = 호별 대지권면적
#   (의견서 호별 표), 단가·감정평가액 0(비움). 토지평가금액 0, 건물평가금액 = 총액.
CONDO_KIND = "집합건물"
_HO = re.compile(r"제\s*([0-9A-Za-z가-힣\-]+)\s*호")


def _unit_scans_raw(context: DocumentContext) -> list[dict]:
    """공부스캔 건물 행(호별 전유부분) → [{registry, ho, struct, area, land_category}] 순서대로(같은 등기번호 1개)."""
    out, seen = [], set()
    land_note = {g.unique_no: g.note for g in context.gongbu if g.is_land and g.unique_no}
    for g in context.gongbu:
        if not g.is_building or not g.unique_no or g.unique_no in seen:
            continue
        seen.add(g.unique_no)
        m = _HO.search(g.address or "")
        note = re.sub(r"^전유부분\s*", "", (g.note or "").strip())
        out.append({"registry": g.registry_no, "ho": m.group(1) if m else None, "struct": _struct_raw(note),
                    "area": g.area, "land_category": land_note.get(g.unique_no), "address": g.address})
    return out


def _condo_objects(spec: ObjectSpec, n: int, scans: list[dict], context: DocumentContext, base: dict,
                   site=None) -> list[dict]:
    row = spec.row
    site = site or context.primary_site
    idx = n - 1
    scan = scans[idx] if idx < len(scans) else None
    if scan and row.area_public is not None and scan["area"] is not None and scan["area"] != row.area_public:
        scan = next((sc for sc in scans if sc["area"] == row.area_public), scan)   # 순서 어긋나면 전용면적으로
    unit = unit_table.by_mark(site.units, row.seq_no) if row.seq_no else None
    if unit is None and idx < len(site.units):
        unit = site.units[idx]
    if unit is not None and row.area_public is not None and unit.area_exclusive not in (None, row.area_public):
        unit = next((u for u in site.units if u.area_exclusive == row.area_public), unit)
    land_cat = (scan["land_category"] if scan else None) or next((g.note for g in context.gongbu if g.is_land and g.note), None)
    registry = scan["registry"] if scan else context.registry_no(kind="건물")
    assessed = row.area_assessed if row.area_assessed is not None else row.area_public
    land_right = unit.area_land_right if unit else None
    # 동/호: 호 = 의견서 호별 표('제3층 제301호') 또는 공부스캔 주소, 동 = 주소의 '제N동'(숫자일 때만). 라벨 '동/호' 아래 칸 2개(동, 호@2).
    unit_text = " ".join(x for x in ((unit.unit if unit else None), (scan["address"] if scan else None), row.location) if x)
    ho_m = _HO.search(unit_text)
    dong_m = _UNIT_DONG.search(unit_text.replace(" ", ""))
    building = {
        "_kind": OBJECT_BUILDING, **base,
        "물건:물건종류": "건물", "물건:부동산구분": CONDO_KIND, "물건:등기소기준 고유번호": registry,
        "탭:건물구조": (scan["struct"] if scan else None) or _pick_struct(site.outline.struct),
        "탭:동/호": dong_m.group(1) if dong_m else None,
        "탭:동/호@2": ho_m.group(1) if ho_m else None,          # 2776 실측(2026-09-07): 동·호가 비어 있었음 → 채운다
        "탭:준공일자": site.outline.approval_date,
        # 구분건물은 내용·잔존년수가 없으니 **0**, 단가도 0 을 실제로 넣는다(업무팀 확정 2026-09-07 — 종전 비움).
        "탭:내용년수": "0", "탭:잔존년수": "0",
        "탭:공부면적(전용면적)": _area(assessed), "탭:사정면적": _area(assessed),
        "탭:평가단가": "0", "탭:감정평가액": _money(row.amount), "탭:비 고": None,
    }
    land = {
        "_kind": OBJECT_LAND, **base,
        "물건:물건종류": "대지", "물건:부동산구분": CONDO_KIND, "물건:등기소기준 고유번호": registry,
        "탭:공부지목": common_codes.land_category(land_cat),
        "탭:용도지역": _ibk_zone(None, site.outline.zone, site.legal_text),
        "탭:공부면적": _area(land_right), "탭:사정면적": _area(land_right),
        # 구분건물 대지는 단가·금액 **0 원**을 실제로 넣는다(업무팀 확정 2026-09-07 — 종전엔 비움). 0 가드 예외 칸(form.ZERO_ALLOWED*).
        "탭:평가단가": "0", "탭:감정평가액": "0", "탭:비 고": None,
    }
    return [building, land]


def _machine_tab(spec: ObjectSpec, context: DocumentContext) -> dict[str, str | None]:
    """기계기구 탭(작성 폼 실화면 2776, 2026-09-07): 기계기구명·내용년수·잔존년수·제작일자·수 량·취득단가·감정평가액·비 고.

        기계기구명 ← 명세 machine_detail('PUMA GT 2600') / 의견서 기계기구 표 명칭
        내용·잔존년수 ← 명세 부기 '0.733(11/15)' = (잔존연수/내용연수) — 의견서 산출과정 표와 같은 값(11·15)
        수 량 ← 명세 count '1(식)' → 1            취득단가 ← **감정평가액과 같은 값**(업무팀 확정 2026-09-07; 재조달원가 85,000,000 아님)
        감정평가액 ← 명세 PRICE                     제작일자 ← '2022.08'(월까지) → 그 달 **1일** 2022-08-01(업무팀 확정 2026-09-07)
    """
    row, head = spec.row, spec.head
    machines = context.primary_site.machines
    machine = next((m for m in machines if m.mark and head.seq_no and m.mark == head.seq_no), None)         or (machines[0] if len(machines) == 1 else None)
    years = _YEARS.search(head.note_more or "") or _YEARS.search(row.note_more or "")
    qty_m = re.match(r"\s*(\d+)", head.qty or row.qty or "")
    made_m = re.match(r"\s*(\d{4})\s*[.\-/]\s*(\d{1,2})(?:\s*[.\-/]\s*(\d{1,2}))?", head.made or row.made or (machine.made if machine else "") or "")
    made = (f"{int(made_m.group(1)):04d}-{int(made_m.group(2)):02d}-{int(made_m.group(3) or 1):02d}"
            if made_m and 1 <= int(made_m.group(2)) <= 12 else None)
    return {
        "탭:기계기구명": (head.category or row.category or (machine.name if machine else None)),
        "탭:내용년수": years.group(2) if years else None,
        "탭:잔존년수": years.group(1) if years else None,
        "탭:제작일자": made,
        "탭:수 량": (qty_m.group(1) if qty_m else (re.sub(r"[^\d]", "", machine.qty) or None if machine and machine.qty else None)),
        "탭:취득단가": _money(row.amount),
        "탭:감정평가액": _money(row.amount),
        "탭:비 고": None,
    }


def _representative_first(specs: list[ObjectSpec], context: DocumentContext) -> list[ObjectSpec]:
    """명세표가 여러 장(land_list0·1…)이면 APW 대표지번 필지가 든 표의 물건을 앞에 둔다(2636 발송본: 708-2 묶음 → 708-3 묶음,
    명세표 순서는 708-3 이 먼저였음). 표 안 순서는 그대로."""
    jib = context.jibun
    if not jib or not jib.bun1:
        return specs
    rep = (jib.bun1.lstrip("0") or "0", (jib.bun2 or "").lstrip("0") or None)
    tables: list[str] = []
    for s in specs:
        if s.row.table not in tables:
            tables.append(s.row.table)
    if len(tables) < 2:
        return specs

    def has_rep(table: str) -> bool:
        for s in specs:
            if s.row.table == table and s.kind == OBJECT_LAND:
                main_no, sub_no = split_jibun(s.head.jibun)
                if main_no and ((main_no.lstrip("0") or "0"), ((sub_no or "").lstrip("0") or None)) == rep:
                    return True
        return False
    first = [t for t in tables if has_rep(t)]
    if not first or first[0] == tables[0]:
        return specs
    order = first + [t for t in tables if t not in first]
    return sorted(specs, key=lambda s: order.index(s.row.table))


def build_ibk(context: DocumentContext, costs=None) -> tuple[dict[str, str | None], list[dict]]:
    """기업 화면 — (헤더 필드, 물건 목록). 물건 dict = '물건:' 키 + '탭:' 키 + `_kind`(토지/건물/기계기구).

    costs: mapping.survey.SurveyCosts(APW_Bill) — 있으면 특별용역비(YONGYEUK)를 헤더에 넣는다.
    """
    fee = context.fee
    specs = _representative_first(split_objects(context.details), context)
    # 기계기구 물건은 항상 **맨 마지막**(업무팀 확정 2026-09-07). 명세표에서 기계 표가 앞에 와도 토지·건물 뒤로 보낸다(순서는 안정 정렬).
    specs = [s for s in specs if s.kind != OBJECT_MACHINE] + [s for s in specs if s.kind == OBJECT_MACHINE]
    header: dict[str, str | None] = {
        "평가사명": context.parties.appraiser(0),
        "헤더:물건종류": header_object_type(specs, context),
        "기준시점": context.price_point_date,
        "감정수수료": _money(fee.total),
        "순수수료": _money(fee.net),
        "실 비": _money(fee.expense_net),
        "특별용역비": _money(getattr(costs, "special", None)) or "0",   # 기업은 특별용역비가 없어도 항상 0 을 넣는다(사용자 지시 2026-09-01, 2636 발송본도 '0')
        "부가세": _money(fee.vat),
    }
    jibun = context.jibun
    common_amounts = {
        "물건:총감정평가액": _money(context.total_amount),
        "물건:토지평가금액": _money(_amount_sum(specs, OBJECT_LAND)),
        "물건:건물평가금액": _money(_amount_sum(specs, OBJECT_BUILDING)),
        "물건:기계기구평가금액": _money(_amount_sum(specs, OBJECT_MACHINE)),
        "물건:기타평가금액": None,
    }
    objects: list[dict] = []
    scans = _unit_scans_raw(context)
    condo_n = 0
    for spec in specs:
        main_no, sub_no = _parcel_jibun(spec, specs, context)
        category = spec.head.category if spec.kind == OBJECT_LAND else None
        # 다현장 문서(2818 옹정리+삼성동)는 물건마다 현장이 다르다 — 소재지·법정동코드·준공일자·용도지역을
        # 그 현장 것으로 쓴다. 현장이 하나뿐인 보통 문서는 늘 대표라 종전과 값이 같다.
        obj_address = _object_address(spec, context)
        site = context.site_for(spec.head.jibun or spec.row.jibun, obj_address)
        base = {
            "물건:법정동코드": ((jibun.legal_code if jibun else None) if context.is_primary_site(site)
                          else context.legal_code_for(obj_address)),
            "물건:소재지": obj_address,
            "물건:번지구분": jibun.jibun_kind if jibun else None,
            "물건:본번지": main_no,
            "물건:부번지": sub_no,
            **common_amounts,
        }
        if spec.row.table.lower().startswith("section_build"):
            condo_n += 1
            new = _condo_objects(spec, condo_n, scans, context, base, site)
        else:
            obj: dict = {
                "_kind": spec.kind, **base,
                "물건:물건종류": object_combo(spec.kind, category),
                # 부동산구분 콤보는 토지/건물/집합건물뿐(recon/combo_ibk.md) — 기계기구는 해당 항목이 없어 비운다(넣으면 거부만 남는다)
                "물건:부동산구분": spec.kind if spec.kind != OBJECT_MACHINE else None,
                "물건:등기소기준 고유번호": None,     # 실물 2704·2683 빈칸
            }
            if spec.kind == OBJECT_LAND:
                obj.update(_land_tab(spec, context, site))
            elif spec.kind == OBJECT_BUILDING:
                siblings = sum(1 for s in specs if s.kind == OBJECT_BUILDING and s.head is spec.head)
                obj.update(_building_tab(spec, context, split_floors=siblings >= 2, site=site))
            elif spec.kind == OBJECT_MACHINE:
                obj.update(_machine_tab(spec, context))
            new = [obj]
        for obj in new:
            obj["물건:일련번호"] = str(len(objects) + 1)
            objects.append(obj)
    return header, objects
