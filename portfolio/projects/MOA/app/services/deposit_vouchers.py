"""CB2 입금 → 아마란스 반제·일반 입금전표 자동 생성.

재무팀이 CB2 Memo에 적어둔 감정서번호가 매칭 근거다(2026-08 검증:
3개월 801건 라벨, 99.4% 실존). 배치는 추측하지 않는다 — Memo가 감정서번호·
지사명인 입금과 적요가 400번호인 약식만 전표로 만들고, 나머지('*'·기타·
빈 값)는 제외로 기록만 한다.

전표 모양은 재무팀 수기 전표를 그대로 따른다(실전표 대조 확정):
- 반제(외상매출금 전표 보유): docuTy 4 — 차변 1030000(계좌 거래처)
  / 대변 1080000(원거래처, 관리번호), 적요 "정산 {감정서번호}"
- 일반(외상매출금 없음): docuTy 3 — 차변 1030000(계좌 거래처, 관리번호)
  / 대변 4010001(원거래처, 관리번호) + 2550000 부가세, 수수료합계+부가세가
  입금액과 다르면 전송하지 않고 보류(fail-closed)
- 지사 입금(Memo 지사명 또는 400 접수 OfficeID≠10): docuTy 7 본지점 —
  차변 1030000 / 대변 1410xxx 지사계정 쌍, 하루 1장 묶음 (수기 00086·00069)
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.bank_account_map import BankAccountMap
from app.models.deposit_outbox import DepositOutbox
from app.models.kb_branch_map import KbBranchMap
from app.models.kb_yak_item import KbYakItem
from app.services.bank_division import bank_division
from app.services.sales_division import (
    YAK_SALES_DIVISION,
    sales_account,
    sales_division,
)
from app.models.voucher_cache import VoucherCache
from app.services.default_vouchers import (
    TAX_FG_CASH,
    TAX_FG_TAXABLE,
    DefaultVoucherService,
    _FIXED_DEPT_CD,
    has_cash_receipt,
)
from app.services.deposit_source import fetch_deposits

_DOC_RE = re.compile(r"^(\d{2}-\d{4}-[0-9A-Z]-\d{4})\b")
# 기본전표(10000+)·카드전표와 겹치지 않는 작성번호 대역
_MENU_SQ_BASE = 50000
_MENU_SQ_SPAN = 40000
# 개인 고객(사업자번호 없음)의 매출 거래처 — 재무팀 확인(2026-08-05)
_MISC_PARTNER_CD = "0000001162"  # 기타-본사
# 선수금 수령 전표의 대변 전용 거래처(아마란스 api16S11 실조회).
_ADVANCE_PARTNER_CD = "0000043767"  # 본사-선수금
# 국민 약식 개별 입금 — 적요가 "400xxxxxx/대체입금/" 형태로 들어온다
_YAK_JEOKYO_RE = re.compile(r"^(400\d{6})/")


def classify_memo(memo: str | None) -> "tuple[str, str | None]":
    """Memo → (분류, 감정서번호). 번호 바로 뒤의 점은 선수금 표시다."""
    value = str(memo or "").strip()
    if not value:
        return "EMPTY", None
    if "*" in value:
        return "STAR", None
    if value == "잡이익":
        return "MISC_INCOME", None
    if branch_salary_from_memo(value):
        return "SALARY", None
    match = _DOC_RE.match(value)
    if match:
        category = "ADVANCE" if value[match.end():].startswith(".") else "DOC"
        return category, match.group(1)
    if "지사" in value or "본사" in value:
        return "BRANCH", None
    return "OTHER", None


def yak_no_from_jeokyo(jeokyo: str | None) -> "str | None":
    """국민 약식 개별 입금의 적요에서 400 접수번호를 뽑는다."""
    match = _YAK_JEOKYO_RE.match(str(jeokyo or "").strip())
    return match.group(1) if match else None


# 지사명(=아마란스 1410 계정명) → 본지점 계정코드. 지사 입금은 본사가 대신
# 받아 이 계정 대변으로 넘긴다(수기 00086·00069 실측). Memo 지사명 분포
# 2개월 78건이 전부 아래 이름과 문자 그대로 일치(2026-08-12 실측).
BRANCH_ACCOUNTS = {
    "경기지사": "1410002", "경인지사": "1410003", "북부지사": "1410004",
    "강원지사": "1410005", "충청지사": "1410006", "대구지사": "1410008",
    "부산지사": "1410009", "경남중앙지사": "1410010", "호남지사": "1410011",
    "제주지사": "1410013", "전북지사": "1410015", "대전세종지사": "1410016",
    "충남지사": "1410018", "울산지사": "1410019", "경북지사": "1410020",
    "경기서부지사": "1410021", "동부지사": "1410022",
}

# BANK_KB_MASTER.OfficeID(=APW office_id) → 지사 계정명. 400 약식의 지사
# 접수분 판별용 — office명('부산경남지사')과 계정명('부산지사')이 달라서
# a10_office_map 이름을 그대로 못 쓰고 고정 매핑으로 확정한다.
OFFICE_BRANCH_NAME = {
    "11": "경기지사", "12": "경인지사", "13": "북부지사", "14": "강원지사",
    "15": "충청지사", "16": "충남지사", "17": "대구지사", "18": "부산지사",
    "19": "호남지사", "21": "경남중앙지사", "22": "제주지사", "23": "동부지사",
    "24": "전북지사", "25": "대전세종지사", "26": "울산지사", "27": "경북지사",
    "28": "경기서부지사",
}

DOCU_TY_BRANCH = "7"  # 전표유형 7.본지점 (수기 00086 raw_json 실측)


def _api_rows(payload: "dict[str, Any]") -> "list[dict[str, Any]]":
    """아마란스의 세 가지 공통 resultData 포장을 행 목록으로 정규화."""
    data = payload.get("resultData")
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        for key in ("data", "datas", "list"):
            rows = data.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    return []


def branch_from_memo(memo: "str | None") -> "str | None":
    """Memo가 지사명 그대로일 때만 그 지사명 — 부분 일치는 오탐이라 안 쓴다."""
    name = str(memo or "").strip()
    return name if name in BRANCH_ACCOUNTS else None


def branch_salary_from_memo(memo: "str | None") -> "str | None":
    """'울산지사 급여입금'처럼 지사명+급여입금인 Memo에서 지사명을 찾는다."""
    value = re.sub(r"\s+", "", str(memo or ""))
    for name in sorted(BRANCH_ACCOUNTS, key=len, reverse=True):
        if value == f"{name}급여입금":
            return name
    return None


_SALARY_BRANCH_ALIASES = {
    **{name.removesuffix("지사"): name for name in BRANCH_ACCOUNTS},
    "대전": "대전세종지사",
    "경남": "경남중앙지사",
}


def branch_salary_name(
    memo: "str | None", jeokyo: "str | None"
) -> "str | None":
    """Memo 또는 적요의 '지사 약칭 + 급여' 패턴을 실제 1410 지사명으로 바꾼다."""
    aliases = {
        **{name: name for name in BRANCH_ACCOUNTS},
        **_SALARY_BRANCH_ALIASES,
    }
    for raw in (memo, jeokyo):
        value = re.sub(r"[\s_\-/]+", "", str(raw or ""))
        if "급여" not in value:
            continue
        before_salary = value.split("급여", 1)[0]
        for alias in sorted(aliases, key=len, reverse=True):
            if alias in before_salary:
                return aliases[alias]
    return None


def jeokyo_token(jeokyo: "str | None") -> str:
    """입금 적요의 첫 토큰(은행 접수번호) — 수기 본지점 전표의 적요가 이 값이다."""
    return str(jeokyo or "").split("/")[0].strip()


def branch_bundle_lines(
    *, items: "list[dict[str, Any]]", voucher_date: date, menu_sq: int,
    division_code: str, start_line_sq: int = 1,
    isu_doc: str = "지사수수료 입금",
) -> "list[dict[str, Any]]":
    """하루치 지사 입금을 본지점 전표 1장으로 — 수기 00086·00069 실측.

    건별 (차변 보통예금 / 대변 1410xxx 지사계정) 쌍을 이어 붙인다.
    차변 거래처는 입금 계좌의 은행지점이고, 대변은 계정과목 자체가 지사를
    식별하므로 거래처를 보내지 않는다. 적요는 접수번호. 은행·계좌가 섞여도
    한 전표에 담는다(00086: 국민남부+신한역삼 혼재).
    items: {token, amount, account_partner, branch_account} 목록.
    """
    common = {
        "inDivCd": division_code,
        "menuDt": voucher_date.strftime("%Y%m%d"),
        "menuSq": menu_sq,
        "docuTy": DOCU_TY_BRANCH,
        "ctDept": _FIXED_DEPT_CD,
        "isuDoc": isu_doc,
    }
    lines: "list[dict[str, Any]]" = []
    for item in items:
        remark = str(item["token"])[:80]
        lines.append(
            {**common, "menuLnSq": start_line_sq + len(lines), "drcrFg": "3",
             "acctCd": "1030000", "acctAm": float(item["amount"]),
             "trCd": item["account_partner"], "rmkDc": remark}
        )
        lines.append(
            {**common, "menuLnSq": start_line_sq + len(lines), "drcrFg": "4",
             "acctCd": item["branch_account"], "acctAm": float(item["amount"]),
             "rmkDc": remark}
        )
    return lines


def yak_bundle_lines(
    *, items: "list[dict[str, Any]]", total: Decimal, voucher_date: date,
    menu_sq: int, division_code: str, account_partner: str,
    start_line_sq: int = 1,
) -> "list[dict[str, Any]]":
    """하루치 약식을 전표 1장으로 — 재무팀 수기 관행(2026-08-05 no=00043 실측).

    차변 보통예금 합계 1줄 + 400건별 (기타수수료 + 부가세예수금) 쌍.
    items: {yak_no, supply, vat, partner_code, branch_name} 목록.
    """
    isu_doc = f"약식입금 {items[0]['yak_no']}"
    if len(items) > 1:
        isu_doc += f" 외 {len(items) - 1}건"
    common = {
        "inDivCd": division_code,
        "menuDt": voucher_date.strftime("%Y%m%d"),
        "menuSq": menu_sq,
        "docuTy": "3",
        "ctDept": _FIXED_DEPT_CD,
        "isuDoc": isu_doc[:100],
    }
    lines: "list[dict[str, Any]]" = [
        {**common, "menuLnSq": start_line_sq, "drcrFg": "3", "acctCd": "1030000",
         "acctAm": float(total), "trCd": account_partner,
         "rmkDc": "약식평가수수료 입금"},
    ]
    for item in items:
        remark = f"약식평가수수료 {item['yak_no']}"
        lines.append(
            {**common, "menuLnSq": start_line_sq + len(lines), "drcrFg": "4",
             "acctCd": "4010002", "acctAm": float(item["supply"]),
             "trCd": item["partner_code"], "rmkDc": remark,
             "maNb": item["yak_no"],
             "userlTy2": YAK_SALES_DIVISION,
             "usermTy1": bank_division(item["branch_name"] or "국민은행")}
        )
        lines.append(
            {**common, "menuLnSq": start_line_sq + len(lines), "drcrFg": "4",
             "acctCd": "2550000", "acctAm": float(item["vat"]),
             "trCd": item["partner_code"], "rmkDc": remark,
             "vatDivCd": division_code,
             "issDt": voucher_date.strftime("%Y%m%d"),
             "taxFg": (TAX_FG_CASH if item.get("cash_receipt")
                       else TAX_FG_TAXABLE),
             "supAm": float(item["supply"])}
        )
    return lines


def banje_bundle_lines(
    *, items: "list[dict[str, Any]]", voucher_date: date, menu_sq: int,
    division_code: str,
) -> "list[dict[str, Any]]":
    """하루치 반제를 전표 1장으로 — 재무팀 정산 전표 실측(2026-08-06).

    감정서별 (차변 보통예금 / 대변 외상매출금) 쌍을 이어 붙인다.
    입금 계좌가 서로 달라도 한 전표에 담는다(수기 전표 실측).
    items: {doc_id, tx_amount, account_partner, receivable_partner} 목록.
    """
    if len(items) == 1:
        single = items[0]
        isu_doc = f"입금 {single['doc_id']} {single.get('customer_name', '')}".strip()
    else:
        isu_doc = f"입금 {items[0]['doc_id']} 외 {len(items) - 1}건"
    common = {
        "inDivCd": division_code,
        "menuDt": voucher_date.strftime("%Y%m%d"),
        "menuSq": menu_sq,
        "docuTy": "4",
        "ctDept": _FIXED_DEPT_CD,
        "isuDoc": isu_doc[:100],
    }
    lines: "list[dict[str, Any]]" = []
    for item in items:
        remark = f"정산 {item['doc_id']}"
        lines.append(
            {**common, "menuLnSq": len(lines) + 1, "drcrFg": "3",
             "acctCd": "1030000", "acctAm": float(item["tx_amount"]),
             "trCd": item["account_partner"], "rmkDc": remark}
        )
        lines.append(
            {**common, "menuLnSq": len(lines) + 1, "drcrFg": "4",
             "acctCd": "1080000", "acctAm": float(item["tx_amount"]),
             "trCd": item["receivable_partner"], "maNb": item["doc_id"],
             "rmkDc": remark}
        )
    return lines


def general_lines(
    *, doc_id: str, fee: Decimal, vat: Decimal, voucher_date: date, menu_sq: int,
    division_code: str, account_partner: str, customer_partner: str,
    customer_name: str = "", cash_receipt: bool = False,
) -> "list[dict[str, Any]]":
    common = {
        "inDivCd": division_code,
        "menuDt": voucher_date.strftime("%Y%m%d"),
        "menuSq": menu_sq,
        "docuTy": "3",
        "ctDept": _FIXED_DEPT_CD,
        "isuDoc": f"입금 {doc_id} {customer_name}".strip()[:100],
    }
    lines = [
        {**common, "menuLnSq": 1, "drcrFg": "3", "acctCd": "1030000",
         "acctAm": float(fee + vat), "trCd": account_partner,
         "maNb": doc_id, "rmkDc": "수수료입금"},
        # 매출 라인에만 관리항목 L2(매출구분)·M1(은행구분) 자리가 있다.
        {**common, "menuLnSq": 2, "drcrFg": "4", "acctCd": sales_account(doc_id),
         "acctAm": float(fee), "trCd": customer_partner,
         "maNb": doc_id, "rmkDc": "일반 매출",
         "usermTy1": bank_division(customer_name)},
    ]
    division = sales_division(doc_id)
    if division:
        lines[1]["userlTy2"] = division
    if vat > 0:
        lines.append(
            {**common, "menuLnSq": 3, "drcrFg": "4", "acctCd": "2550000",
             "acctAm": float(vat), "trCd": customer_partner,
             "rmkDc": f"감정평가수수료 {doc_id}",
             "vatDivCd": division_code,
             "issDt": voucher_date.strftime("%Y%m%d"),
             "taxFg": TAX_FG_CASH if cash_receipt else TAX_FG_TAXABLE,
             "supAm": float(fee)}
        )
    return lines


def advance_lines(
    *, doc_id: str, amount: Decimal, voucher_date: date, menu_sq: int,
    division_code: str, account_partner: str, customer_partner: str,
    customer_name: str = "",
) -> "list[dict[str, Any]]":
    """선수금 수령 전표: 보통예금 차변 / 선수금 대변."""
    common = {
        "inDivCd": division_code,
        "menuDt": voucher_date.strftime("%Y%m%d"),
        "menuSq": menu_sq,
        "docuTy": "3",
        "ctDept": _FIXED_DEPT_CD,
        "isuDoc": f"선수금 {doc_id} {customer_name}".strip()[:100],
    }
    return [
        {**common, "menuLnSq": 1, "drcrFg": "3", "acctCd": "1030000",
         "acctAm": float(amount), "trCd": account_partner,
         "maNb": doc_id, "rmkDc": "선수금"},
        {**common, "menuLnSq": 2, "drcrFg": "4", "acctCd": "2590000",
         "acctAm": float(amount), "trCd": customer_partner,
         "maNb": doc_id, "rmkDc": "선수금"},
    ]


def misc_income_lines(
    *, amount: Decimal, voucher_date: date, menu_sq: int,
    division_code: str, account_partner: str,
) -> "list[dict[str, Any]]":
    """사이버브랜치 잡이익 입금: 보통예금 차변 / 잡이익 대변."""
    common = {
        "inDivCd": division_code,
        "menuDt": voucher_date.strftime("%Y%m%d"),
        "menuSq": menu_sq,
        "docuTy": "1",
        "ctDept": _FIXED_DEPT_CD,
        "isuDoc": "잡이익",
    }
    return [
        {**common, "menuLnSq": 1, "drcrFg": "3", "acctCd": "1030000",
         "acctAm": float(amount), "trCd": account_partner, "rmkDc": "잡이익"},
        {**common, "menuLnSq": 2, "drcrFg": "4", "acctCd": "9300000",
         "acctAm": float(amount), "rmkDc": "잡이익"},
    ]


class DepositVoucherService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self._default = DefaultVoucherService(db)
        self.client = self._default.client

    # ── 1단계: 입금 수집·분류 (전송 없음) ──────────────────────────
    def scan(
        self, date_from: date, date_to: date, *, legacy: bool = False
    ) -> "dict[str, int]":
        """기간 내 입금을 outbox에 적재한다. 이미 기록된 입금은 건너뛴다.

        legacy=True면 감정서번호 건도 전송 대상이 아닌 LEGACY(기존처리)로
        기록한다 — 배치 도입 시점의 백필용.
        """
        deposits = fetch_deposits(
            date_from.strftime("%Y%m%d"), date_to.strftime("%Y%m%d")
        )
        known: dict[str, DepositOutbox] = {
            entry.unique_field: entry
            for entry in self.db.scalars(
                select(DepositOutbox).where(
                    DepositOutbox.tx_day >= date_from,
                    DepositOutbox.tx_day <= date_to,
                )
            )
        }
        counts = {"new": 0, "known": 0, "reclassified": 0, "doc": 0, "excluded": 0}
        reason_of = {
            "STAR": "Memo '*' 처리완료 표시",
            "BRANCH": "지사 입금",
            "SALARY": "지사 급여입금",
            "OTHER": "기타 Memo(수기 처리 영역)",
            "EMPTY": "Memo 없음",
        }
        for row in deposits:
            unique_field = str(row["UNIQUE_FIELD"] or "").strip()
            if not unique_field:
                continue
            if unique_field in known:
                # 입금이 먼저 쌓이고 Memo는 나중에 달린다 — 전송 전 상태면
                # 현재 Memo로 다시 분류한다 (없음→감정서번호, 번호→'*' 등).
                entry = known[unique_field]
                if entry.status in ("PENDING", "EXCLUDED"):
                    category, doc_id = classify_memo(row["Memo"])
                    if branch_salary_name(row["Memo"], row["JEOKYO"]):
                        category, doc_id = "SALARY", None
                    memo_now = str(row["Memo"] or "").strip()[:500] or None
                    changed = memo_now != entry.memo
                    entry.memo = memo_now
                    yak_no = (
                        yak_no_from_jeokyo(entry.jeokyo)
                        if category in ("EMPTY", "OTHER") else None
                    )
                    if category in ("DOC", "ADVANCE"):
                        desired_kind = (
                            "ADVANCE" if category == "ADVANCE"
                            else self._voucher_kind(doc_id, entry.tx_amount)
                        )
                        state_changed = (
                            entry.doc_id != doc_id
                            or entry.voucher_kind != desired_kind
                            or entry.status == "EXCLUDED"
                        )
                        entry.doc_id = doc_id
                        entry.voucher_kind = desired_kind
                        entry.status = "LEGACY" if legacy else "PENDING"
                        entry.reason = None
                        if changed or state_changed:
                            counts["reclassified"] += 1
                    elif category == "MISC_INCOME":
                        state_changed = (
                            entry.doc_id is not None
                            or entry.voucher_kind != "MISC_INCOME"
                            or entry.status == "EXCLUDED"
                        )
                        entry.doc_id = None
                        entry.voucher_kind = "MISC_INCOME"
                        entry.status = "LEGACY" if legacy else "PENDING"
                        entry.reason = None
                        if changed or state_changed:
                            counts["reclassified"] += 1
                    elif category == "SALARY":
                        state_changed = (
                            entry.doc_id is not None
                            or entry.voucher_kind != "SALARY"
                            or entry.status == "EXCLUDED"
                        )
                        entry.doc_id = None
                        entry.voucher_kind = "SALARY"
                        entry.status = "LEGACY" if legacy else "PENDING"
                        entry.reason = None
                        if changed or state_changed:
                            counts["reclassified"] += 1
                    elif yak_no and entry.status == "EXCLUDED":
                        # 잘못 제외됐던 약식 건 복구 (Memo '*'는 STAR라 여기 안 옴)
                        entry.doc_id = yak_no
                        entry.voucher_kind = "YAK"
                        entry.status = "LEGACY" if legacy else "PENDING"
                        entry.reason = None
                        counts["reclassified"] += 1
                    elif branch_from_memo(memo_now) and entry.status == "EXCLUDED":
                        # '지사 입금'으로 제외됐던 건 복구 — 본지점 전표 대상
                        entry.doc_id = jeokyo_token(entry.jeokyo)[:30] or None
                        entry.voucher_kind = "BRANCH"
                        entry.status = "LEGACY" if legacy else "PENDING"
                        entry.reason = None
                        counts["reclassified"] += 1
                    elif category not in ("DOC", "ADVANCE", "MISC_INCOME", "SALARY") and entry.status == "PENDING" and not (
                        entry.voucher_kind == "YAK" and yak_no
                    ) and not (
                        entry.voucher_kind == "BRANCH" and branch_from_memo(memo_now)
                    ):
                        # 약식(적요 400번호)은 Memo가 비어도 전송 대상 — 신규 적재와
                        # 같은 예외를 재분류에도 적용한다 (Memo '*'가 달리면 제외).
                        entry.status = "EXCLUDED"
                        entry.reason = reason_of[category]
                        counts["reclassified"] += 1
                    elif changed:
                        counts["reclassified"] += 1
                counts["known"] += 1
                continue
            category, doc_id = classify_memo(row["Memo"])
            if branch_salary_name(row["Memo"], row["JEOKYO"]):
                category, doc_id = "SALARY", None
            txday = str(row["ACCT_TXDAY"])
            entry = DepositOutbox(
                unique_field=unique_field,
                bank_cd=str(row["BANK_CD"] or "").strip(),
                acct_no=str(row["ACCT_NO"] or "").strip(),
                tx_day=date(int(txday[:4]), int(txday[4:6]), int(txday[6:8])),
                tx_amount=Decimal(str(row["TX_AMT"] or 0)),
                jeokyo=str(row["JEOKYO"] or "").strip()[:100] or None,
                memo=str(row["Memo"] or "").strip()[:500] or None,
            )
            yak_no = (
                yak_no_from_jeokyo(entry.jeokyo)
                if category in ("EMPTY", "OTHER") else None
            )
            if category in ("DOC", "ADVANCE"):
                entry.doc_id = doc_id
                entry.voucher_kind = (
                    "ADVANCE" if category == "ADVANCE"
                    else self._voucher_kind(doc_id, entry.tx_amount)
                )
                entry.status = "LEGACY" if legacy else "PENDING"
                counts["doc"] += 1
            elif category == "MISC_INCOME":
                entry.voucher_kind = "MISC_INCOME"
                entry.status = "LEGACY" if legacy else "PENDING"
                counts["doc"] += 1
            elif category == "SALARY":
                entry.voucher_kind = "SALARY"
                entry.status = "LEGACY" if legacy else "PENDING"
                counts["doc"] += 1
            elif yak_no:
                # 국민 약식 개별 입금 — Memo 없이 적요의 400번호로 처리
                entry.doc_id = yak_no
                entry.voucher_kind = "YAK"
                entry.status = "LEGACY" if legacy else "PENDING"
                counts["doc"] += 1
            elif branch_from_memo(entry.memo):
                # 지사 입금 — Memo의 지사명으로 본지점 전표 대상
                entry.doc_id = jeokyo_token(entry.jeokyo)[:30] or None
                entry.voucher_kind = "BRANCH"
                entry.status = "LEGACY" if legacy else "PENDING"
                counts["doc"] += 1
            else:
                entry.status = "EXCLUDED"
                entry.reason = reason_of[category]
                counts["excluded"] += 1
            self.db.add(entry)
            known[unique_field] = entry
            counts["new"] += 1
        self.db.commit()
        return counts

    def _voucher_kind(self, doc_id: str, tx_amount: Decimal) -> str:
        """반제 판정 — 입금액과 같은 금액의 외상매출금 차변이 있을 때만.

        외상매출금이 있어도 금액이 다르면 이 입금과 무관한 별도 청구다
        (실측 01-2607-A-0104: 외상매출금 6,117,100 존재하나 입금 4,961,000은
        재무팀이 일반 입금전표로 처리). 금액까지 같아야 반제로 본다.
        """
        billed = self.db.scalar(
            select(VoucherCache.id).where(
                VoucherCache.management_no == doc_id,
                VoucherCache.account_code == "1080000",
                VoucherCache.debit_credit == "3",
                VoucherCache.amount == tx_amount,
            ).limit(1)
        )
        return "BANJE" if billed else "GENERAL"

    # ── 2단계: PENDING 건 전표 전송 ────────────────────────────────
    def send_pending(
        self, *, limit: int = 50, include_yak: bool = False
    ) -> "dict[str, int]":
        rows = list(
            self.db.scalars(
                select(DepositOutbox)
                .where(DepositOutbox.status == "PENDING")
                # 아직 시도 안 한 건(reason 없음)을 먼저 집는다 — "수기 전표 있음"
                # 같은 영구 보류성 건이 limit 창을 다 차지하면 신규가 시도조차
                # 못 한다(2026-08-11 실증: PENDING 86건 > limit 50, 4일 굶음).
                .order_by(
                    case((DepositOutbox.reason.is_(None), 0), else_=1),
                    DepositOutbox.id,
                )
                .limit(limit)
            )
        )
        counts = {"sent": 0, "held": 0, "failed": 0, "yak_deferred": 0}
        yaks = [entry for entry in rows if entry.voucher_kind == "YAK"]
        branches = [entry for entry in rows if entry.voucher_kind == "BRANCH"]
        salaries = [entry for entry in rows if entry.voucher_kind == "SALARY"]
        banjes: "list[tuple[DepositOutbox, dict[str, Any]]]" = []
        for entry in rows:
            if entry.voucher_kind in ("YAK", "BRANCH", "SALARY"):
                continue
            hold = self._collect_or_send(entry, banjes)
            if hold == "COLLECTED":
                self.db.commit()
                continue
            if hold is None:
                counts["sent" if entry.status == "S" else "failed"] += 1
            else:
                entry.reason = hold
                counts["held"] += 1
            self.db.commit()
        if banjes:
            # 반제는 회차마다 그날치를 전표 1장으로 묶는다(재무팀 정산 전표 관행)
            self._send_banje_bundles(banjes, counts)
        if not include_yak:
            # 약식·지사는 하루 1장 유지 — --include-yak 회차(17시 예약)에서만 묶는다
            counts["yak_deferred"] = len(yaks) + len(branches) + len(salaries)
        else:
            # 지사 접수 400(BANK_KB_MASTER OfficeID≠10)은 약식 매출이 아니라
            # 본지점 대상이다 — 400579347·400577516 재무팀 실처리(제주지사) 실측.
            moved = {
                entry.id for entry in yaks
                if (office := self._kb_office(entry.doc_id or "")) and office != "10"
            }
            branches += [entry for entry in yaks if entry.id in moved]
            yaks = [entry for entry in yaks if entry.id not in moved]
            if yaks:
                self._send_yak_bundles(yaks, counts)
            if branches:
                self._send_branch_bundles(branches, counts)
            if salaries:
                self._send_branch_bundles(salaries, counts)
        return counts

    def _collect_or_send(
        self,
        entry: DepositOutbox,
        banjes: "list[tuple[DepositOutbox, dict[str, Any]]]",
    ) -> "str | None":
        """공통 검증 후 반제는 묶음 후보로 모으고("COLLECTED"), 일반은 바로 보낸다."""
        doc_id = entry.doc_id or ""
        if entry.voucher_kind != "MISC_INCOME" and not doc_id.startswith("01-"):
            return "본사(01-) 외 감정서 — 수기 확인 필요"
        account = self.db.scalar(
            select(BankAccountMap).where(
                BankAccountMap.bank_cd == entry.bank_cd,
                BankAccountMap.acct_no == entry.acct_no,
                BankAccountMap.active == "Y",
            )
        )
        if not account:
            return f"계좌 매핑 없음({entry.bank_cd}/{entry.acct_no})"
        if entry.tx_amount <= 0:
            return "입금액이 0 이하"
        if entry.voucher_kind == "MISC_INCOME":
            return self._send_misc_income(entry, account)
        already = self._already_recorded(doc_id, entry.tx_amount)
        if already:
            return already
        if entry.voucher_kind == "ADVANCE":
            return self._send_advance(entry, account)
        # 재계산: 그 사이 외상매출금 전표가 생겼을 수 있다
        entry.voucher_kind = self._voucher_kind(doc_id, entry.tx_amount)
        if entry.voucher_kind == "BANJE":
            receivable = self._receivable_partner(doc_id, entry.tx_amount)
            if not receivable:
                return "외상매출금 전표의 거래처를 찾지 못함"
            banjes.append(
                (entry, {
                    "doc_id": doc_id, "tx_amount": entry.tx_amount,
                    "account_partner": account.partner_code,
                    "receivable_partner": receivable,
                    "customer_name": self._customer_name(doc_id),
                })
            )
            return "COLLECTED"
        return self._send_general(entry, account)

    def _send_banje_bundles(
        self,
        collected: "list[tuple[DepositOutbox, dict[str, Any]]]",
        counts: "dict[str, int]",
    ) -> None:
        """반제는 같은 날 입금을 전표 1장으로 묶는다 — 계좌가 달라도 한 전표
        (재무팀 정산 전표 실측: 국민신탁·우리종로3가 혼재)."""
        groups: "dict[tuple, list[tuple[DepositOutbox, dict[str, Any]]]]" = {}
        for entry, item in collected:
            org = self._organization(item["doc_id"])
            groups.setdefault((entry.tx_day, org), []).append((entry, item))
        for (tx_day, (company_code, division_code)), group in sorted(
            groups.items()
        ):
            first = group[0][0]
            menu_sq = _MENU_SQ_BASE + (int(first.id) % _MENU_SQ_SPAN)
            lines = banje_bundle_lines(
                items=[item for _, item in group],
                voucher_date=tx_day, menu_sq=menu_sq,
                division_code=division_code,
            )
            self._send_group(group, company_code, menu_sq, lines, counts)
            self.db.commit()

    def _send_yak_bundles(
        self, entries: "list[DepositOutbox]", counts: "dict[str, int]"
    ) -> None:
        """약식(400)은 같은 날·같은 계좌 입금을 전표 1장으로 묶는다(재무팀 관행).

        구성건 하나가 보류돼도 나머지는 진행한다 — 각 입금이 독립 건이라
        묶음 전체를 막을 이유가 없다.
        """
        groups: "dict[tuple, list[DepositOutbox]]" = {}
        for entry in entries:
            groups.setdefault(
                (entry.tx_day, entry.bank_cd, entry.acct_no), []
            ).append(entry)
        for (tx_day, bank_cd, acct_no), group in sorted(groups.items()):
            account = self.db.scalar(
                select(BankAccountMap).where(
                    BankAccountMap.bank_cd == bank_cd,
                    BankAccountMap.acct_no == acct_no,
                    BankAccountMap.active == "Y",
                )
            )
            resolved: "list[tuple[DepositOutbox, dict[str, Any]]]" = []
            org: "tuple[str, str] | None" = None
            for entry in group:
                if not account:
                    entry.reason = f"계좌 매핑 없음({bank_cd}/{acct_no})"
                    counts["held"] += 1
                    continue
                item = self._resolve_yak(entry)
                if isinstance(item, str):
                    entry.reason = item
                    counts["held"] += 1
                    continue
                if org is None:
                    org = (item.pop("company_code"), item.pop("division_code"))
                elif (item["company_code"], item["division_code"]) != org:
                    # 회계단위가 다르면 같은 전표에 못 담는다 — 다음 회차로 보류
                    entry.reason = "회계단위가 묶음과 달라 보류(단독 회차 필요)"
                    counts["held"] += 1
                    continue
                else:
                    item.pop("company_code"), item.pop("division_code")
                # 묶음전표라도 세무구분은 건별이다 — 한 전표에 현금영수증 건과
                # 세금계산서 건이 섞여 들어온다.
                item["cash_receipt"] = has_cash_receipt(self.db, item["yak_no"])
                resolved.append((entry, item))
            self.db.commit()
            if not resolved or org is None:
                continue
            company_code, division_code = org
            first = resolved[0][0]
            try:
                append_target = self._yak_append_target(
                    tx_day, company_code, division_code
                )
            except Exception as exc:  # 조회 실패 때 새 전표 생성은 중복 위험
                reason = f"기존 약식전표 조회 실패 — 다음 회차 재시도: {exc}"[:200]
                for entry, _ in resolved:
                    entry.reason = reason
                    counts["held"] += 1
                self.db.commit()
                continue
            if append_target:
                menu_sq, start_line_sq = append_target
            else:
                menu_sq = _MENU_SQ_BASE + (int(first.id) % _MENU_SQ_SPAN)
                start_line_sq = 1
            total = sum((entry.tx_amount for entry, _ in resolved), Decimal(0))
            lines = yak_bundle_lines(
                items=[item for _, item in resolved], total=total,
                voucher_date=tx_day, menu_sq=menu_sq,
                division_code=division_code,
                account_partner=account.partner_code,
                start_line_sq=start_line_sq,
            )
            self._send_bundle(resolved, company_code, menu_sq, lines, counts)
            self.db.commit()

    def _yak_append_target(
        self, tx_day: date, company_code: str, division_code: str
    ) -> "tuple[int, int] | None":
        """당일 MOA 약식 미발행 전표의 (작성번호, 다음 라인번호).

        최초 회차는 차변 합계 1줄과 건별 대변을 만들고, 추가 회차는 다음 줄에
        새 입금 합계 차변 1줄과 새 건별 대변을 붙인다. 따라서 한 전표 안에서
        회차별로도, 전체로도 차대가 항상 일치한다.
        """
        sent = self.db.scalars(
            select(DepositOutbox).where(
                DepositOutbox.tx_day == tx_day,
                DepositOutbox.status == "S",
                DepositOutbox.menu_sq.isnot(None),
                DepositOutbox.request_body.isnot(None),
            )
        ).all()
        candidates: "set[int]" = set()
        for entry in sent:
            try:
                body = json.loads(entry.request_body or "{}")
            except (TypeError, ValueError):
                continue
            lines = body.get("data") if isinstance(body, dict) else None
            if not isinstance(lines, list):
                continue
            if any(
                isinstance(line, dict)
                and str(line.get("docuTy") or "") == "3"
                and str(line.get("inDivCd") or "") == division_code
                and str(line.get("acctCd") or "") == "4010002"
                and str(line.get("isuDoc") or "").startswith("약식입금")
                for line in lines
            ):
                candidates.add(int(entry.menu_sq))
        if not candidates:
            return None

        day = tx_day.strftime("%Y%m%d")
        line_numbers: "dict[int, list[int]]" = {menu: [] for menu in candidates}
        for page in range(1, 200):
            payload = self.client.post(
                "/apiproxy/api11A16",
                json_body={
                    "coCd": company_code,
                    "groupSeq": get_settings().a10_group_seq,
                    "divCd": division_code,
                    "frDt": day,
                    "toDt": day,
                    "docuFg": "0",
                    "viewPage": page,
                    "viewCount": 500,
                },
                timeout=60.0,
            )
            rows = _api_rows(payload)
            for row in rows:
                try:
                    menu_sq = int(row.get("menuSq"))
                    line_sq = int(row.get("menuLnSq"))
                    issued_sq = int(row.get("isuSq") or 0)
                except (TypeError, ValueError):
                    continue
                if (
                    menu_sq in candidates
                    and str(row.get("menuDt") or "") == day
                    and str(row.get("docuTy") or "") == "3"
                    and issued_sq == 0
                ):
                    line_numbers[menu_sq].append(line_sq)
            if len(rows) < 500:
                break

        available = {
            menu: max(numbers) for menu, numbers in line_numbers.items() if numbers
        }
        if not available:
            return None
        menu_sq = max(available, key=lambda menu: (available[menu], menu))
        return menu_sq, available[menu_sq] + 1

    def _yak_duplicate_reason(
        self, entry: DepositOutbox, supply: Decimal
    ) -> "str | None":
        """같은 개별 입금 또는 같은 날·금액의 수기 전표만 중복이다.

        2026-08-25 실측: 400579202 등은 7/30에 2,000원(발급수수료류) 전표가 먼저 있고 오늘 52,800원 본수수료가 들어왔다.
        번호만 보고 막으면 본수수료 전표가 영영 안 나간다. 배치 이력은 CB2의
        개별 거래(outbox_id), 수기 전표는 거래일·공급가까지 같아야 중복으로 본다.
        """
        yak_no = entry.doc_id or ""
        duplicated = self.db.scalar(
            select(KbYakItem.id)
            .where(KbYakItem.outbox_id == entry.id)
            .limit(1)
        )
        if duplicated:
            return "이미 배치가 전표화한 400번호"
        manual = self.db.scalar(
            select(VoucherCache.id)
            .where(
                VoucherCache.management_no == yak_no,
                VoucherCache.account_code == "4010002",
                VoucherCache.debit_credit == "4",
                VoucherCache.amount == supply,
                VoucherCache.voucher_date == entry.tx_day,
            )
            .limit(1)
        )
        if manual:
            return "이미 전표 있음(수기 처리 추정) — 관리번호로 확인"
        return None

    def _resolve_yak(self, entry: DepositOutbox) -> "dict[str, Any] | str":
        """약식 구성건 검증 — 통과하면 item dict, 보류면 사유 문자열."""
        yak_no = entry.doc_id or ""
        if entry.tx_amount <= 0:
            return "입금액이 0 이하"
        if entry.tx_amount % 11 != 0:
            return "약식 입금액이 공급가+부가세(1.1배)로 나눠지지 않음"
        vat = (entry.tx_amount / 11).quantize(Decimal("1"))
        supply = entry.tx_amount - vat
        duplicate = self._yak_duplicate_reason(entry, supply)
        if duplicate:
            return duplicate
        ts = self.db.execute(
            text(
                f"SELECT TOP 1 CustName, Office "
                f"FROM [{get_settings().mssql_source_db}].dbo.APW_TS_Master "
                "WHERE LTRIM(HFDocid) = :h ORDER BY TS_SEQ DESC"
            ),
            {"h": yak_no},
        ).mappings().first()
        branch_name = str(ts["CustName"] or "").strip() if ts else ""
        office = str(ts["Office"] or "") if ts else ""
        kb_branch = self._kb_branch(yak_no) if not branch_name else None
        if kb_branch is not None:
            branch_name = kb_branch.branch_name
        if not branch_name:
            return "약식 지점을 찾지 못함(TS_Master·KB 지점코드 모두 없음)"
        company_code, division_code = self._default._organization(office)
        branch = (
            kb_branch.partner_code
            if kb_branch is not None and kb_branch.partner_code
            else self._branch_partner(company_code, branch_name)
        )
        if not branch:
            # 아마란스에 지점 거래처가 없으면 기타-본사로 보낸다(사용자 확정
            # 2026-08-13) — 지점명은 은행구분·약식 원장(branch_name)에 남는다.
            branch = _MISC_PARTNER_CD
        return {
            "yak_no": yak_no, "supply": supply, "vat": vat,
            "partner_code": branch, "branch_name": branch_name,
            "company_code": company_code, "division_code": division_code,
        }

    def _send_branch_bundles(
        self, entries: "list[DepositOutbox]", counts: "dict[str, int]"
    ) -> None:
        """지사 입금은 그날치를 본지점 전표 1장으로 묶는다 — 계좌·은행이 섞여도
        한 전표(수기 00086 실측: 국민남부+신한역삼 혼재). 회계단위는 본사.

        같은 날짜에 MOA가 만든 미발행 본지점 전표가 이미 있으면 api11A16으로
        실제 마지막 라인번호를 확인하고 그 다음 번호부터 이어 붙인다. 이미
        발행됐거나 아마란스에서 삭제된 전표에는 손대지 않고 새 전표를 만든다.
        조회 자체가 실패하면 별도 전표를 만들어 버리지 않고 보류한다.
        """
        groups: "dict[date, list[DepositOutbox]]" = {}
        for entry in entries:
            groups.setdefault(entry.tx_day, []).append(entry)
        company_code, division_code = self._default._organization("10")
        salary_bundle = all(entry.voucher_kind == "SALARY" for entry in entries)
        seen_yak: "set[str]" = set()  # 취소·재입금으로 같은 400이 두 번 온 회차 대비
        for tx_day, group in sorted(groups.items()):
            resolved: "list[tuple[DepositOutbox, dict[str, Any]]]" = []
            for entry in group:
                item = self._resolve_branch(entry)
                if isinstance(item, str):
                    entry.reason = item
                    counts["held"] += 1
                    continue
                if item.get("yak_no") and item["yak_no"] in seen_yak:
                    entry.reason = "같은 400번호가 이번 회차에 중복 — 수기 확인 필요"
                    counts["held"] += 1
                    continue
                if item.get("yak_no"):
                    seen_yak.add(item["yak_no"])
                resolved.append((entry, item))
            self.db.commit()
            if not resolved:
                continue
            first = resolved[0][0]
            try:
                # 급여입금은 지사수수료 전표와 제목·성격이 달라 별도 전표로 만든다.
                append_target = None if salary_bundle else self._branch_append_target(
                    tx_day, company_code, division_code
                )
            except Exception as exc:  # 조회 실패 때 새 전표 생성은 중복 위험
                reason = f"기존 지사전표 조회 실패 — 다음 회차 재시도: {exc}"[:200]
                for entry, _ in resolved:
                    entry.reason = reason
                    counts["held"] += 1
                self.db.commit()
                continue
            if append_target:
                menu_sq, start_line_sq = append_target
            else:
                menu_sq = _MENU_SQ_BASE + (int(first.id) % _MENU_SQ_SPAN)
                start_line_sq = 1
            lines = branch_bundle_lines(
                items=[item for _, item in resolved],
                voucher_date=tx_day, menu_sq=menu_sq,
                division_code=division_code, start_line_sq=start_line_sq,
                isu_doc="지사급여입금" if salary_bundle else "지사수수료 입금",
            )
            self._send_group(resolved, company_code, menu_sq, lines, counts)
            for entry, item in resolved:
                if entry.status != "S" or not item.get("yak_no"):
                    continue
                # 지사 접수 400도 약식 원장에 남긴다 — 같은 번호의 재전표화 차단.
                # 본지점 건은 공급가/부가세 분해가 없어 전액/0으로 기록한다.
                self.db.add(
                    KbYakItem(
                        yak_no=item["yak_no"], outbox_id=entry.id,
                        tx_day=entry.tx_day, supply=item["amount"],
                        vat=Decimal(0), branch_name=item["branch_name"],
                        partner_code=item["account_partner"], menu_sq=menu_sq,
                        status="S",
                    )
                )
            self.db.commit()

    def _branch_append_target(
        self, tx_day: date, company_code: str, division_code: str
    ) -> "tuple[int, int] | None":
        """당일 MOA 본지점 미발행 전표의 (작성번호, 다음 라인번호).

        로컬 성공 이력으로 우리 전표의 menuSq 후보를 먼저 제한하고, api11A16의
        미발행 결과에 실제로 남아 있는 라인만 신뢰한다. 따라서 다른 시스템의
        본지점 전표에 붙거나 이미 발행된 전표를 수정하지 않는다.
        """
        sent = self.db.scalars(
            select(DepositOutbox).where(
                DepositOutbox.tx_day == tx_day,
                DepositOutbox.status == "S",
                DepositOutbox.menu_sq.isnot(None),
                DepositOutbox.request_body.isnot(None),
            )
        ).all()
        candidates: "set[int]" = set()
        for entry in sent:
            try:
                body = json.loads(entry.request_body or "{}")
            except (TypeError, ValueError):
                continue
            lines = body.get("data") if isinstance(body, dict) else None
            if not isinstance(lines, list):
                continue
            if any(
                isinstance(line, dict)
                and str(line.get("docuTy") or "") == DOCU_TY_BRANCH
                and str(line.get("inDivCd") or "") == division_code
                for line in lines
            ):
                candidates.add(int(entry.menu_sq))
        if not candidates:
            return None

        day = tx_day.strftime("%Y%m%d")
        line_numbers: "dict[int, list[int]]" = {menu: [] for menu in candidates}
        for page in range(1, 200):
            payload = self.client.post(
                "/apiproxy/api11A16",
                json_body={
                    "coCd": company_code,
                    "groupSeq": get_settings().a10_group_seq,
                    "divCd": division_code,
                    "frDt": day,
                    "toDt": day,
                    "docuFg": "0",
                    "viewPage": page,
                    "viewCount": 500,
                },
                timeout=60.0,
            )
            rows = _api_rows(payload)
            for row in rows:
                try:
                    menu_sq = int(row.get("menuSq"))
                    line_sq = int(row.get("menuLnSq"))
                    issued_sq = int(row.get("isuSq") or 0)
                except (TypeError, ValueError):
                    continue
                if (
                    menu_sq in candidates
                    and str(row.get("menuDt") or "") == day
                    and str(row.get("docuTy") or "") == DOCU_TY_BRANCH
                    and issued_sq == 0
                ):
                    line_numbers[menu_sq].append(line_sq)
            if len(rows) < 500:
                break

        available = {
            menu: max(numbers) for menu, numbers in line_numbers.items() if numbers
        }
        if not available:
            return None
        menu_sq = max(available, key=lambda menu: (available[menu], menu))
        return menu_sq, available[menu_sq] + 1

    def _resolve_branch(self, entry: DepositOutbox) -> "dict[str, Any] | str":
        """본지점 구성건 검증 — 통과하면 item dict, 보류면 사유 문자열.

        지사 확정은 ① Memo 지사명(1410 계정명과 정확 일치) ② 400번호의
        BANK_KB_MASTER OfficeID 순. 둘 다 없으면 보류(fail-closed).
        """
        if entry.tx_amount <= 0:
            return "입금액이 0 이하"
        account = self.db.scalar(
            select(BankAccountMap).where(
                BankAccountMap.bank_cd == entry.bank_cd,
                BankAccountMap.acct_no == entry.acct_no,
                BankAccountMap.active == "Y",
            )
        )
        if not account:
            return f"계좌 매핑 없음({entry.bank_cd}/{entry.acct_no})"
        yak_no = (
            entry.doc_id if entry.voucher_kind == "YAK"
            else yak_no_from_jeokyo(entry.jeokyo)
        )
        salary = entry.voucher_kind == "SALARY"
        name = (
            branch_salary_name(entry.memo, entry.jeokyo) if salary
            else branch_from_memo(entry.memo)
        )
        if not name and yak_no:
            name = OFFICE_BRANCH_NAME.get(self._kb_office(yak_no) or "")
        if not name:
            return "지사를 확정하지 못함(Memo 지사명·KB 접수 OfficeID 모두 없음)"
        token = "지사급여입금" if salary else (
            jeokyo_token(entry.jeokyo) or (yak_no or "")
        )
        if not token:
            return "적요에서 접수번호를 찾지 못함"
        if yak_no:
            duplicated = self.db.scalar(
                select(KbYakItem.id).where(KbYakItem.outbox_id == entry.id).limit(1)
            )
            if duplicated:
                return "이미 배치가 전표화한 400번호"
        manual_query = select(VoucherCache.id).where(
            VoucherCache.account_code == BRANCH_ACCOUNTS[name],
            VoucherCache.debit_credit == "4",
        )
        if salary:
            manual_query = manual_query.where(
                VoucherCache.voucher_date == entry.tx_day,
                VoucherCache.amount == entry.tx_amount,
                func.replace(VoucherCache.remark, " ", "").like("%지사급여입금%"),
            )
        else:
            manual_query = manual_query.where(
                VoucherCache.voucher_date == entry.tx_day,
                VoucherCache.amount == entry.tx_amount,
                VoucherCache.remark.like(f"%{token}%"),
            )
        manual = self.db.scalar(manual_query.limit(1))
        if manual:
            return "이미 본지점 전표 있음(수기 처리 추정) — 적요로 확인"
        return {
            "token": token, "amount": entry.tx_amount,
            "account_partner": account.partner_code,
            "branch_account": BRANCH_ACCOUNTS[name], "branch_name": name,
            "yak_no": yak_no,
        }

    def _kb_office(self, yak_no: str) -> "str | None":
        """400번호 → BANK_KB_MASTER.OfficeID ('10'=본사, 그 외=지사 접수).

        한 번호에 행이 2개(WorkResult 3·6)지만 OfficeID는 같다(실측). 행이
        없으면 None — 약식 경로의 기존 지점 검증(TS_Master)이 보류로 잡는다.
        """
        if not yak_no:
            return None
        office = self.db.execute(
            text(
                f"SELECT TOP 1 OfficeID "
                f"FROM [{get_settings().mssql_source_db}].dbo.BANK_KB_MASTER "
                "WHERE LTRIM(RequestNM) = :h ORDER BY MasterID DESC"
            ),
            {"h": yak_no},
        ).scalar()
        value = str(office or "").strip()
        return value or None

    def _send_bundle(
        self,
        resolved: "list[tuple[DepositOutbox, dict[str, Any]]]",
        company_code: str,
        menu_sq: int,
        lines: "list[dict[str, Any]]",
        counts: "dict[str, int]",
    ) -> None:
        """약식 묶음 전송 — 성공하면 구성건 원장(KbYakItem)도 함께 남긴다."""
        self._send_group(resolved, company_code, menu_sq, lines, counts)
        for entry, item in resolved:
            if entry.status != "S":
                continue
            self.db.add(
                KbYakItem(
                    yak_no=item["yak_no"], outbox_id=entry.id,
                    tx_day=entry.tx_day, supply=item["supply"],
                    vat=item["vat"], branch_name=item["branch_name"],
                    partner_code=item["partner_code"], menu_sq=menu_sq,
                    status="S",
                )
            )

    def _send_group(
        self,
        group: "list[tuple[DepositOutbox, dict[str, Any]]]",
        company_code: str,
        menu_sq: int,
        lines: "list[dict[str, Any]]",
        counts: "dict[str, int]",
    ) -> None:
        """묶음 전표 1건 전송 — 그룹의 모든 outbox 행에 같은 결과를 기록한다."""
        body = {"coCd": company_code, "data": lines}
        body_json = json.dumps(body, ensure_ascii=False, default=str)
        now = datetime.now()
        for entry, _ in group:
            entry.menu_sq = menu_sq
            entry.request_body = body_json
            entry.sent_at = now
        try:
            response = self.client.post("/apiproxy/api11A10", json_body=body)
        except Exception as exc:  # noqa: BLE001 - 전송 실패는 기록하고 계속
            for entry, _ in group:
                entry.status = "F"
                entry.error_msg = str(exc)[:500]
                counts["failed"] += 1
            return
        response_json = json.dumps(response, ensure_ascii=False, default=str)
        for entry, _ in group:
            entry.response_body = response_json
            entry.status = "S"
            entry.reason = None
            counts["sent"] += 1

    def _already_recorded(self, doc_id: str, tx_amount: Decimal) -> "str | None":
        """이 입금이 이미 아마란스에 반영돼 있으면 보류 사유를 돌려준다(fail-closed).

        재무팀이 수기로 먼저 처리한 입금을 배치가 또 전표화하는 이중계상 방지:
        ① 같은 감정서에 같은 금액의 외상매출금 대변(반제)이 이미 있음
        ② 같은 전표 안에 이 감정서 라인과 같은 금액의 보통예금 차변이 함께
           있음 — 직접입금 전표 (실측: 01-2607-3-2258 수기 보통예금 전환 건)
        캐시(10분 주기) 기준이라 방금 발행된 전표까지는 못 본다 — 수기 처리
        직후라면 다음 회차에서 걸러진다.
        """
        if not doc_id:
            return None
        settled = self.db.scalar(
            select(VoucherCache.id)
            .where(
                VoucherCache.management_no == doc_id,
                VoucherCache.account_code == "1080000",
                VoucherCache.debit_credit == "4",
                VoucherCache.amount == tx_amount,
            )
            .limit(1)
        )
        if settled:
            return "이미 반제(외상매출금 대변) 전표 있음 — 수기 처리 추정"
        deposited = self.db.execute(
            text(
                """
                SELECT TOP 1 d.id
                FROM dbo.a10_voucher_cache d
                JOIN dbo.a10_voucher_cache s
                  ON s.voucher_date = d.voucher_date
                 AND s.voucher_no = d.voucher_no
                 AND s.division_code = d.division_code
                WHERE s.management_no = :doc
                  AND d.account_code = '1030000'
                  AND d.debit_credit = '3'
                  AND d.amount = :amount
                """
            ),
            {"doc": doc_id, "amount": tx_amount},
        ).first()
        if deposited:
            return "이미 입금(보통예금 차변) 전표 있음 — 수기 처리 추정"
        return None

    def _send_general(
        self, entry: DepositOutbox, account: BankAccountMap
    ) -> "str | None":
        """일반 입금전표 전송 — 공통 검증(_collect_or_send)은 끝난 상태로 온다."""
        doc_id = entry.doc_id or ""
        menu_sq = _MENU_SQ_BASE + (int(entry.id) % _MENU_SQ_SPAN)
        company_code, division_code = self._organization(doc_id)
        fee, vat = self._doc_amounts(doc_id)
        if fee is None:
            return "감정서(apw_masterex)를 찾지 못함"
        if fee + vat != entry.tx_amount:
            return (
                f"금액 불일치 — 입금 {entry.tx_amount:,.0f} ≠ "
                f"수수료합계 {fee:,.0f} + 부가세 {vat:,.0f}"
            )
        customer = self._customer_partner(company_code, doc_id)
        if not customer:
            return "아마란스 거래처 미확정(사업자번호 매칭 실패)"
        customer_name = self._customer_name(doc_id)
        lines = general_lines(
            doc_id=doc_id, fee=fee, vat=vat,
            voucher_date=entry.tx_day, menu_sq=menu_sq,
            division_code=division_code,
            account_partner=account.partner_code,
            customer_partner=customer,
            customer_name=customer_name,
            cash_receipt=has_cash_receipt(self.db, doc_id),
        )
        return self._send(entry, company_code, menu_sq, lines)

    def _send_advance(
        self, entry: DepositOutbox, account: BankAccountMap
    ) -> "str | None":
        """Memo의 감정서번호 뒤에 점이 붙은 선수금 수령 전표를 전송한다."""
        doc_id = entry.doc_id or ""
        menu_sq = _MENU_SQ_BASE + (int(entry.id) % _MENU_SQ_SPAN)
        company_code, division_code = self._organization(doc_id)
        lines = advance_lines(
            doc_id=doc_id,
            amount=entry.tx_amount,
            voucher_date=entry.tx_day,
            menu_sq=menu_sq,
            division_code=division_code,
            account_partner=account.partner_code,
            customer_partner=_ADVANCE_PARTNER_CD,
            customer_name=self._customer_name(doc_id),
        )
        return self._send(entry, company_code, menu_sq, lines)

    def _send_misc_income(
        self, entry: DepositOutbox, account: BankAccountMap
    ) -> "str | None":
        """Memo가 정확히 '잡이익'인 본사 입금의 일반전표를 전송한다."""
        duplicate = self.db.execute(
            text(
                """
                SELECT TOP 1 b.id
                FROM dbo.a10_voucher_cache b
                JOIN dbo.a10_voucher_cache m
                  ON m.voucher_date = b.voucher_date
                 AND m.division_code = b.division_code
                 AND m.voucher_no = b.voucher_no
                WHERE b.voucher_date = :day
                  AND b.account_code = '1030000' AND b.debit_credit = '3'
                  AND b.partner_code = :partner AND b.amount = :amount
                  AND m.account_code = '9300000' AND m.debit_credit = '4'
                  AND m.amount = :amount
                """
            ),
            {"day": entry.tx_day, "partner": account.partner_code,
             "amount": entry.tx_amount},
        ).first()
        if duplicate:
            return "이미 보통예금/잡이익 전표 있음 — 수기 처리 추정"
        menu_sq = _MENU_SQ_BASE + (int(entry.id) % _MENU_SQ_SPAN)
        company_code, division_code = self._default._organization("10")
        lines = misc_income_lines(
            amount=entry.tx_amount,
            voucher_date=entry.tx_day,
            menu_sq=menu_sq,
            division_code=division_code,
            account_partner=account.partner_code,
        )
        return self._send(entry, company_code, menu_sq, lines)

    def _send(
        self,
        entry: DepositOutbox,
        company_code: str,
        menu_sq: int,
        lines: "list[dict[str, Any]]",
    ) -> None:
        body = {"coCd": company_code, "data": lines}
        entry.menu_sq = menu_sq
        entry.request_body = json.dumps(body, ensure_ascii=False, default=str)
        entry.sent_at = datetime.now()
        try:
            response = self.client.post("/apiproxy/api11A10", json_body=body)
            entry.response_body = json.dumps(response, ensure_ascii=False, default=str)
            entry.status = "S"
            entry.reason = None
        except Exception as exc:  # 전송 실패는 기록하고 다음 건으로
            entry.status = "F"
            entry.error_msg = str(exc)[:2000]
        return None

    def _kb_branch(self, yak_no: str) -> "KbBranchMap | None":
        """400번호 → BANK_KB_REQUEST_MASTER의 KB 지점코드 → 매핑 테이블."""
        kb_code = self.db.execute(
            text(
                f"SELECT TOP 1 KB_Code "
                f"FROM [{get_settings().mssql_source_db}].dbo.BANK_KB_REQUEST_MASTER "
                "WHERE LTRIM(RequestNm) = :h ORDER BY SEQ DESC"
            ),
            {"h": yak_no},
        ).scalar()
        code = str(kb_code or "").strip()
        if not code:
            return None
        return self.db.scalar(
            select(KbBranchMap).where(
                KbBranchMap.kb_code == code, KbBranchMap.active == "Y"
            )
        )

    def _branch_partner(self, company_code: str, branch_name: str) -> "str | None":
        """'국민은행 동백' → 아마란스 '국민은행동백지점' 거래처 매칭.

        아마란스 등록명은 띄어쓰기가 제각각이라 공백을 지우고 비교한다.
        미사용(useYn='0') 거래처는 조회 단계에서 뺀다 — 같은 지점이 중복
        등록돼 있고 한쪽이 폐지된 경우가 있다(국민은행동백지점 실측).
        그래도 둘 이상이면 과거 약식 전표(4010002)에서 실제 쓰인 코드를
        고르고, 이력이 없으면 사업자번호 있는 쪽을 택한다.
        """
        def normalize(value: str) -> str:
            # 아마란스 등록명의 법인 접두사('(주) 국민은행 시흥능곡지점' 실측)를
            # 벗겨야 지점명 앞부분 일치 비교가 된다.
            flat = value.replace(" ", "")
            for prefix in ("(주)", "(주식회사)", "주식회사", "㈜"):
                if flat.startswith(prefix):
                    flat = flat[len(prefix):]
            return flat

        name = branch_name.strip()
        if not name:
            return None
        key = normalize(name)
        rows: list[dict[str, Any]] = []
        for term in dict.fromkeys([name, key]):
            payload = self.client.post(
                "/apiproxy/api16S11",
                json_body={
                    "coCd": company_code, "trNm": term, "useYn": "1",
                    "usePagination": True, "pagingOffset": 0, "pagingCount": 30,
                },
            )
            data = payload.get("resultData") or []
            if isinstance(data, dict):
                data = data.get("datas") or data.get("data") or []
            rows.extend(data)
        candidates: dict[str, str] = {}
        for row in rows:
            code = str(row.get("trCd") or "").strip()
            trnm = str(row.get("trNm") or "").strip()
            if code and normalize(trnm).startswith(key):
                candidates[code] = "".join(
                    ch for ch in str(row.get("regNb") or "") if ch.isdigit()
                )
        if not candidates:
            return None
        if len(candidates) == 1:
            return next(iter(candidates))
        used = self.db.execute(
            select(VoucherCache.partner_code, func.count().label("n"))
            .where(
                VoucherCache.account_code == "4010002",
                VoucherCache.partner_code.in_(list(candidates)),
            )
            .group_by(VoucherCache.partner_code)
            .order_by(func.count().desc())
        ).first()
        if used:
            return str(used[0]).strip()
        with_reg = [code for code, reg in candidates.items() if reg]
        return with_reg[0] if len(with_reg) == 1 else None

    def _organization(self, doc_id: str) -> "tuple[str, str]":
        office = self.db.execute(
            text(
                f"SELECT TOP 1 Office FROM [{get_settings().mssql_source_db}].dbo.APW_Master "
                "WHERE DocID = :doc"
            ),
            {"doc": doc_id},
        ).scalar()
        return self._default._organization(str(office or ""))

    def _receivable_partner(self, doc_id: str, tx_amount: Decimal) -> "str | None":
        row = self.db.execute(
            select(VoucherCache.partner_code)
            .where(
                VoucherCache.management_no == doc_id,
                VoucherCache.account_code == "1080000",
                VoucherCache.debit_credit == "3",
                VoucherCache.amount == tx_amount,
                VoucherCache.partner_code.isnot(None),
            )
            .order_by(VoucherCache.voucher_date.desc())
            .limit(1)
        ).scalar()
        return str(row).strip() if row else None

    def _customer_name(self, doc_id: str) -> str:
        """은행구분 판정에 쓰는 의뢰처명(APW_Master.CustName)."""
        name = self.db.execute(
            text(
                f"SELECT TOP 1 CustName "
                f"FROM [{get_settings().mssql_source_db}].dbo.APW_Master "
                "WHERE DocID = :doc"
            ),
            {"doc": doc_id},
        ).scalar()
        return str(name or "").strip()

    def _doc_amounts(self, doc_id: str) -> "tuple[Decimal | None, Decimal]":
        row = self.db.execute(
            text(
                f"SELECT TOP 1 [수수료합계] AS fee, [부가가치세] AS vat "
                f"FROM [{get_settings().mssql_source_db}].dbo.apw_masterex "
                "WHERE DocID = :doc"
            ),
            {"doc": doc_id},
        ).mappings().first()
        if not row:
            return None, Decimal(0)
        fee = Decimal(str(row["fee"] or 0)).quantize(Decimal("1"))
        vat = Decimal(str(row["vat"] or 0)).quantize(Decimal("1"))
        return fee, vat

    def _customer_partner(self, company_code: str, doc_id: str) -> "str | None":
        """의뢰 거래처의 사업자번호로 아마란스 거래처를 유일 매칭한다.

        개인 고객(사업자번호 없음)은 재무팀 규칙대로 '기타-본사'로 보낸다.
        """
        digits = self.db.execute(
            text(
                f"""
                SELECT TOP 1 c.SNO
                FROM [{get_settings().mssql_source_db}].dbo.APW_Master m
                JOIN [{get_settings().mssql_source_db}].dbo.APW_Customer c
                  ON c.CustID = m.CustID AND c.Office = m.Office
                WHERE m.DocID = :doc
                ORDER BY c.Active DESC, c.SEQ DESC
                """
            ),
            {"doc": doc_id},
        ).scalar()
        reg_nb = "".join(ch for ch in str(digits or "") if ch.isdigit())
        if not reg_nb:
            return _MISC_PARTNER_CD
        payload = self.client.post(
            "/apiproxy/api16S11",
            json_body={"coCd": company_code, "regNb": reg_nb, "useYn": "1"},
        )
        data = payload.get("resultData") or []
        if isinstance(data, dict):
            data = data.get("datas") or data.get("data") or []
        codes = {str(row.get("trCd") or "").strip() for row in data if row.get("trCd")}
        return codes.pop() if len(codes) == 1 else None
