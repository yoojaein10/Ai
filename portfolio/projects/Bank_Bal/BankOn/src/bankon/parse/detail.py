"""`.gam` 명세표 파싱 — 물건별 행.

신한은 `mullist` 가 물건별 행을 주지만, 국민 등 나머지 은행은 명세표를 직접 읽어야
한다. 평가유형마다 테이블이 달라서(토지=land_list, 공동주택/건물=section_build,
기계=detail_machin …) 패밀리 정규식으로 모은다. GamJun `extractor` 에서 이식하고,
**계층 주소 조합**을 새로 넣었다.

⚠️ 실데이터상 모든 행의 `GUBUN` 이 'D' 라 그것으로는 명세행을 못 가른다.
   진짜 명세행은 `NO`/`JIBUN`/`PRICE` 중 하나가 채워진다.

⚠️ 소재지가 행마다 쪼개져 있는 표가 있다(실측 `land_list0` 142행):

       NO=1  ADDR='경기도'  JIBUN='299-2' …   ← 명세행
             ADDR='이천시'                    ← 주소 조각
             ADDR='마장면'                    ← 주소 조각
             ADDR='양촌리'                    ← 주소 조각

   명세행 뒤에 따라오는 '주소만 있는 행'을 이어 붙여 완전한 소재지를 만든다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation

# 명세 테이블 패밀리. 테이블명 = 패밀리 + 바인더번호(가변 자릿수).
# `_2` 계열(land_list_20 등)은 제목행 서식 테이블이라 정규식이 걸러낸다.
TABLE_FAMILIES: tuple[str, ...] = (
    "land_list", "mullist", "section_build",
    "detail_machin", "detail_ship", "detail_movables", "detail_ds",
    "detail_car", "pbs_land", "app_ship", "rent",
)
_TABLE_RE = re.compile(r"^(?:" + "|".join(TABLE_FAMILIES) + r")\d+$", re.IGNORECASE)

# 명세행 판별 신호 — 하나라도 채워지면 진짜 행.
ROW_SIGNALS: tuple[str, ...] = ("NO", "No", "JIBUN", "PRICE", "cPRICE", "Price", "price")

# 동일부호(상동) — 윗 명세행 값을 승계한다.
DITTO_MARKS = frozenset({'"', "〃", "″", "”", "“", "상동"})

TEXT_COLUMNS: dict[str, tuple[str, ...]] = {
    "seq_no": ("NO", "No", "SEQ", "SEQNO", "GIHO"),
    "mark": ("SNO", "GIHO"),
    "location": ("ADDR", "LOCATION", "CDESC"),
    "jibun": ("JIBUN",),
    "category": ("JIMOK", "Gimok_Go", "Gimok", "CATEGORY", "machine_detail",
                 "NAME", "CNAME", "A1", "ship_area1"),
    "zone": ("YONGDO", "YoungDo"),
    "struct": ("gujo", "STRUCT"),
    "note": ("BIGO", "NOTE"),
    "qty": ("count",),            # detail_machin: 수량 '1(식)'
    "made": ("make_date",),       # detail_machin: 제작일자 '2022.08'(둘째 행엔 제작자가 온다 — 머리행 값만 쓴다)
}
DECIMAL_COLUMNS: dict[str, tuple[str, ...]] = {
    "area_public": ("AREA1", "AREA"),
    "area_assessed": ("AREA2",),
    "unit_price": ("DANGA", "Gdan"),
    "amount": ("PRICE", "cPRICE", "Price", "price"),
}

# 토지 명세표의 '묶음괄호' 열 — 여는괄호('<')가 그룹 머리행 표시다. 머리행의
# AREA2(사정)/PRICE(평가액)는 그룹 합계라 물건 고유값이 아니다(매핑이 걸러 쓴다).
BRACKET_COLUMNS: tuple[str, ...] = ("AREA1LB", "AREA1RB")
OPEN_BRACKET = "<"
# 사정면적 쪽 묶음괄호 — 머리행 판정에는 안 쓰지만 조각 행 판정에서는 똑같이 '글자가 아닌 그림'으로 취급해야 한다.
_BRACKET_COLUMNS_2: tuple[str, ...] = ("AREA2LB", "AREA2RB")

# 주소 조각 행 판별: 소재지만 있고 다른 값이 없는 행.
_ADDRESS_ONLY_KEYS = ("ADDR", "LOCATION")

# `YONGDO` 열은 블록 종류에 따라 뜻이 다르다(토지=용도지역 / 건물=구조). 둘 다 세로로
# 줄바꿈돼 첫 조각만 잡히므로("제2종"·"철근"), **완성될 때까지** 이어붙인다(농협 이식 2026-09-07).
_ZONE_DONE = re.compile(r"(지역|구역|지구)")          # 용도지역: 제2종일반주거지역
_ZONE_PREFIX = re.compile(r"^[,\s]*제\s*\d+\s*종")   # 잘린 용도지역 머리: '제3종', ', 제3종'
_STRUCT_DONE = re.compile(r"조$")                    # 구조: 철근콘크리트조 / …구조
MAX_WRAP_LINES = 4                                   # 이어붙일 조각 수 상한(폭주 방지)

UNIT_LAND = "토지"
UNIT_BUILDING = "건물"


def _wrapped_done(text: str | None, unit_kind: str | None) -> bool:
    """이어붙인 값이 이미 온전한가 — 여기서 멈춰야 뒤따르는 지붕·층수가 안 붙는다."""
    if not text:
        return False
    cleaned = text.strip().rstrip(",")
    pattern = _STRUCT_DONE if unit_kind == UNIT_BUILDING else _ZONE_DONE
    return bool(pattern.search(cleaned))


def _should_wrap(current: str | None, fragment: str, unit_kind: str | None) -> bool:
    """이 조각을 직전 행 `zone` 에 이어붙일지 — **잘린 머리**일 때만.

    인계본(농협)은 온전해질 때까지 무조건 이었지만, 이 계통에선 건물 금액행의 `YONGDO` 가
    층 표시('1층'/'지하층', 기업 비고 출처)라 뒷줄 설명('층별 용도'…)이 줄줄이 붙었다(2683 회귀).
      토지: 머리가 '제N종' 처럼 잘려 있을 때(또는 비어 있고 조각이 …지역일 때)만
      건물: 머리가 구조 조각('철근')이고 조각이 '…조/…구조' 로 끝날 때만 — '층'·'지붕'으로 끝나는 머리는 안 잇는다
    """
    head = (current or "").strip().rstrip(",")
    piece = fragment.strip().rstrip(",")
    if unit_kind == UNIT_BUILDING:
        if not head or _STRUCT_DONE.search(head) or head.endswith(("층", "지붕")):
            return False
        return bool(_STRUCT_DONE.search(piece))
    if not head:
        return bool(_ZONE_DONE.search(piece))
    return bool(_ZONE_PREFIX.match(head)) and not _ZONE_DONE.search(head)


@dataclass(frozen=True)
class DetailRow:
    """명세표 한 행 = 물건 하나."""

    table: str
    seq_no: str | None = None
    mark: str | None = None
    location: str | None = None
    jibun: str | None = None
    category: str | None = None      # 지목 또는 품명
    zone: str | None = None          # 용도지역
    struct: str | None = None        # 구조(건물)
    note: str | None = None
    qty: str | None = None            # 기계 수량(detail_machin count)
    made: str | None = None           # 기계 제작일자(detail_machin make_date)
    note_more: str | None = None      # 명세행 뒤 부기 행들의 비고를 이어 붙인 것(기계 '0.733(11/15)' = 잔존/내용년수, 2776)
    area_public: Decimal | None = None
    area_assessed: Decimal | None = None
    unit_price: Decimal | None = None
    amount: Decimal | None = None
    group_head: bool = False          # 묶음괄호 머리행(AREA2/PRICE=그룹 합계)
    group_member: bool = False        # 묶음괄호 안 후속행('|'/'>') — 일단지 구성 필지(2706 1124-1) 등
    excluded: bool = False            # PRICE 칸이 '감정평가외' 같은 글자 = 평가 제외 필지(도로 등, 2636 708-4)
    unit_kind: str | None = None      # 이 행이 속한 명세 블록 — UNIT_LAND | UNIT_BUILDING (land_list 의 건물 유닛 판별, 농협)

    @property
    def is_land(self) -> bool:
        return self.table.lower().startswith(("land_list", "pbs_land"))

    @property
    def is_building(self) -> bool:
        """구분건물 명세표(section_build)인가. 일반 건물은 land_list 에 온다."""
        return self.table.lower().startswith("section_build")

    @property
    def kind(self) -> str | None:
        """물건 실제 종류 — 블록 머리(`unit_kind`) 우선, 없으면 테이블로 추정.

        `land_list`(토지 명세표)에 건물 유닛이 섞여 있으므로 테이블만으론 못 가른다
        (실측 2452: land_list 뿐인 단독주택 문서 — is_land=True 지만 kind='건물').
        """
        if self.unit_kind:
            return self.unit_kind
        if self.is_building:
            return UNIT_BUILDING
        return UNIT_LAND if self.is_land else None


def _clean(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _pick(row: dict, columns: tuple[str, ...]) -> str | None:
    for column in columns:
        value = _clean(row.get(column))
        if value is not None:
            return value
    return None


def _decimal(row: dict, columns: tuple[str, ...]) -> Decimal | None:
    text = _pick(row, columns)
    if text is None:
        return None
    try:
        return Decimal(text.replace(",", ""))
    except InvalidOperation:
        return None


def _resolve_ditto(value: str | None, previous: str | None) -> str | None:
    """동일부호(`"`, `상동`)면 직전 명세행 값을 승계한다."""
    return previous if value is not None and value in DITTO_MARKS else value


def is_detail_row(row: dict) -> bool:
    return any(_clean(row.get(signal)) is not None for signal in ROW_SIGNALS)


def _is_text_price_subrow(row: dict) -> bool:
    """NO·지번 없이 PRICE 칸이 글자('감정평가외')뿐인 부속행(법면 부분·도로저촉 등) — 물건이 아니라 직전 물건의 부기.
    2636 실물: 이 행의 ADDR 이 줄바꿈된 주소 조각('만세구')이라 새 명세행으로 오인하면 소재지가 끊긴다."""
    if _pick(row, TEXT_COLUMNS["seq_no"]) or _clean(row.get("JIBUN")):
        return False
    return _pick(row, DECIMAL_COLUMNS["amount"]) is not None and _decimal(row, DECIMAL_COLUMNS["amount"]) is None


def is_address_fragment(row: dict) -> bool:
    """소재지 조각 행 — 명세행이 아니면서 주소 칸이 채워진 행. 괄호표시('|')·비고·면적 부기가 같이 있어도 조각이다
    (2636 실물: '화성시' 행에 AREA2LB='|', '만세구' 행에 감정평가외 부기가 붙어 있었음)."""
    if is_detail_row(row) and not _is_text_price_subrow(row):
        return False
    return _pick(row, _ADDRESS_ONLY_KEYS) is not None


def _build(table: str, row: dict, previous: dict[str, str | None]) -> tuple[DetailRow, dict]:
    texts = {name: _pick(row, cols) for name, cols in TEXT_COLUMNS.items()}
    texts = {name: _resolve_ditto(value, previous.get(name)) for name, value in texts.items()}
    numbers = {name: _decimal(row, cols) for name, cols in DECIMAL_COLUMNS.items()}
    bracket = _pick(row, BRACKET_COLUMNS)
    group_head = bracket == OPEN_BRACKET
    excluded = _pick(row, DECIMAL_COLUMNS["amount"]) is not None and numbers["amount"] is None
    return DetailRow(table=table, group_head=group_head, group_member=bracket in ("|", ">"), excluded=excluded,
                     **texts, **numbers), texts


_UNIT_ORDINAL = re.compile(r"^[가-힣]$")               # 구분건물 유닛머리(가/나/다…)
_NUMERIC_NO = re.compile(r"^\d+$")

# 유닛 머리 규칙이 성립하는 명세표 — 토지 명세표는 필지를 숫자로, 그 위 건물을
# 한글 한 글자로 번호매긴다. `mullist`(신한 물건행) 등 다른 표는 관례가 달라 제외한다.
_UNIT_TABLES = ("land_list", "pbs_land")


def _unit_kind_of(seq_no: str | None) -> str | None:
    """명세 블록 머리 번호 → 그 블록이 토지인지 건물인지.

    토지 명세표(`land_list`)는 **필지를 숫자(1,2,3)**, 그 지상 **건물을 한글 한 글자
    (가,나,다)** 로 번호매긴다. 건물 유닛 블록에서는 열의 뜻까지 바뀐다 —
    `JIMOK` 은 지목이 아니라 **건물 용도**, `YONGDO` 는 용도지역이 아니라 **건물 구조**다.
    (실측 2516: NO=1·2 필지 + NO=가~라 건물 / 2452: NO=가 뿐 — land_list 인데 토지가 없는 문서)
    """
    if not seq_no:
        return None
    text = seq_no.strip()
    if _NUMERIC_NO.match(text):
        return UNIT_LAND
    if _UNIT_ORDINAL.match(text):
        return UNIT_BUILDING
    return None
_FLOOR_HO_MARK = re.compile(
    r"제\s*\d+\s*층\s*제\s*[0-9A-Za-z가-힣][0-9A-Za-z가-힣\-]*\s*호")   # 제2층 제3-207호


def _is_struct_line(gujo: str | None, area1: str | None, price: str | None) -> bool:
    """`gujo` 칸이 온전한 '구조'(철근콘크리트구조 등)인 물리행인지.

    section_build 은 한 물건을 여러 물리행에 세로로 줄바꿈해 넣는다. 구조는 유닛머리
    행의 gujo 에만 온다 — 층별면적행(gujo=층명+AREA1)·'(내)' 부기·'제N층 제N호'
    가격행은 구조가 아니다.
    """
    if not gujo or area1 or price:
        return False
    if gujo.startswith("("):
        return False
    if _FLOOR_HO_MARK.search(gujo):
        return False
    # 국민 구분건물 표제부는 같은 `gujo` 칸에 **용도지역**도 적어 둔다(실측 0541
    # '일반주거지역' → '철근콘크리트구조' 두 줄). 구조가 아니므로 건너뛴다 —
    # 안 걸러내면 조각 잇기가 '일반주거지역철근콘크리트구조' 를 만든다.
    if _ZONE_DONE.search(gujo) or _ZONE_PREFIX.match(gujo):
        return False
    return True


def _header_jibun(raw_rows: list) -> str | None:
    """표제부(첫 NO행 이전)의 첫 '숫자로 시작하는 지번' — 물건 공통 지번."""
    for raw in raw_rows or ():
        if not isinstance(raw, dict):
            continue
        if _pick(raw, TEXT_COLUMNS["seq_no"]):
            return None                        # 첫 NO행 = 표제부 끝
        jibun = _clean(raw.get("JIBUN"))
        if jibun and re.match(r"^\s*산?\s*\d", jibun):
            return jibun
    return None


_GROUP_TAIL = ("|", ">")


def _area1_group_total(raw_rows: list, index: int) -> Decimal | None:
    """층별로 나뉜 **공부면적(AREA1) 묶음괄호의 합**. 묶음이 아니면 None.

    명세표는 한 물건의 공부면적을 층마다 한 행씩 적고 AREA1 괄호(`<` `|` `>`)로 묶는다.
    머리행의 AREA1 만 쓰면 **첫 층 면적만** 들어간다.
      · 구분건물(section_build) 실측 2874 새마을 203호: 1층 77.75 · 2층 77.75 · 지하층 77.75 ·
        지하층 차고 17.78 = 251.03 = 사정면적. 화면엔 77.75 만 갔다.
      · 토지 명세표(land_list)의 건물 유닛 실측 2871 하나 단가 756,000 행: 2~9층
        98.82×5 + 84.24 + 69.66 + 32.34 = 680.34 = 사정면적. 화면엔 98.82.
    괄호 밖 행(대지권 면적 196.88 등)은 더하지 않는다 — 괄호가 끝나면(`>`) 멈춘다.

    ★묶음 안에 **제 몫의 명세행**(NO·지번·금액을 가진 행)이 있으면 층 묶음이 아니라
    **물건 묶음**(land_list 일단지 — 머리 AREA2 가 필지들의 합계)이라 합치지 않는다.
    괄호가 깨져 있으면(닫힘 없음) None 을 돌려 종전 값(머리행 AREA1)을 쓰게 한다(fail-closed).

    ★그리고 **합이 머리행 사정면적(AREA2)과 정확히 같을 때만** 쓴다. 괄호가 층 묶음이 아닌
    경우가 실제로 있어서(전례 624건 스캔) 합만 믿으면 틀린 값이 들어간다:
      · '2층~5층 **각** 298.32'(0680) — 층마다라는 뜻이라 단순 합(570.04)이 아니다(사정 1,465).
      · 기존/증축을 사정 두 줄로 나눈 표(1463·0981·1119) — 공부 괄호는 건물 전체라 단가 줄과 안 맞는다.
      · 멸실·철거·감정평가외 층이 섞인 표(1029·2482·0780) — 사정이 공부합보다 작다.
      · 지분 표기('98x-----', 0801) — 숫자가 면적이 아니다.
    같을 때만 쓰면 그 값은 곧 사정면적이라 틀릴 수가 없고, 애매한 표는 종전대로 담당자가 본다.
    """
    rows = [r for r in (raw_rows or ())]
    if not (0 <= index < len(rows)) or not isinstance(rows[index], dict):
        return None
    start = index
    if _pick(rows[index], BRACKET_COLUMNS) != OPEN_BRACKET:
        if _pick(rows[index], BRACKET_COLUMNS) not in _GROUP_TAIL:
            return None                                   # 묶음 아님 — 층이 하나
        while start >= 0 and _pick(rows[start], BRACKET_COLUMNS) != OPEN_BRACKET:
            start -= 1
        if start < 0:
            return None                                   # 여는 괄호가 없다
    total: Decimal | None = None
    for raw in rows[start:]:
        if not isinstance(raw, dict):
            return None
        mark = _pick(raw, BRACKET_COLUMNS)
        if raw is not rows[start] and mark not in _GROUP_TAIL:
            return None                                   # 닫히지 않은 묶음
        if raw is not rows[start] and is_detail_row(raw) and not _is_text_price_subrow(raw):
            return None     # 묶음 안에 제 몫의 명세행이 또 있다 = 물건 묶음(일단지)이라 합치지 않는다
        area = _decimal(raw, DECIMAL_COLUMNS["area_public"])
        if area is not None:
            total = area if total is None else total + area
        if mark == ">":
            assessed = _decimal(rows[start], DECIMAL_COLUMNS["area_assessed"])
            return total if (total is not None and total == assessed) else None
    return None


def _section_build_objects(table: str, raw_rows: list) -> list[DetailRow]:
    """구분건물 명세표(section_build)를 물건별 행으로 병합.

    물건 경계 = PRICE(비준가액) 채워진 물리행(유닛당 정확히 1행). NO 칸: 숫자(1,2)=
    토지행(경계 리셋), 한글1자(가/나…)=구분건물 유닛머리(순번). 유닛머리~PRICE행 사이의
    세로 조각을 PRICE행 기준으로 역병합해 물건 하나(구조·면적·금액·층/호)를 만든다.
    표제부(첫 NO행 이전 세로 줄바꿈 블록)는 물건이 아니라 공통 헤더라 버린다.
    """
    header_jibun = _header_jibun(raw_rows)
    objects: list[DetailRow] = []
    current_no: str | None = None
    struct_head: str | None = None
    for index, raw in enumerate(raw_rows or ()):
        if not isinstance(raw, dict):
            continue
        no = _pick(raw, TEXT_COLUMNS["seq_no"])
        gujo = _clean(raw.get("gujo") or raw.get("STRUCT"))
        area1 = _clean(raw.get("AREA1"))
        price = _pick(raw, DECIMAL_COLUMNS["amount"])
        if no and not _UNIT_ORDINAL.match(no):
            current_no = struct_head = None            # 토지행 = 경계 리셋
            continue
        if no and _UNIT_ORDINAL.match(no):
            current_no = no
        if _is_struct_line(gujo, area1, price):
            # 구조도 세로로 잘린다 — '철근' + '콘크리트구조'(실측 2665 표제부). 온전해질
            # 때까지만 잇고 완성되면 멈춘다(뒤의 '(철근)콘크리트지붕'·'24층' 이 안 붙게).
            if struct_head is None:
                struct_head = gujo
            elif not _STRUCT_DONE.search(struct_head):
                struct_head += gujo
        if price is not None:                          # 물건 확정
            # 공부면적은 층마다 한 행씩 나뉘어 괄호로 묶여 있을 수 있다 → 묶음이면 합(2874).
            floors = _area1_group_total(raw_rows, index)
            objects.append(DetailRow(
                table=table, seq_no=current_no,
                location=(gujo if gujo and _FLOOR_HO_MARK.search(gujo) else None),
                jibun=header_jibun, struct=struct_head,
                area_public=(floors if floors is not None
                             else _decimal(raw, DECIMAL_COLUMNS["area_public"])),
                area_assessed=_decimal(raw, DECIMAL_COLUMNS["area_assessed"]),
                amount=_decimal(raw, DECIMAL_COLUMNS["amount"]),
                note=_clean(raw.get("BIGO")), group_head=False,
                unit_kind=UNIT_BUILDING))
            struct_head = None
    return objects


def is_rollup_only(rows: tuple[DetailRow, ...]) -> bool:
    """명세행이 '금액만 있는 총액행' 뿐 — 개별 물건 식별자(순번·지번·소재지·면적)가
    어느 행에도 없다(집계형 .gam, round0_memo='집계명세표…'). 개별 물건은 별도
    자식문서에만 있어 .gam 으로 복구 불가 → 매핑이 총액을 물건값으로 오기입하지 않게 한다.
    """
    if not rows:
        return False

    def _is_item(r: DetailRow) -> bool:
        return any((r.seq_no, r.jibun, r.location, r.area_public, r.area_assessed))

    return not any(_is_item(r) for r in rows)


def parse(tables: dict[str, list]) -> tuple[DetailRow, ...]:
    """명세 테이블에서 물건 행을 뽑는다(주소 조각은 직전 행에 이어 붙인다)."""
    rows: list[DetailRow] = []
    for table, raw_rows in tables.items():
        if not _TABLE_RE.match(table):
            continue
        if table.lower().startswith("section_build"):
            # 구분건물 명세표는 물리행이 세로로 조각나 별도 병합한다.
            rows.extend(_section_build_objects(table, raw_rows or []))
            continue
        previous: dict[str, str | None] = {}   # 동일부호 승계는 테이블 안에서만
        # 블록 머리(NO)가 바뀔 때까지 같은 유닛에 속한다 — 금액행은 머리 아래
        # 몇 행 뒤에 NO 없이 오므로, 머리에서 종류를 물려받아야 토지/건물을 가른다.
        unit_kind: str | None = None
        tracks_units = table.lower().startswith(_UNIT_TABLES)
        wrapped = 0                            # 직전 행에 이어붙인 줄바꿈 조각 수
        for index, raw in enumerate(raw_rows or ()):
            if not isinstance(raw, dict):
                continue
            if is_detail_row(raw) and not _is_text_price_subrow(raw):
                record, previous = _build(table, raw, previous)
                # 공부면적이 층마다 한 행씩 나뉘어 괄호로 묶여 있으면 합친다(2871 하나 2~9층).
                floors = _area1_group_total(raw_rows, index)
                if floors is not None and floors != record.area_public:
                    record = replace(record, area_public=floors)
                if tracks_units:
                    unit_kind = _unit_kind_of(record.seq_no) or unit_kind
                    record = replace(record, unit_kind=unit_kind)
                rows.append(record)
                wrapped = 0
                continue
            if not (rows and rows[-1].table == table):
                continue
            # 부기 행의 비고는 직전 명세행에 모아 둔다(기계기구 명세: 둘째 행 BIGO '0.733(11/15)' → 잔존/내용년수, 2776 실측 2026-09-07).
            more = _clean(raw.get("BIGO"))
            if more and not is_detail_row(raw):
                rows[-1] = replace(rows[-1], note_more=" ".join(x for x in (rows[-1].note_more, more) if x))
            # 명세행 뒤에 붙는 주소 조각(부속행 포함) — 직전 행 소재지에 이어 붙인다.
            if is_address_fragment(raw):
                fragment = _pick(raw, _ADDRESS_ONLY_KEYS)
                joined = " ".join(x for x in (rows[-1].location, fragment) if x)
                rows[-1] = replace(rows[-1], location=joined or None)
                # 같은 물리행에 주소 조각과 용도지역 조각이 함께 올 수 있다(실측 2546) — 아래 잇기도 계속한다.
            # 세로로 줄바꿈된 용도지역·구조 조각 — 온전해질 때까지 직전 행에 이어 붙인다.
            #   실측 2546: '제2종' + '일반주거지역,'        → 제2종일반주거지역
            #   실측 2546 건물유닛: '철근' + '콘크리트조'     → 철근콘크리트조(뒤의 슬래브지붕·3층은 안 붙음)
            if not tracks_units or wrapped >= MAX_WRAP_LINES:
                continue
            fragment = _pick(raw, TEXT_COLUMNS["zone"])
            if fragment and _should_wrap(rows[-1].zone, fragment, rows[-1].unit_kind):
                rows[-1] = replace(rows[-1], zone=(rows[-1].zone or "") + fragment)
                wrapped += 1
    return tuple(rows)


def excluded_parts(tables: dict[str, list]) -> tuple[DetailRow, ...]:
    """번호 없는 **'감정평가외' 면적행** — 건물의 평가 제외 부분(옥탑·연면적제외 층).

    하나 화면은 이걸 물건 한 행으로 넣는다(2871 실측 2026-09-16: 옥탑 12.25 →
    평가단가 1 · 감정평가액 0 · 면적 12.25, 나머지 건물 정보는 본 건물과 같다).

    `parse()` 는 이 행들을 물건으로 세지 않는다 — 번호도 지번도 없어 직전 물건의 부기로 취급해야
    하는 것들(토지 '도로후퇴부분'·'법면')과 한 줄 차이라서다. 가르는 기준은 **공부·사정 면적이
    둘 다 있는가**다(전례 624건: 토지 부기는 공부가 비어 있고 주소 조각이 붙어 있다).
    details 에 섞지 않고 따로 돌려주므로 다른 은행 매핑은 종전 그대로다.
    """
    found: list[DetailRow] = []
    for table, raw_rows in tables.items():
        if not _TABLE_RE.match(table):
            continue
        for raw in raw_rows or ():
            if not isinstance(raw, dict) or not _is_text_price_subrow(raw):
                continue
            public = _decimal(raw, DECIMAL_COLUMNS["area_public"])
            assessed = _decimal(raw, DECIMAL_COLUMNS["area_assessed"])
            if public is None or assessed is None:
                continue                      # 토지 부기(도로후퇴·법면 등) — 종전대로 물건이 아니다
            found.append(DetailRow(
                table=table, area_public=public, area_assessed=assessed,
                struct=_clean(raw.get("gujo")), zone=_pick(raw, TEXT_COLUMNS["zone"]),
                note=_clean(raw.get("BIGO")), excluded=True, unit_kind=UNIT_BUILDING))
    return tuple(found)


def for_sequence(rows: tuple[DetailRow, ...], seq_no: str | None) -> DetailRow | None:
    """물건순번으로 행 하나를 고른다. 순번이 없으면 첫 행.

    다물건(금액 있는 물건이 2개 이상)에서 화면 일련번호(숫자)가 오면 그 순서의 물건을
    고른다 — 명세표 NO('가'/'나')와 화면 순번(1/2)이 다르기 때문. 그 외에는 기존
    동작(seq_no 문자열 매칭, 없으면 첫 행) 그대로라 단일물건은 무회귀.
    """
    if not rows:
        return None
    if seq_no and seq_no.strip().isdigit():
        anchors = tuple(r for r in rows if r.amount is not None)
        if len(anchors) >= 2:                          # 다물건: 금액앵커가 물건경계
            idx = int(seq_no) - 1
            if 0 <= idx < len(anchors):
                return anchors[idx]
    if seq_no is None:
        return rows[0]
    for row in rows:
        if row.seq_no == seq_no:
            return row
    return rows[0]


# ── 명세표 부가정보(의견서 없는 '감정평가회보' 건용 폴백, 2026-09-14) ─────────────────────────
# 신한 대지권면적·총층수는 의견서 개요(호별 표·'지하N층/지상N층')에서 읽는데, 회보 형식 .gam(로컬 619건 중 36건)
# 은 의견서(HWP)가 아예 없어 전부 None 이 됐다(2819 실화면: 담당자가 명세표 값으로 손수 채움).
# 같은 값이 section_build 표제부·호별 블록에 있다 — 층별면적 행 '20층'·'지1층', 호별 '소유권대지권' 행의 AREA2.
_FLOOR_GROUND_RE = re.compile(r"(?<![제지하\d])(\d+)\s*층")     # '20층', '2층 ~ 19층 각' → 20, 2, 19 (제N층·지N층 제외)
_FLOOR_BASEMENT_RE = re.compile(r"(?<!제)지하?\s*(\d+)\s*층")   # '지1층'·'지하 2층' → 1, 2 ('제지1층' 호 표기 제외)
_LAND_RIGHT_MARK = "대지권"


@dataclass(frozen=True)
class SpecExtras:
    """section_build 표에서 뽑은 건물 층수와 호별 대지권면적(기호 → ㎡). 없으면 None/빈 dict."""

    ground_floors: int | None = None
    basement_floors: int | None = None
    land_rights: dict | None = None            # __post_init__ 에서 dict 로 고정

    def __post_init__(self):
        if self.land_rights is None:
            object.__setattr__(self, "land_rights", {})

    def land_right_for(self, mark: str | None) -> Decimal | None:
        return self.land_rights.get((mark or "").strip()) if mark else None


def spec_extras(tables: dict[str, list]) -> SpecExtras:
    """section_build 표 전부를 훑어 층수(최대값)·호별 대지권면적을 모은다. 표가 없으면 빈 값."""
    ground: int | None = None
    basement: int | None = None
    rights: dict[str, Decimal] = {}
    for name, raw_rows in (tables or {}).items():
        if not _TABLE_RE.match(str(name)) or not str(name).lower().startswith("section_build"):
            continue
        current: str | None = None
        for raw in raw_rows or ():
            if not isinstance(raw, dict):
                continue
            no = _pick(raw, TEXT_COLUMNS["seq_no"])
            if no and _UNIT_ORDINAL.match(no):
                current = no
            elif no:
                current = None                                     # 토지행 = 유닛 밖
            gujo = _clean(raw.get("gujo") or raw.get("STRUCT")) or ""
            if gujo.startswith("제"):                              # '제지1층 제비01호' = 호 표기, 층수 아님
                pass
            else:
                for m in _FLOOR_GROUND_RE.finditer(gujo):
                    ground = max(ground or 0, int(m.group(1)))
                for m in _FLOOR_BASEMENT_RE.finditer(gujo):
                    basement = max(basement or 0, int(m.group(1)))
            if current and _LAND_RIGHT_MARK in gujo and current not in rights:
                value = _decimal(raw, DECIMAL_COLUMNS["area_assessed"]) or _decimal(raw, DECIMAL_COLUMNS["area_public"])
                if value is not None:
                    rights[current] = value
    return SpecExtras(ground_floors=ground, basement_floors=basement, land_rights=rights)
