"""법인카드 사용내역 엑셀 → 아마란스 일반전표 분개 생성.

재무팀이 카드사 포털에서 받아 용도·공제여부를 확정한 엑셀(.xls)을 읽어
아마란스 자동전표(api11A10, docuTy=1 일반)로 보낼 분개를 만든다.

분개 규칙 (재무팀 실제 전표 대조로 확인):
  공제대상 → 차변 비용(공급가액) + 차변 부가세대급금(부가세) / 대변 미지급금(승인금액)
  미공제   → 차변 비용(승인금액 전액)                        / 대변 미지급금(승인금액)
세무구분은 두 경우 모두 17(카드), 증빙은 8(신용카드매출전표).

이 모듈은 조립·검증까지만 한다. 아마란스 전송은 호출하는 쪽에서 한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

# 엑셀 사용용도 → 아마란스 계정코드 (DZ_Code 판매관리비 계열 + 실제 전표 대조)
ACCOUNT_MAP = {
    "복리후생비": "8110000",
    "차량유지비": "8220000",
    "여비교통비": "8120000",
    "통신비": "8140000",
    "운반비": "8240000",
    "지급수수료": "8310000",
    "체력단련비": "8590000",
    "미수금": "1200000",
}
ACCOUNT_VEHICLE = ACCOUNT_MAP["차량유지비"]   # 8220000 — 업무용승용차(carCd) 필수
ACCOUNT_PAYABLE = "2530000"    # 미지급금 (대변, 거래처=카드)
ACCOUNT_VAT_INPUT = "1350000"  # 부가세대급금 (공제대상일 때만)

# 계정별로 적요 뒤에 붙이는 용도 문구 (재무팀 수기 관행, 2026-08-07 요청).
# 복리후생비는 가맹점만 적으면 무슨 명목인지 안 보여서 용도를 덧붙인다.
# 예: 3771.08.06. 죠샌드위치&마우이포케 서초점-사원식대 및 회식대
REMARK_SUFFIX = {
    ACCOUNT_MAP["복리후생비"]: "-사원식대 및 회식대",
}
# 아마란스 rmkDc 한도. 가맹점명이 길어도 용도 문구가 잘리지 않게 이 값에 맞춰
# 앞부분을 줄인다 — 잘린 "…-사원식"은 안 붙느니만 못하다.
REMARK_MAX = 80

TAX_FG_CARD = "27"       # 세무구분 27.카드매입 (17은 카드매출 — 재무팀 수기 전표 실측 2026-08-11)
ATTR_CD_CARD_SLIP = "8"  # 증빙 8.신용카드매출전표
DOCU_TY_GENERAL = "1"    # 전표유형 1.일반

REQUIRED_COLUMNS = (
    "카드사", "카드번호", "사용자", "사용일자", "승인번호", "가맹점",
    "승인금액", "공급가액", "부가세", "사용용도", "공제대상", "사업자번호", "취소여부",
)


@dataclass
class CardUsage:
    """엑셀 1행 = 카드 사용 1건."""

    row_no: int
    card_no: str
    card_alias: str
    user_name: str
    use_date: str        # YYYYMMDD
    appr_no: str
    merchant: str
    merchant_biz_no: str
    total: Decimal       # 승인금액
    supply: Decimal      # 공급가액
    vat: Decimal         # 부가세
    purpose: str         # 사용용도 = 계정과목명
    deductible: bool     # 공제대상 여부
    canceled: bool
    industry: str = ""
    # 계정을 우리 이력에서 자동으로 채웠다는 표시 — 화면이 '자동' 딱지를 붙여
    # 담당자가 훑어보고 고칠 수 있게 한다 (2026-08-20).
    auto_purpose: bool = False
    appr_time: str = ""  # 승인시간 HH:MM:SS (엑셀·CB2_APPR 공통, 검증 화면 표시용)
    tax_info: str = ""   # 과세정보 (일반과세 등, 엑셀에만 있음 — DB 수집분은 빈 값)
    # 확정된 계정코드·적요. 담당자가 화면에서 고친 값을 그대로 전송하기 위해 보관한다
    # (사용용도에서 매번 다시 매핑하면 확정 당시 승인한 내용과 달라질 수 있다).
    account_code: str = ""
    remark: str = ""
    holds: list[str] = field(default_factory=list)  # 보류 사유
    # 이미 전표로 만든 건이면 그 전표의 상태(D 확정·S 전송완료·F 전송실패). 화면이
    # 전송완료 건만 숨기고 미전송·실패 건은 계속 보여주기 위해 쓴다.
    processed_status: str = ""

    split_no: int = 1  # 한 승인건을 여러 용도로 쪼갠 경우의 순번

    @property
    def appr_key(self) -> str:
        """승인 1건을 가리키는 키 (분할 전)."""
        return f"CARD-{self.card_no}-{self.use_date}-{self.appr_no}"

    @property
    def dedup_key(self) -> str:
        """중복 방지 키. 같은 건이 다른 엑셀에 섞여 와도 한 번만 생성한다.

        한 승인건을 용도별로 쪼개는 것은 정상 업무라 분할 순번까지 포함한다.
        """
        return f"{self.appr_key}-{self.split_no}"

    @property
    def on_hold(self) -> bool:
        return bool(self.holds)

    @property
    def blocked(self) -> bool:
        """확정을 막는 보류가 하나라도 있나 — 안내뿐이면 확정할 수 있다."""
        return any(not is_advisory(hold) for hold in self.holds)

    @property
    def auto_remark(self) -> str:
        """재무팀 수기 전표 적요 관행: 카드끝4자리.월.일. 가맹점 (예: 9051.07.31. 카카오T일반택시)

        복리후생비처럼 용도 문구가 정해진 계정은 뒤에 그 문구를 붙인다
        (예: 3771.08.06. 죠샌드위치&마우이포케 서초점-사원식대 및 회식대).
        """
        card_tail = self.card_no[-4:] if self.card_no else ""
        mmdd = (
            f"{self.use_date[4:6]}.{self.use_date[6:8]}."
            if len(self.use_date or "") == 8 else ""
        )
        prefix = f"{card_tail}.{mmdd}" if card_tail and mmdd else f"{card_tail}{mmdd}"
        base = f"{prefix} {self.merchant}".strip()
        suffix = REMARK_SUFFIX.get(self.account_code, "")
        if not suffix:
            return base
        return f"{base[: REMARK_MAX - len(suffix)].rstrip()}{suffix}"


def _digits(value: Any) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _amount(value: Any) -> Decimal:
    text = str(value or "0").replace(",", "").strip()
    try:
        return Decimal(text or "0")
    except Exception:
        return Decimal("0")


def parse_excel(path: str) -> list[CardUsage]:
    """카드 사용내역 엑셀(.xls/.xlsx)을 읽어 CardUsage 목록으로 만든다."""
    rows = _read_rows(path)
    if not rows:
        raise ValueError("엑셀에 데이터가 없습니다.")
    missing = [c for c in REQUIRED_COLUMNS if c not in rows[0]]
    if missing:
        raise ValueError(f"엑셀 형식이 다릅니다. 없는 컬럼: {', '.join(missing)}")

    usages = []
    for i, row in enumerate(rows, start=2):  # 2행부터가 데이터 (1행=머리글)
        usages.append(
            CardUsage(
                row_no=i,
                card_no=_digits(row.get("카드번호")),
                card_alias=str(row.get("카드별칭") or "").strip(),
                user_name=str(row.get("사용자") or "").strip(),
                use_date=_digits(row.get("사용일자"))[:8],
                appr_no=str(row.get("승인번호") or "").strip(),
                merchant=str(row.get("가맹점") or "").strip(),
                merchant_biz_no=_digits(row.get("사업자번호")),
                total=_amount(row.get("승인금액")),
                supply=_amount(row.get("공급가액")),
                vat=_amount(row.get("부가세")),
                purpose=str(row.get("사용용도") or "").strip(),
                deductible=str(row.get("공제대상") or "").strip() == "공제대상",
                canceled=str(row.get("취소여부") or "").strip() != "정상",
                industry=str(row.get("업종") or "").strip(),
                appr_time=str(row.get("승인시간") or "").strip(),
                tax_info=str(row.get("과세정보") or "").strip(),
                account_code=ACCOUNT_MAP.get(str(row.get("사용용도") or "").strip(), ""),
            )
        )
    for u in usages:
        u.remark = u.auto_remark
    return usages


def _read_rows(path: str) -> list[dict[str, Any]]:
    """.xls(BIFF)와 .xlsx를 모두 읽어 [{컬럼명: 값}] 으로 반환."""
    if path.lower().endswith(".xls"):
        import xlrd

        sheet = xlrd.open_workbook(path).sheet_by_index(0)
        header = [str(sheet.cell_value(0, c)).strip() for c in range(sheet.ncols)]
        rows = []
        for r in range(1, sheet.nrows):
            values = {}
            for c, name in enumerate(header):
                v = sheet.cell_value(r, c)
                if isinstance(v, float) and v == int(v):
                    v = int(v)
                values[name] = str(v).strip()
            if any(values.values()):
                rows.append(values)
        return rows

    from openpyxl import load_workbook

    ws = load_workbook(path, data_only=True).worksheets[0]
    it = ws.iter_rows(values_only=True)
    header = [str(v or "").strip() for v in next(it)]
    rows = []
    for raw in it:
        values = {h: ("" if v is None else str(v).strip()) for h, v in zip(header, raw)}
        if any(values.values()):
            rows.append(values)
    return rows


def assign_split_numbers(usages: list[CardUsage]) -> "dict[str, list[CardUsage]]":
    """한 승인건이 여러 행으로 쪼개진 경우 분할 순번을 매기고 승인번호별로 묶어 준다.

    dedup_key가 이 순번을 포함하므로, 키로 중복을 조회하기 전에 먼저 불러야 한다.
    같은 목록에 여러 번 불러도 결과가 같다.
    """
    groups: dict[str, list[CardUsage]] = {}
    for u in usages:
        groups.setdefault(u.appr_key, []).append(u)
    for group in groups.values():
        for n, u in enumerate(group, start=1):
            u.split_no = n
    return groups


# 확정을 막지 않는 '안내' 보류 (2026-08-20 사용자 결정). 화면에는 노란 줄로
# 그대로 보이지만 골라서 확정할 수 있다.
#  - 가맹점 거래처: 2026-08-19 에 분개 세 줄을 모두 카드사 거래처로 통일하면서
#    쓰지 않는 값이 됐는데 검사만 남아 있었다.
#  - 승인번호 분할: 한 승인건을 용도별로 쪼개는 것은 정상 업무다(dedup_key 가
#    분할 순번을 포함하는 이유). 확인하라는 안내지 막을 일이 아니다.
# 화면(card-vouchers.js)에도 같은 목록이 있다 — 시험이 둘을 맞춰 둔다.
ADVISORY_HOLDS = ("가맹점 거래처 없음", "승인번호 분할")


def is_advisory(hold: str) -> bool:
    return str(hold or "").startswith(ADVISORY_HOLDS)


PROCESSED_HOLD = {
    "S": "이미 아마란스로 전송된 건",
    "D": "이미 전표로 확정된 건(미전송)",
    "F": "전표 전송에 실패한 건",
}


def apply_confirmed(usages: list[CardUsage], stored: "dict[str, Any]") -> None:
    """처리된 건의 표시 값을 확정 당시 저장한 값으로 되살린다 (2026-08-31 사용자 제보).

    다시 불러온 목록은 카드사 원천(DEDUCT_YN)과 자동 추천으로 그려져, 확정 때
    고친 공제·계정이 되돌아간 것처럼 보였다("확정하면 무조건 공제로 바뀌나?").
    전표에 저장된 값이 진실이고, 화면·엑셀 내보내기도 그와 같아야 한다.
    """
    for u in usages:
        saved = stored.get(u.dedup_key)
        if saved is None:
            continue
        u.purpose = saved.purpose or u.purpose
        u.account_code = saved.account_code or u.account_code
        u.deductible = bool(saved.deductible)
        u.supply = saved.supply
        u.vat = saved.vat
        u.remark = saved.remark or u.remark
        u.auto_purpose = False  # 확정 값은 자동 추천이 아니다


def validate(
    usages: list[CardUsage],
    *,
    known_keys: "set[str] | dict[str, str] | None" = None,
) -> None:
    """보류 사유를 각 건에 채운다. 전표 생성은 보류가 없는 건만 대상으로 한다.

    금액 검증은 공제대상 건에만 건다. 미공제는 분개에 승인금액만 쓰고
    공급가·부가세를 쓰지 않아, 그 두 칸이 어긋나도 분개는 정확하다.

    known_keys는 dedup_key→전표상태 매핑을 받는다(집합을 주면 상태 미상으로 본다).
    """
    known = known_keys or {}
    if not isinstance(known, dict):
        known = {key: "" for key in known}

    groups = assign_split_numbers(usages)

    for u in usages:
        if u.canceled:
            u.holds.append("취소 건")
        if not u.account_code:
            u.holds.append(f"계정 미매핑(사용용도: {u.purpose or '없음'})")
        if u.total <= 0:
            u.holds.append("승인금액 없음")
        elif u.deductible and u.supply + u.vat != u.total:
            u.holds.append(
                f"금액 불일치(공급가 {u.supply:,} + 부가세 {u.vat:,} ≠ 승인 {u.total:,})"
            )
        if len(u.merchant_biz_no) != 10:
            u.holds.append("가맹점 사업자번호 없음/형식오류")
        if not u.card_no:
            u.holds.append("카드번호 없음")
        if u.dedup_key in known:
            u.processed_status = known[u.dedup_key] or ""
            u.holds.append(PROCESSED_HOLD.get(u.processed_status, "이미 전표가 생성된 건"))

    # 분할 건: 쪼갠 금액의 합이 원 승인금액과 맞는지 확인할 수 없으므로,
    # 최소한 같은 승인번호가 몇 건으로 쪼개졌는지 알려 담당자가 확인하게 한다.
    for key, group in groups.items():
        if len(group) > 1:
            rows = ", ".join(str(g.row_no) for g in group)
            for u in group:
                u.holds.append(f"승인번호 분할 {len(group)}건(행 {rows}) — 금액 확인 필요")


def build_lines(
    usages: list[CardUsage],
    *,
    division_code: str,
    voucher_date: str,
    menu_sq: int,
    card_partners: dict[str, str],
    merchant_partners: dict[str, str],
    emp_cd: str = "",
    dept_cd: str = "",
    vehicles: "dict[str, str] | None" = None,
) -> list[dict[str, Any]]:
    """보류가 없는 건들을 하루치 한 전표(menu_sq)의 분개 라인으로 조립한다.

    vehicles: 카드 사용자명 → 아마란스 업무용승용차 코드(carCd). 차량유지비(8220000) 비용 라인에만 싣는다
      (재무팀 전표 실측 2026-08-24: 관리항목 '업무용승용차' = c3Type 0000002166 / c3Value 313도5539).

    card_partners: 카드번호 → 아마란스 거래처코드(trFg=9)
    merchant_partners: 가맹점 사업자번호 → 아마란스 거래처코드
      (거래처를 카드사로 통일하면서 분개에는 더 안 쓰지만, 호출부 호환을 위해 남겨둔다)
    emp_cd/dept_cd: 작성자(empCd)·작성부서(ctDept) — a10_user_emp_map에서 온 값.
      비어 있으면 기존처럼 미전송 (재무팀 수기 전표는 empCd=사원코드, ctDept=1010).
    """
    common = {
        "inDivCd": division_code,
        "menuDt": voucher_date,
        "menuSq": menu_sq,
        "docuTy": DOCU_TY_GENERAL,
    }
    if emp_cd:
        common["empCd"] = emp_cd
    if dept_cd:
        common["ctDept"] = dept_cd
    lines: list[dict[str, Any]] = []

    def add(drcr: str, account: str, amount: Decimal, partner: str, remark: str,
            *, taxed: bool = False, vat_line: bool = False,
            usage: CardUsage | None = None) -> None:
        line = {
            **common,
            "menuLnSq": len(lines) + 1,
            "drcrFg": drcr,
            "acctCd": account,
            "acctAm": float(amount),
            "trCd": partner,
            "rmkDc": remark[:80],
        }
        if taxed and usage is not None:
            line.update({
                "taxFg": TAX_FG_CARD,
                "attrCd": ATTR_CD_CARD_SLIP,
                "regNb": usage.merchant_biz_no,
            })
            if account == ACCOUNT_VEHICLE and vehicles:
                car_cd = vehicles.get((usage.user_name or "").strip())
                if car_cd:
                    line["carCd"] = car_cd
        if vat_line and usage is not None:
            # 부가세계정 라인은 부가세사업장·신고기준일·세무구분·공급가액이 필수다
            # (감정서 매출전표의 부가세예수금 라인과 같은 규칙).
            # ctNb는 세무구분 27에서 결제카드(카드 거래처코드) 칸이다 — 승인번호가
            # 아니다 (아마란스 자동수집 전표 실측 2026-08-14: 부가세대급금 라인에만
            # 실리고 비용·미공제 라인엔 없다).
            line.update({
                "vatDivCd": division_code,
                "issDt": voucher_date,
                "taxFg": TAX_FG_CARD,
                "supAm": float(usage.supply),
                "attrCd": ATTR_CD_CARD_SLIP,
                "regNb": usage.merchant_biz_no,
                "ctNb": card_partners.get(usage.card_no, ""),
            })
        lines.append(line)

    for u in usages:
        if u.on_hold:
            continue
        card_cd = card_partners.get(u.card_no, "")
        remark = u.remark or u.auto_remark
        # 거래처는 세 라인 모두 카드사로 통일한다 (재무팀 요청 2026-08-19).
        # 가맹점은 적요와 부가세 라인의 사업자번호(regNb)로 남는다.
        if u.deductible:
            add("3", u.account_code, u.supply, card_cd, remark, taxed=True, usage=u)
            add("3", ACCOUNT_VAT_INPUT, u.vat, card_cd, remark, vat_line=True, usage=u)
        else:
            # 미공제는 부가세를 비용에 합산해 한 줄로 (재무팀 전표와 동일)
            add("3", u.account_code, u.total, card_cd, remark, taxed=True, usage=u)
        add("4", ACCOUNT_PAYABLE, u.total, card_cd, remark)
    return lines


# split_amounts(승인금액 ÷ 1.1 로 공급가액·부가세를 만들던 것)는 2026-08-21 에
# 걷어냈다. 그때까지는 카드사가 두 칸을 안 줘서 화면·결재 양식이 비어 보였는데
# (2026-08-20 실측 848건 중 287건), 재무팀이 CB2_APPR 에 실제 값을 채워 넣었다.
# 본사 8월 937건 기준 공급가액 926 · 부가세 913 이 원천에 있고, 공제 대상 906건은
# 공급가액+부가세가 승인금액과 **전부** 일치한다(불일치 0건). 추정식을 남겨 두면
# 카드사가 안 준 11건에 없는 부가세를 만들어 낸다 — 면세 거래가 특히 그렇다.


def summarize(usages: list[CardUsage]) -> dict[str, Any]:
    # 생성대상은 '확정을 막는 보류가 없는 것' — 안내뿐인 건은 생성대상에 든다.
    ready = [u for u in usages if not u.blocked]
    held = [u for u in usages if u.blocked]
    return {
        "total_count": len(usages),
        "ready_count": len(ready),
        "hold_count": len(held),
        "ready_amount": float(sum(u.total for u in ready)),
        "deductible_count": sum(1 for u in ready if u.deductible),
        "dates": sorted({u.use_date for u in usages if u.use_date}),
    }


def missing_vehicles(usages: list[CardUsage], vehicles: "dict[str, str] | None") -> list[str]:
    """차량유지비 건인데 업무용승용차가 없는 카드 사용자 목록 (보류 건 제외, 이름 순)."""
    known = vehicles or {}
    names = {
        (u.user_name or "").strip() or "(사용자 없음)"
        for u in usages if not u.on_hold and u.account_code == ACCOUNT_VEHICLE
        and not known.get((u.user_name or "").strip())
    }
    return sorted(names)
