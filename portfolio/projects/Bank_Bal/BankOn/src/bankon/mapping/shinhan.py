"""신한은행 담보(`TBNKSHG24DAMB`) 필드 매핑.

화면 항목명은 `recon/fields_shinhan_damb.md`, 콤보 선택지는 `recon/combo_shinhan.md`
에서 실제 화면을 읽어 수집한 것이다. 화면이 바뀌면 이 파일만 고친다.

물건 1건 = 화면의 `물건순번` 1개. mullist 행 하나가 물건 하나에 대응한다.
mullist 가 없으면(신한 건의 32%) 담보종류·담보용도를 비워둔다 — 사용자 결정.
"""
from __future__ import annotations

import re
from decimal import ROUND_DOWN, Decimal

from ..codes import shinhan as codes
from ..model import DocumentContext
from ..parse.characteristics import LEASE_SELF_USE, LEASE_UNKNOWN
from ..parse.cost import representative
from ..parse import units
from ..parse.mullist import MullistRow

# 표가 없을 때 쓰는 기본값(사용자 확정).
DEFAULT_CHARACTERISTIC = "아니오"
DEFAULT_LEASE = LEASE_SELF_USE   # 임대 콤보엔 '해당없음' 항목이 없다(임대있음/임대없음(공실)/임대없음(자가사용및자가사용예정)).
                                 # 의견서에 임대 정보가 없으면 자가사용으로(2737 발송본 대조·사용자 확정 2026-09-07). 종전 '해당없음'(2026-08-25)
CHECKLIST_ANSWER = "1"          # 신한 점검항목 13개는 전부 1(=예)

# 점검항목은 라벨이 길고 화면마다 문구가 조금씩 달라 라벨로 못 찾는다.
# 드라이버가 `TcxComboBox`(비 DB 바인딩) 컨트롤을 순서대로 채우게 한다.
CHECKLIST_CONTROL_CLASS = "TcxComboBox"

# 은행 폼이 기본값을 미리 넣어두는 칸 — 문서(의견서 OLE) 값으로 항상 덮어쓴다(업무팀 대조 2026-08-26).
# 물건특성 8칸은 은행 기본 '아니오'/'해당없음' 이 남아 발송된 사고, 소재지는 의뢰 원문이 남는 문제.
ALWAYS_OVERWRITE = frozenset({
    "매매/분양", "임대", "튼상가", "오픈상가", "공부/현황 불일치", "제시외건물,종물/부합물",
    "미등기 부동산", "별도 등기 존재", "소재지",
})

_CHARACTERISTIC_FIELDS = (
    ("매매/분양", "sale"),
    ("튼상가", "open_wall_shop"),
    ("오픈상가", "open_shop"),
    ("공부/현황 불일치", "mismatch"),
    ("제시외건물,종물/부합물", "extra_building"),
    ("미등기 부동산", "unregistered"),
    ("별도 등기 존재", "separate_registry"),
)


MACHINE_KIND = "기계기구"
MACHINE_USE = "기타부동산(단독시설)"


def _money(value: Decimal | None) -> str | None:
    """화면은 콤마를 자동으로 붙이므로 숫자만 넣는다."""
    if value is None:
        return None
    return format(value.quantize(Decimal(1)) if value == value.to_integral() else value, "f")


def _unit_price(row: MullistRow) -> str | None:
    """평가단가 = 감정평가액 ÷ 사정면적 (토지 물건).

    비용층 대표단가(cost.unit_price)는 문서 하나에 하나뿐이라 다물건 건에서
    물건별 단가를 못 집는다. 화면 규칙은 물건별 `감정평가액 ÷ 사정면적` 이고
    실측상 정확히 정수로 떨어진다. 건물(집합상가 등)은 화면상 0/공란이라 비운다.
    """
    # 구분건물(집합건물 호실)은 0(업무팀 확정 2026-08-26, 2695 사용자 재확인 2026-08-27, form.ZERO_ALLOWED 로 0가드 예외).
    # 토지건물의 건물 행은 감정평가액 ÷ 사정면적(사용자 정정 2026-08-27, 2673: 602,234,010/724.71 → 831,000). 기계기구는 비움.
    if row.is_building and row.is_unit_building:
        return "0"
    if not (row.is_land or row.is_building) or not row.amount or not row.area_assessed:
        return None
    try:
        return format((row.amount / row.area_assessed).quantize(Decimal(1)), "f")
    except (ArithmeticError, ValueError):
        return None


def _area(value: Decimal | None) -> str | None:
    """면적은 소수 2자리 고정 + **버림**이다(실측: 11.717 → 11.71, 54.6 → 54.60)."""
    if value is None:
        return None
    return format(value.quantize(Decimal("0.01"), rounding=ROUND_DOWN), "f")


def _digits(value: str | None) -> str | None:
    """등기번호는 화면에 하이픈 없이 숫자만 들어간다."""
    if not value:
        return None
    return re.sub(r"\D", "", value) or None


_FLOOR_RE = re.compile(r"제\s*(지하?)?\s*(\d+)\s*층")


def _floor_no(address: str | None) -> str | None:
    """소재지의 `제9층` 에서 해당층수를 뽑는다(mullist 에는 층 정보가 없다).

    지하는 음수 — `제지1층 제비01호` → `-1`(2819 담당자 완성본 실측 2026-09-14, 국민 2788 규칙과 같다).
    종전 정규식은 '제' 바로 뒤 숫자만 받아 지하층을 None 으로 비웠다.
    """
    if not address:
        return None
    match = _FLOOR_RE.search(address)
    if not match:
        return None
    return f"-{match.group(2)}" if match.group(1) else match.group(2)


def header_fields(context: DocumentContext) -> dict[str, str | None]:
    """물건과 무관한 화면 하단 필드(작성자·금액·수수료)."""
    parties = context.parties
    account = context.account
    fee = context.fee
    return {
        # 발송 기준(2026-08-25 실물 01-2607-3-2403): 대표·심사자는 비워서 발송 → 넣지 않는다.
        "대표,지사장": None,
        "평가사명1@2": parties.appraiser(0),   # 라벨 오른쪽 둘째 콤보가 이름(첫째는 빈 콤보)
        "평가사명2@2": parties.appraiser(1),
        "평가사명3@2": parties.appraiser(2),
        "심사자": None,
        "총감정가액": _money(context.total_amount),
        "기준시점": context.price_point_date,
        "현장답사일": context.survey_date,
        "순수수료": _money(fee.net),
        "실   비": _money(fee.expense_with_vat),
        "감정평가료": _money(fee.total),
        # 수수료입금계좌번호·계좌입금자명·사업등록번호는 신한 폼에 칸이 없다(국민 전용) — 실화면 확인(2026-08-25).
    }


def characteristic_fields(context: DocumentContext) -> dict[str, str]:
    """물건특성 8종. 의견서 표가 없으면 기본값으로 채운다."""
    found = context.characteristics
    fields = {
        label: getattr(found, key) or DEFAULT_CHARACTERISTIC
        for label, key in _CHARACTERISTIC_FIELDS
    }
    # 물건특성 표에 임대 답이 없으면 .gam 요약표 비고의 임대료 단서(`월 임대료 : 3,800,000원`)로 임대있음을 가리고,
    # 그것도 없을 때만 기본값(2831 담당자 지적 2026-09-11 — 임대 중인 건이 자가사용으로 나갔다).
    if found.lease in (None, "", LEASE_UNKNOWN):
        fields["임대"] = context.lease_hint or DEFAULT_LEASE
    else:
        fields["임대"] = found.lease
    return fields


def property_fields(
    context: DocumentContext,
    row: MullistRow,
    combos: dict[str, frozenset[str]] | None = None,
) -> dict[str, str | None]:
    """물건 1건 → 화면 필드.

    combos 에 실제 콤보 목록을 주면 목록에 없는 값은 None 이 되어 비워진다
    (엉뚱한 값을 넣느니 비우는 편이 안전하다).
    """
    allowed = combos or {}
    outline = context.outline
    jibun = context.jibun
    row_jibun = _row_jibun(row.address)
    cost = representative(context.cost_layers)

    struct = category = None
    if row.is_building:
        struct = codes.building_struct(
            row.struct_or_category or outline.struct, allowed.get("건물구조(신)")
        )
    elif row.is_land:
        category = codes.land_category(row.struct_or_category, allowed.get("지목"))

    kind = codes.collateral_kind(row.collateral_kind, allowed.get("담보종류"))
    if row.is_land and category and (allowed.get("담보용도") is None or category in allowed["담보용도"]):
        # 토지 물건: 담보종류·담보용도 = 지목(사용자 정정 2026-08-27, 2673: 공장→공장용지).
        use = category
        if allowed.get("담보종류") is None or category in allowed["담보종류"]:
            kind = category
    elif row.is_machine:
        # 기계기구 물건: 담보종류 '기계기구', 담보용도 '기타부동산(단독시설)'(사용자 정정 2026-08-27).
        kind = MACHINE_KIND if allowed.get("담보종류") is None or MACHINE_KIND in allowed["담보종류"] else kind
        use = MACHINE_USE if allowed.get("담보용도") is None or MACHINE_USE in allowed["담보용도"] else None
    else:
        use = codes.collateral_use(kind, allowed.get("담보용도"))
    is_unit = row.is_unit_building   # 구분건물(집합건물 호실)만 등기번호를 넣는다(사용자 확정 2026-08-27)
    unit = units.by_mark(context.units, row.mark) if is_unit else None

    zone = row.zone or outline.zone
    if allowed.get("용도지역구분(신)") is not None and zone not in allowed["용도지역구분(신)"]:
        zone = None
    if row.is_building and not is_unit:
        zone = None      # 토지건물의 건물 행엔 용도지역 안 넣음(사용자 정정 2026-08-27, 2673)

    return {
        "물건순번": None,      # 화면 행 번호(그리드가 매김) — 쓰지 않는다. 매칭은 본번지·부번지(2026-08-25)
        "담보종류": kind,
        "담보용도": use,
        "담보세부종류": row.object_kind,
        "용도지역구분(신)": zone,
        "건물구조(신)": struct,
        "지목": category,
        # 화면 안내 "※아래 칸은 동미만 주소만 입력" = 동/리 **아래** 부분(지번·건물명·동·층·호)만.
        # 업무팀 실물(2676, 2026-08-26): '415-9 강동역SK리더스뷰 103동 6층 607호'. 은행 선입력값을 덮어쓴다.
        "소재지": _location(context, row),
        "법정동_시군구": jibun.reg if jibun else None,
        "법정동_읍면동": jibun.eub if jibun else None,
        "번지구분": row_jibun[0] if row_jibun else (jibun.jibun_kind if jibun else None),
        "본번지": row_jibun[1] if row_jibun else (jibun.bun1 if jibun else None),
        "부번지": row_jibun[2] if row_jibun else (jibun.bun2 if jibun else None),
        "공부면적(수량)": _area(row.area_public),
        "사정면적": _area(row.area_assessed),
        # 호별 대지권면적(의견서 개요 호별 표, 기호=SNO) 우선 — 2695: 11.788/9.2774/10.534 (사용자 정정 2026-08-27). 없으면 대표값.
        # 의견서가 없는 회보 형식(.gam 에 HWP 없음, 2819)은 개요·호별 표가 다 비므로 명세표 '소유권대지권' 행으로(2026-09-14).
        "대지권면적": _area(unit.area_land_right if unit and unit.area_land_right is not None
                       else (outline.area_land_right if outline.area_land_right is not None
                             else context.spec_extras.land_right_for(row.mark))),
        "감정평가액": _money(row.amount),
        "평가단가": _unit_price(row),
        # 건물 전용 칸: 토지 물건엔 넣지 않는다(발송 실물 2403: 토지 행은 비어 있음). 기계기구는 행 값만.
        "사용승인일": (row.approval_date or outline.approval_date) if row.is_building else None,   # 기계기구도 비움(2026-08-27)
        # 내용연수·잔존연수는 신한은 넣지 않는다(업무팀 확정 2026-08-26) — 문서에 값이 있어도 비운다.
        "내용연수": None,
        "잔존연수": None,
        "총층수": _int(outline.ground_floors, context.spec_extras.ground_floors) if row.is_building else None,   # 명세표 '20층' 폴백(2819)
        "해당층수": _floor_no(row.address or outline.address),
        "총방수": None,         # 어떤 소스에도 없다
        # 등기부번호는 물건 종류에 맞는 칸에 숫자만(업무팀 실물 2676: 건물등기부번호 24012026017191).
        # mullist DUNG_NO 우선, 없으면 공부 스캔(T_SCAN_GONGBU).
        # 등기부번호는 구분건물(집합건물)만 건물등기부번호에 넣고, 토지건물·토지는 둘 다 비움(사용자 확정 2026-08-27).
        "토지등기부번호": None,
        "건물등기부번호": _digits(row.registry_no or context.registry_no(kind="건물", seq_no=row.seq_no))
                      if (row.is_building and is_unit) else None,
    }


_JIBUN_TAIL_RE = re.compile(r"\s*(?:번지|외\s*\d+\s*필지|제?\d+층|제?\d+호|[가-힣]*동\s*\d+호|\d+동).*$")
_JIBUN_RE = re.compile(r"(산)?\s*(\d+)(?:-(\d+))?\s*$")


def _row_jibun(address: str | None) -> tuple[str, str, str] | None:
    """물건 주소의 지번 → (번지구분, 본번지, 부번지). '356-2 외 1필지'·'산 12-3'·'798-3 제9층 제901호' 처리.

    물건마다 지번이 다르므로(2552: 356-2/356-3/356-26…) 문서 대표 지번을 쓰면 안 된다(2026-08-25).
    """
    if not address:
        return None
    core = _JIBUN_TAIL_RE.sub("", address.strip())
    match = _JIBUN_RE.search(core)
    if not match:
        return None
    san, bun1, bun2 = match.groups()
    return ("산" if san else "일반", bun1, bun2 or "0")


_JIBUN_TOKEN_RE = re.compile(r"^(산)?(\d+)(?:-(\d+))?(번지)?(외|,)?$")   # '1601-10외' (등기 주소, 2819) 도 지번 토큰


def _below_dong(address: str | None) -> str | None:
    """주소에서 동/리 이하만: 지번부터 끝까지. '제103동 제6층 제607호' 의 '제' 는 **그대로 둔다**
    (발송 실물 2695 '580 …스퀘어동 제3층 제4-305호', 사용자 확정 2026-08-27; 종전엔 뗐음).

    '서울특별시 강동구 길동 415-9 "강동역에스케이리더스뷰" 제103동 제6층 제607호'
        → '415-9 강동역에스케이리더스뷰 제103동 제6층 제607호'
    '경기도 여주시 점봉동 산 12-3' → '산 12-3'   /  '도곡리 356-2 외 1필지' → '356-2 외 1필지'
    지번을 못 찾으면 None(은행 선입력값을 그대로 둔다).
    """
    if not address:
        return None
    tokens = address.replace('"', " ").replace("'", " ").split()
    start = None
    for i, tok in enumerate(tokens):
        if tok == "산" and i + 1 < len(tokens) and _JIBUN_TOKEN_RE.match(tokens[i + 1]):
            start = i
            break
        if _JIBUN_TOKEN_RE.match(tok) and not tok.isdigit() or (tok.isdigit() and i > 0 and re.search(r"[동리가읍면]$", tokens[i - 1])):
            start = i
            break
    if start is None:
        return None
    out = []
    for tok in tokens[start:]:
        tok = re.sub(r"번지$", "", tok)
        if tok:
            out.append(tok)
    return " ".join(out) or None


def _location(context: DocumentContext, row: MullistRow) -> str | None:
    """'※아래 칸은 동미만 주소만' 칸(읍면동 아래) — 발송 실물(2673·2695, 2026-08-27) 관례:
    구분건물 = 주소 원문의 동 이하('580 …스퀘어동 제3층 제4-305호'), 토지 = 지번('144-12'),
    토지건물의 건물 = 공부스캔 건물 주소의 동 이하('144 주건축물제1동'), 기계기구 = 지번 + 명칭('144 전동 체인호이스트')."""
    address = row.address or context.outline.address
    if row.is_building and not row.is_unit_building:
        want = _digits(row.registry_no)
        for g in context.gongbu:
            if (g.kind or "").strip() == "건물" and g.address and (not want or _digits(g.unique_no) == want):
                return _below_dong(g.address) or _below_dong(address)
    if row.is_unit_building:
        # 구분건물도 등기 표제부 주소가 건물명까지 갖춘다('1601-10외 3필지 서초어반하이오피스텔 제지1층 제비01호' — 2819 담당자
        # 완성본과 글자 그대로 일치). mullist ADDR_NEW 엔 건물명이 없다. **등기번호가 정확히 맞는 행만** 쓴다(fail-closed, 2026-09-14).
        want = _digits(row.registry_no)
        if want:
            for g in context.gongbu:
                if (g.kind or "").strip() == "건물" and g.address and _digits(g.unique_no) == want:
                    hit = _below_dong(g.address)
                    if hit:
                        return hit
    if row.is_machine:
        jibun = _below_dong(address)
        machines = [m for m in context.machines if m.name]
        if machines:
            # 기계기구 물건이 여럿이면 mullist 순서대로 표의 행을 짝지운다.
            before = list(context.properties).index(row) if row in context.properties else 0
            idx = sum(1 for p in context.properties[:before] if p.is_machine)
            name = machines[min(idx, len(machines) - 1)].name
            return f"{jibun} {name}".strip() if jibun else name
        return jibun
    return _below_dong(address)


def _int(*candidates: int | None) -> str | None:
    for value in candidates:
        if value is not None:
            return str(value)
    return None


def build(
    context: DocumentContext,
    combos: dict[str, frozenset[str]] | None = None,
) -> tuple[dict[str, str | None], ...]:
    """물건별 화면 필드 묶음. 헤더·물건특성은 모든 물건에 같은 값으로 붙인다."""
    header = header_fields(context)
    traits = characteristic_fields(context)
    if not context.has_mullist:
        # mullist 없는 32% — 물건 단위 값이 없으므로 헤더만 채운다.
        return ({**header, **traits},)
    return tuple(
        {**header, **traits, **property_fields(context, row, combos)}
        for row in context.properties
    )
