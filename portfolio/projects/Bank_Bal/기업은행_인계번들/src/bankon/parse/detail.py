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
# 사정면적 쪽 묶음괄호 — 머리행 판정에는 안 쓰지만(실측상 AREA1 쪽이 머리 신호),
# 조각 행 판정에서는 똑같이 '글자가 아닌 그림'으로 취급해야 한다.
_BRACKET_COLUMNS_2: tuple[str, ...] = ("AREA2LB", "AREA2RB")
OPEN_BRACKET = "<"

# 주소 조각 행 판별: 소재지만 있고 다른 값이 없는 행.
_ADDRESS_ONLY_KEYS = ("ADDR", "LOCATION")


UNIT_LAND = "토지"
UNIT_BUILDING = "건물"


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
    area_public: Decimal | None = None
    area_assessed: Decimal | None = None
    unit_price: Decimal | None = None
    amount: Decimal | None = None
    group_head: bool = False          # 묶음괄호 머리행(AREA2/PRICE=그룹 합계)
    unit_kind: str | None = None      # 이 행이 속한 명세 블록 — UNIT_LAND | UNIT_BUILDING

    @property
    def is_land(self) -> bool:
        """명세 **테이블**이 토지계인가(land_list/pbs_land).

        ⚠️ 테이블 판정이라 `land_list` 에 실린 **제시외·일반 건물 행도 True** 다.
        물건이 실제로 토지인지 건물인지는 `unit_kind` 를 봐야 한다(실측 2452:
        land_list 뿐인 단독주택 문서 — is_land=True 지만 unit_kind='건물').
        """
        return self.table.lower().startswith(("land_list", "pbs_land"))

    @property
    def is_building(self) -> bool:
        """구분건물 명세표(section_build)인가. 일반 건물은 land_list 에 온다."""
        return self.table.lower().startswith("section_build")

    @property
    def kind(self) -> str | None:
        """물건 실제 종류 — 블록 머리(`unit_kind`) 우선, 없으면 테이블로 추정.

        `land_list`(토지 명세표)에 건물 유닛이 섞여 있으므로 테이블만으론 못 가른다.
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


def is_address_fragment(row: dict) -> bool:
    """소재지 조각 행 — 주소만 있고 나머지가 비어 있다.

    묶음괄호 열(`AREA1LB`/`AREA2LB` …)은 값이 아니라 표를 세로로 잇는 **그림 글자**
    (`<` `|` `>`)라 조각 판정에서 뺀다. 안 그러면 괄호가 지나가는 줄의 주소 조각이
    통째로 버려져 계층 주소가 끊긴다(실측 2516: `인천광역시 강화군 길상면 선두리` 가
    `인천광역시` 에서 끊겼다 — 괄호 세로줄 `|` 이 같은 행에 있었기 때문).
    """
    if is_detail_row(row):
        return False
    if _pick(row, _ADDRESS_ONLY_KEYS) is None:
        return False
    ignored = {"ATTR", "GUBUN", *_ADDRESS_ONLY_KEYS, *BRACKET_COLUMNS, *_BRACKET_COLUMNS_2}
    return not any(
        _clean(value) for key, value in row.items() if key not in ignored
    )


def _build(table: str, row: dict, previous: dict[str, str | None]) -> tuple[DetailRow, dict]:
    texts = {name: _pick(row, cols) for name, cols in TEXT_COLUMNS.items()}
    texts = {name: _resolve_ditto(value, previous.get(name)) for name, value in texts.items()}
    numbers = {name: _decimal(row, cols) for name, cols in DECIMAL_COLUMNS.items()}
    group_head = _pick(row, BRACKET_COLUMNS) == OPEN_BRACKET
    return DetailRow(table=table, group_head=group_head, **texts, **numbers), texts


_UNIT_ORDINAL = re.compile(r"^[가-힣]$")               # 구분건물 유닛머리(가/나/다…)
_NUMERIC_NO = re.compile(r"^\d+$")

# 유닛 머리 규칙이 성립하는 명세표 — 토지 명세표는 필지를 숫자로, 그 위 건물을
# 한글 한 글자로 번호매긴다. `mullist`(신한 물건행) 등 다른 표는 관례가 달라 제외한다.
_UNIT_TABLES = ("land_list", "pbs_land")


def _unit_kind_of(seq_no: str | None) -> str | None:
    """명세 블록 머리 번호 → 그 블록이 토지인지 건물인지.

    토지 명세표(`land_list`)는 **필지를 숫자(1,2,3)**, 그 지상 **건물을 한글 한 글자
    (가,나,다)** 로 번호매긴다. 건물 유닛 블록에서는 열의 뜻까지 바뀐다 —
    `JIMOK` 은 지목이 아니라 **건물 용도**(제2종근린생활시설), `YONGDO` 는 용도지역이
    아니라 **건물 구조**(일반철골구조/기타지붕/단층) 다.

        실측 2516: NO=1·2(대) 필지 + NO=가·나·다·라(제2종근린생활시설) 건물
        실측 2531: NO=1·2(공장용지) + NO=가(공장, 철골조)
        실측 2452: NO=가 뿐(단독주택) — land_list 인데 토지가 없는 문서
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
    for raw in raw_rows or ():
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
                struct_head = gujo
        if price is not None:                          # 물건 확정
            objects.append(DetailRow(
                table=table, seq_no=current_no,
                location=(gujo if gujo and _FLOOR_HO_MARK.search(gujo) else None),
                jibun=header_jibun, struct=struct_head,
                area_public=_decimal(raw, DECIMAL_COLUMNS["area_public"]),
                area_assessed=_decimal(raw, DECIMAL_COLUMNS["area_assessed"]),
                amount=_decimal(raw, DECIMAL_COLUMNS["amount"]),
                note=_clean(raw.get("BIGO")), group_head=False,
                unit_kind=UNIT_BUILDING))
            struct_head = None
            continue
        if struct_head is None and _is_struct_line(gujo, area1, price):
            struct_head = gujo
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
        for raw in raw_rows or ():
            if not isinstance(raw, dict):
                continue
            if is_detail_row(raw):
                record, previous = _build(table, raw, previous)
                if tracks_units:
                    unit_kind = _unit_kind_of(record.seq_no) or unit_kind
                    record = replace(record, unit_kind=unit_kind)
                rows.append(record)
                continue
            # 명세행 뒤에 붙는 주소 조각 — 직전 행 소재지에 이어 붙인다.
            if rows and rows[-1].table == table and is_address_fragment(raw):
                fragment = _pick(raw, _ADDRESS_ONLY_KEYS)
                joined = " ".join(x for x in (rows[-1].location, fragment) if x)
                rows[-1] = replace(rows[-1], location=joined or None)
    return tuple(rows)


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
