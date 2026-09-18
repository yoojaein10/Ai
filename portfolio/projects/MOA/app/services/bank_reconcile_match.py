"""일계표 대사 — 계좌 × 일자 한 묶음의 은행 거래와 보통예금 전표줄을 짝짓는다 (순수).

은행 쪽 INOUT_GUBUN '2'(입금) ↔ 전표 차변 '3', '1'(출금) ↔ 대변 '4'.
본체는 **합계 대사**(은행 합계 = 전표 합계)다. 건별 짝은 합계가 어긋났을 때 어디가
빠졌는지 보여 주는 설명이라, 못 찾아도 합계가 같으면 '합계 일치·건수 다름'으로 둔다.

짝짓기 순서: ① 배치 묶음(outbox 작성번호가 같은 거래들의 합 = 전표줄 1개 — 약식·지사·급여)
→ ② 같은 금액 1:1(적요 토큰이 맞는 줄 먼저) → ③ 소집합 합(은행 여러 건 = 줄 1개, 또는
은행 1건 = 줄 여러 개) → ④ 남는 것.
"""

import re
from decimal import Decimal
from itertools import combinations
from typing import Any

MATCHED = "MATCHED"        # 합계 같고 남는 건 없음
TOTAL_ONLY = "TOTAL_ONLY"  # 합계는 같은데 건별로는 못 맞춤(건수 다름)
DIFF = "DIFF"              # 합계가 다름

DEPOSIT = ("2", "3")       # (INOUT_GUBUN, debit_credit)
WITHDRAWAL = ("1", "4")

SUBSET_MAX_SIZE = 6        # 소집합 탐색 크기 상한
SUBSET_MAX_POOL = 14       # 소집합 후보 수 상한 (C(14,6)=3003 — 충분히 싸다)

_DOC_RE = re.compile(r"\d{2}-\d{4}-\d-\d{4}")
_NUM_RE = re.compile(r"\d{6,}")


def tokens(text: Any) -> "set[str]":
    """적요·메모·관리번호에서 짝짓기에 쓸 토큰 — 감정서번호와 6자리 이상 숫자만."""
    raw = str(text or "")
    found = set(_DOC_RE.findall(raw))
    found.update(_NUM_RE.findall(_DOC_RE.sub(" ", raw)))
    return found


def _bank_tokens(row: "dict[str, Any]") -> "set[str]":
    return tokens(row.get("jeokyo")) | tokens(row.get("memo"))


def _line_tokens(line: "dict[str, Any]") -> "set[str]":
    return tokens(line.get("remark")) | tokens(line.get("management_no"))


def _pair(kind: str, bank_keys: list, line_keys: list, amount: Decimal) -> "dict[str, Any]":
    return {"kind": kind, "bank": list(bank_keys), "lines": list(line_keys), "amount": amount}


def _match_bundles(free_bank: dict, free_lines: dict, bundles: "dict[Any, str]", pairs: list) -> None:
    groups: "dict[str, list]" = {}
    for key in list(free_bank):
        bundle_id = bundles.get(key)
        if bundle_id:
            groups.setdefault(bundle_id, []).append(key)
    for keys in groups.values():
        total = sum(free_bank[k]["amount"] for k in keys)
        line_key = next((lk for lk, line in free_lines.items() if line["amount"] == total), None)
        if line_key is None:
            continue
        pairs.append(_pair("bundle", keys, [line_key], total))
        for k in keys:
            free_bank.pop(k)
        free_lines.pop(line_key)


def _match_exact(free_bank: dict, free_lines: dict, pairs: list) -> None:
    # 1차: 같은 금액 중 적요 토큰이 맞는 줄. 2차: 남은 같은 금액 아무 줄.
    for prefer_tokens in (True, False):
        for key in list(free_bank):
            row = free_bank.get(key)
            if row is None:
                continue
            candidates = [lk for lk, line in free_lines.items() if line["amount"] == row["amount"]]
            if prefer_tokens:
                own = _bank_tokens(row)
                candidates = [lk for lk in candidates if own and own & _line_tokens(free_lines[lk])]
            if not candidates:
                continue
            line_key = candidates[0]
            pairs.append(_pair("exact", [key], [line_key], row["amount"]))
            free_bank.pop(key)
            free_lines.pop(line_key)


def _find_subset(pool: "list[tuple[Any, Decimal]]", target: Decimal) -> "list | None":
    pool = pool[:SUBSET_MAX_POOL]
    for size in range(2, min(SUBSET_MAX_SIZE, len(pool)) + 1):
        for combo in combinations(pool, size):
            if sum(amount for _, amount in combo) == target:
                return [key for key, _ in combo]
    return None


def _match_groups(free_bank: dict, free_lines: dict, pairs: list) -> None:
    # 은행 여러 건 → 전표줄 1개 (급여 이체 여러 건을 한 줄로 기표)
    for line_key in list(free_lines):
        line = free_lines.get(line_key)
        if line is None:
            continue
        pool = [(k, r["amount"]) for k, r in free_bank.items() if r["amount"] < line["amount"]]
        found = _find_subset(pool, line["amount"])
        if found:
            pairs.append(_pair("group", found, [line_key], line["amount"]))
            for k in found:
                free_bank.pop(k)
            free_lines.pop(line_key)
    # 은행 1건 → 전표줄 여러 개 (한 입금을 여러 줄로 나눠 기표)
    for key in list(free_bank):
        row = free_bank.get(key)
        if row is None:
            continue
        pool = [(lk, line["amount"]) for lk, line in free_lines.items() if line["amount"] < row["amount"]]
        found = _find_subset(pool, row["amount"])
        if found:
            pairs.append(_pair("group", [key], found, row["amount"]))
            free_bank.pop(key)
            for lk in found:
                free_lines.pop(lk)


def match_side(bank_rows: "list[dict[str, Any]]", lines: "list[dict[str, Any]]",
               bundles: "dict[Any, str]") -> "dict[str, Any]":
    """한 방향(입금↔차변 또는 출금↔대변)의 합계 대사 + 건별 짝."""
    bank_rows = list(bank_rows)
    lines = list(lines)
    bank_total = sum((r["amount"] for r in bank_rows), Decimal(0))
    voucher_total = sum((line["amount"] for line in lines), Decimal(0))
    free_bank = {r["key"]: r for r in bank_rows}
    free_lines = {line["key"]: line for line in lines}
    pairs: "list[dict[str, Any]]" = []
    _match_bundles(free_bank, free_lines, bundles, pairs)
    _match_exact(free_bank, free_lines, pairs)
    _match_groups(free_bank, free_lines, pairs)
    diff = bank_total - voucher_total
    if diff == 0 and not free_bank and not free_lines:
        status = MATCHED
    elif diff == 0:
        status = TOTAL_ONLY
    else:
        status = DIFF
    return {
        "bank_count": len(bank_rows),
        "bank_total": bank_total,
        "voucher_count": len(lines),
        "voucher_total": voucher_total,
        "diff": diff,
        "status": status,
        "pairs": pairs,
        "unmatched_bank": list(free_bank.values()),
        "unmatched_lines": list(free_lines.values()),
        "unapproved_count": sum(1 for line in lines if not line.get("approved", True)),
    }


CANCEL_MARK = "취소"


def _cancelled_pairs(bank_rows: "list[dict[str, Any]]") -> "tuple[list[dict[str, Any]], list[dict[str, Any]]]":
    """같은 날 같은 금액의 입금과 '취소' 출금(또는 그 반대)은 서로 상쇄 — 전표가 없는 게 맞다.

    (8/21 광명제일: 현금 2,574,100 입금 뒤 같은 금액이 '의창새마을금고/취소'로 나갔다.)
    '취소' 표시가 없는 같은 금액 입·출금은 상쇄하지 않는다 — 실제 왕복이면 전표가 있어야 한다.
    """
    remaining = list(bank_rows)
    pairs = []
    for row in list(remaining):
        if row.get("inout") != "1" or row not in remaining:
            continue
        if CANCEL_MARK not in str(row.get("jeokyo") or ""):
            continue
        twin = next((r for r in remaining if r.get("inout") == "2" and r["amount"] == row["amount"]), None)
        if twin is None:
            continue
        pairs.append({"deposit": twin["key"], "withdrawal": row["key"], "amount": row["amount"]})
        remaining.remove(row)
        remaining.remove(twin)
    for row in list(remaining):
        if row.get("inout") != "2" or row not in remaining or CANCEL_MARK not in str(row.get("jeokyo") or ""):
            continue
        twin = next((r for r in remaining if r.get("inout") == "1" and r["amount"] == row["amount"]), None)
        if twin is None:
            continue
        pairs.append({"deposit": row["key"], "withdrawal": twin["key"], "amount": row["amount"]})
        remaining.remove(row)
        remaining.remove(twin)
    return remaining, pairs


def match_account_day(bank_rows: "list[dict[str, Any]]", lines: "list[dict[str, Any]]",
                      bundles: "dict[Any, str]") -> "dict[str, Any]":
    """입금은 차변과, 출금은 대변과만 맞춘다. 취소로 상쇄된 입·출금 쌍은 먼저 뺀다."""
    bank_rows, cancelled = _cancelled_pairs(bank_rows)
    result: "dict[str, Any]" = {"cancelled": cancelled}
    for name, (inout, drcr) in (("deposit", DEPOSIT), ("withdrawal", WITHDRAWAL)):
        result[name] = match_side(
            [r for r in bank_rows if r.get("inout") == inout],
            [line for line in lines if line.get("drcr") == drcr],
            bundles,
        )
    return result
