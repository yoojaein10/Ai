"""상여 계산 엔진 — 사람 한 명의 행 목록을 받아 엑셀 합계행을 만든다 (순수 함수, DB 없음).

주주 (엑셀 'NN월-주주' 합계행, 요율 블록마다 한 줄):
  Q(산출액) = ΣH − ΣK − ΣP − [사람 단위: 전월 가변비 J + 미납비이월 M + 당월감정서경비 O + 기타 N]
  상여 = Q<0 ? 0 : Q × 요율,  미납비용 AE = 상여가 0이면 Q(음수) → 다음 달 M
  Y = ROUNDDOWN(상여 + 처리비 V − 화환 W + 물건조사비 X, −3),  W 는 Q<0 이면 0
  소득세 = ROUNDDOWN(Y×30%, −3), 주민세 = ROUNDDOWN(소득세×10%, −1), 지급 = Y − 소득세 − 주민세 − 기타공제
  사람 단위 항목은 **산출액(Q_pre)이 가장 큰 블록에 한 번** 넣는다 (이영준 26.08 실측).

평·동 (엑셀 'NN월-평.동' 사람 합계행):
  행: I = 순수수료 + 토지조사비, J = ROUND(담보 1.5% | 그외 1%), L = I − J
  소속 상여 = 한계누진(L), 공통건 상여 = L × 행 요율(기본 3%)
  AD = ROUNDDOWN(Σ상여 + 처리수당 − 화환, −3) × 지급률, 소득세 = ROUNDDOWN(AD×율, −3), 지방세 10%
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.services.bonus.rules import (
    associate_doc_calc,
    card_limit,
    income_tax,
    progressive_bonus,
    resident_tax,
    rounddown,
    shareholder_doc_calc,
)

COMMON_DEFAULT_RATE = 3.0

# 공제 종류 → 어느 단계에서 빠지는가
Q_STAGE = {"VARIABLE_ADJ": "variable_cost", "UNPAID_CARRY": "carry_in", "DOC_EXPENSE": "doc_expense", "MISC": "misc"}
# 환입(+): 가변비 환입(김남수 26.08 J=−3,289,000) · 감정서경비 환입(송정선 26.03 O=−1,500,000)
Q_ADD = {"VARIABLE_CREDIT": "variable_credit", "EXPENSE_CREDIT": "expense_credit"}
Y_ADD = {"HANDLING": "handling"}
# 선지급은 엑셀 Y 수식에 손으로 뺀 값(=ROUNDDOWN(…)-20000000) — 세전 단계에서 뺀다
# OTHER_EXPENSE = 화환 시트의 그 밖의 비용(세금과공과·지급임차료·도서인쇄비·건강검진 …) — 엑셀 W 에 같이 합산된다
Y_SUB = {"WREATH": "wreath", "PENALTY": "wreath", "INSURANCE": "wreath", "OTHER_EXPENSE": "wreath", "ADVANCE_PAID": "advance_paid"}
AC_SUB = {"OTHER_DEDUCT": "other_deduct"}
DEDUCTION_KINDS = tuple(Q_STAGE) + tuple(Q_ADD) + tuple(Y_ADD) + tuple(Y_SUB) + tuple(AC_SUB)


@dataclass
class Row:
    doc_id: str
    person: str
    kind: str = "SHAREHOLDER"          # SHAREHOLDER | ASSOCIATE | COMMON
    work_type: str = ""
    fee: float = 0.0                   # 인별 순수수료 (지분 적용 후)
    land_fee: float = 0.0              # 토지조사비 (지분 적용 후)
    travel_fee: float = 0.0            # 부족출장비 (지분 적용 후, 양수)
    survey_fee: float = 0.0            # 물건조사비 (평가자 행에만)
    expense_fee: float = 0.0           # 당월감정서경비 자동값 (전표 귀속 안분)
    rate: "float | None" = None        # 주주 요율(%) / 공통건 요율(%)
    block_from: "date | None" = None   # 요율 블록 시작일 (같은 요율이라도 블록이 다르면 따로)
    customer_name: str = ""
    receipt_date: "date | None" = None
    share_pct: float = 100.0
    share_source: str = ""
    rate_source: str = ""
    flags: "tuple[str, ...]" = field(default_factory=tuple)
    signing: bool = False              # 서명료 지분(2.5%) — 손배·협회비를 내지 않는다 (주인이 전액 부담)
    min_bonus: float = 0.0             # 공통건 하한 (국공유재산·법원 300,000)


def _buckets(deductions: "list[dict[str, Any]] | tuple") -> "tuple[dict[str, float], list[str]]":
    """공제 목록을 단계별 합으로. 모르는 종류는 경고로 남기고 무시한다."""
    totals = {key: 0.0 for key in ("variable_cost", "variable_credit", "carry_in", "doc_expense", "expense_credit", "misc", "handling", "wreath", "advance_paid", "other_deduct")}
    warnings: "list[str]" = []
    for item in deductions or ():
        kind = str(item.get("kind") or "").upper()
        amount = float(item.get("amount") or 0)
        bucket = Q_STAGE.get(kind) or Q_ADD.get(kind) or Y_ADD.get(kind) or Y_SUB.get(kind) or AC_SUB.get(kind)
        if bucket is None:
            warnings.append(f"모르는 공제 종류를 무시했습니다: {kind or '(없음)'}")
            continue
        totals[bucket] += amount
    return totals, warnings


def _row_dict(row: Row, **calc: float) -> "dict[str, Any]":
    return {
        "doc_id": row.doc_id, "person": row.person, "kind": row.kind, "work_type": row.work_type,
        "customer_name": row.customer_name, "receipt_date": row.receipt_date,
        "fee": row.fee, "land_fee": row.land_fee, "travel_fee": row.travel_fee,
        "survey_fee": row.survey_fee, "expense_fee": row.expense_fee,
        "rate": row.rate, "block_from": row.block_from, "rate_source": row.rate_source,
        "share_pct": row.share_pct, "share_source": row.share_source, "flags": list(row.flags),
        **calc,
    }


def _shareholder_calc(row: Row) -> "dict[str, float]":
    calc = shareholder_doc_calc(row.work_type, row.fee, row.land_fee, row.travel_fee)
    if row.signing:                    # 서명료 행: H 만 받고 K·P 는 주인 행이 전액 낸다 (엑셀 26.08 r375)
        calc["indemnity"], calc["association_fee"] = 0.0, 0.0
    return calc


def _sum(rows: "list[dict[str, Any]]", key: str) -> float:
    return float(sum(float(row.get(key) or 0) for row in rows))


# ── 주주 ────────────────────────────────────────────────────────────────

def shareholder_person(
    rows: "list[Row]",
    *,
    variable_auto: float = 0.0,
    carry_in: float = 0.0,
    deductions: "list[dict[str, Any]] | tuple" = (),
) -> "dict[str, Any]":
    """주주 한 사람 — 요율 블록별 합계행과 사람 합계."""
    calc_rows = [_row_dict(row, **_shareholder_calc(row)) for row in rows]
    buckets, warnings = _buckets(deductions)
    variable_cost = float(variable_auto) + buckets["variable_cost"] - buckets["variable_credit"]
    carry = float(carry_in) + buckets["carry_in"]
    doc_expense = _sum(calc_rows, "expense_fee") + buckets["doc_expense"] - buckets["expense_credit"]
    misc = buckets["misc"]
    person_level = variable_cost + carry + doc_expense + misc

    grouped: "dict[tuple[float | None, date | None], list[dict[str, Any]]]" = {}
    for row in calc_rows:
        grouped.setdefault((row["rate"], row["block_from"]), []).append(row)
    if not grouped:
        grouped[(None, None)] = []
    pre = {
        key: sum(r["assessed"] - r["indemnity"] - r["association_fee"] for r in items)
        for key, items in grouped.items()
    }
    main_key = max(pre, key=lambda key: pre[key])

    blocks = []
    for key, items in grouped.items():
        rate, block_from = key
        is_main = key == main_key
        q = pre[key] - (person_level if is_main else 0.0)
        if rate is None and items:
            warnings.append(f"요율이 없는 행 {len(items)}건 — 상여를 계산하지 않았습니다 (요율 설정을 확인하세요).")
        bonus = 0.0 if (q < 0 or rate is None) else q * float(rate) / 100
        wreath = buckets["wreath"] if (is_main and q >= 0) else 0.0   # 엑셀 W = IF(Q<0, 0, …)
        handling = buckets["handling"] if is_main else 0.0
        advance = buckets["advance_paid"] if is_main else 0.0
        survey = _sum(items, "survey_fee")
        pretax = rounddown(bonus + handling - wreath + survey, -3) - advance
        tax = income_tax(pretax)
        resident = resident_tax(tax)
        other = buckets["other_deduct"] if is_main else 0.0
        blocks.append({
            "rate": rate, "block_from": block_from, "main": is_main, "count": len(items),
            "assessed": _sum(items, "assessed"), "indemnity": _sum(items, "indemnity"),
            "association_fee": _sum(items, "association_fee"),
            "q_pre": pre[key], "payout_base": q, "bonus": bonus,
            "handling": handling, "wreath": wreath, "advance_paid": advance, "survey_fee": survey,
            "pretax": pretax, "income_tax": tax, "resident_tax": resident,
            "other_deduct": other, "payment": pretax - tax - resident - other,
            "unpaid_carry_out": q if (bonus == 0 and q < 0) else 0.0,
            "card_limit": card_limit(items),
            "rows": items,
        })

    totals = {
        "count": len(calc_rows),
        "fee": _sum(calc_rows, "fee"), "land_fee": _sum(calc_rows, "land_fee"),
        "travel_fee": _sum(calc_rows, "travel_fee"), "assessed": _sum(calc_rows, "assessed"),
        "indemnity": _sum(calc_rows, "indemnity"), "association_fee": _sum(calc_rows, "association_fee"),
        "variable_cost": variable_cost, "variable_auto": float(variable_auto),
        "carry_in": carry, "doc_expense": doc_expense, "misc": misc,
        "payout_base": sum(b["payout_base"] for b in blocks),
        "bonus": sum(b["bonus"] for b in blocks),
        "handling": sum(b["handling"] for b in blocks), "wreath": sum(b["wreath"] for b in blocks),
        "advance_paid": sum(b["advance_paid"] for b in blocks),
        "survey_fee": _sum(calc_rows, "survey_fee"),
        "pretax": sum(b["pretax"] for b in blocks),
        "income_tax": sum(b["income_tax"] for b in blocks),
        "resident_tax": sum(b["resident_tax"] for b in blocks),
        "other_deduct": sum(b["other_deduct"] for b in blocks),
        "payment": sum(b["payment"] for b in blocks),
        "unpaid_carry_out": sum(b["unpaid_carry_out"] for b in blocks),
        "card_limit": sum(b["card_limit"] for b in blocks),
        # 상여가 0이라 못 뺀 화환류 — 마감 때 공제 대장에서 다시 대기로 돌린다
        "wreath_unapplied": buckets["wreath"] - sum(b["wreath"] for b in blocks),
    }
    return {"kind": "SHAREHOLDER", "rows": calc_rows, "blocks": blocks, "totals": totals, "warnings": warnings}


# ── 평·동 (소속평가사 · 공통건) ────────────────────────────────────────────

def _associate_row(row: Row) -> "dict[str, Any]":
    calc = associate_doc_calc(row.work_type, row.fee, row.land_fee, row.travel_fee)
    gross, indemnity = calc["assessed"], calc["indemnity"]     # I, J
    assessed = gross - indemnity                                # L
    if row.kind == "COMMON":
        rate = COMMON_DEFAULT_RATE if row.rate is None else float(row.rate)
        bonus = assessed * rate / 100
        if row.min_bonus and bonus < row.min_bonus:      # 국공유재산·법원 공통건 하한 300,000 (엑셀 정액)
            bonus = float(row.min_bonus)
    else:
        rate = None
        bonus = progressive_bonus(assessed)
    return _row_dict(row, gross=gross, indemnity=indemnity, assessed=assessed, bonus=bonus, applied_rate=rate)


def associate_person(
    rows: "list[Row]",
    *,
    pay_ratio: float = 1.0,
    tax_rate: float = 0.15,
    deductions: "list[dict[str, Any]] | tuple" = (),
) -> "dict[str, Any]":
    """소속평가사(또는 주주의 공통건 묶음) 한 사람 — 평·동 시트 사람 합계행."""
    calc_rows = [_associate_row(row) for row in rows]
    buckets, warnings = _buckets(deductions)
    bonus = _sum(calc_rows, "bonus") + _sum(calc_rows, "survey_fee")   # AA = SUM(M:Z)
    handling, wreath, other = buckets["handling"], buckets["wreath"], buckets["other_deduct"]
    advance = buckets["advance_paid"]
    pretax = float(Decimal(str(rounddown(bonus + handling - wreath, -3))) * Decimal(str(pay_ratio))) - advance
    tax = income_tax(pretax, tax_rate)
    resident = resident_tax(tax)
    gross = _sum(calc_rows, "gross")
    totals = {
        "count": len(calc_rows),
        "fee": _sum(calc_rows, "fee"), "land_fee": _sum(calc_rows, "land_fee"),
        "gross": gross, "indemnity": _sum(calc_rows, "indemnity"), "assessed": _sum(calc_rows, "assessed"),
        "survey_fee": _sum(calc_rows, "survey_fee"),
        "bonus": bonus, "handling": handling, "wreath": wreath, "advance_paid": advance,
        "pay_ratio": float(pay_ratio), "tax_rate": float(tax_rate),
        "pretax": pretax, "income_tax": tax, "resident_tax": resident,
        "other_deduct": other, "payment": pretax - tax - resident - other,
        "card_limit": rounddown(Decimal(str(gross)) * Decimal("0.05"), -3),
        "wreath_unapplied": 0.0,
        "common_count": sum(1 for row in calc_rows if row["kind"] == "COMMON"),
    }
    return {"kind": "ASSOCIATE", "rows": calc_rows, "totals": totals, "warnings": warnings}
