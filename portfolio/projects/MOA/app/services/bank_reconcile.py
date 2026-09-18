"""일계표 대사 — 원천 리더와 리포트 조립.

은행: CB2_ACCT_HIS(사이버브랜치, 읽기 전용) 입·출금 전부.
전표: a10_voucher_cache 보통예금(1030000) 차·대변, 전 회계단위(10분 주기 캐시).
계좌↔거래처: a10_bank_account_map. 배치 묶음: a10_deposit_outbox(status S)의 menu_sq.

재무팀이 사이버브랜치 엑셀과 아마란스 일월계표를 손으로 맞추던 일을 대신한다
(2026-08-26 실측: 8/25 본사 입금 711,350,107·출금 1,656,953,214 원 단위 일치).
"""

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.bank_account_map import BankAccountMap
from app.models.deposit_outbox import DepositOutbox
from app.models.voucher_cache import VoucherCache
from app.services.bank_reconcile_match import DIFF, MATCHED, TOTAL_ONLY, match_account_day
from app.services.deposit_source import fetch_transactions

BANK_ACCOUNT_CODE = "1030000"
UNMAPPED = "UNMAPPED"
STATUS_TEXT = {MATCHED: "일치", TOTAL_ONLY: "합계 일치·건수 다름", DIFF: "차이", UNMAPPED: "매핑 필요"}
_STATUS_RANK = {MATCHED: 0, TOTAL_ONLY: 1, DIFF: 2, UNMAPPED: 3}

EXPORT_SUMMARY_COLUMNS = [
    ("day", "일자"), ("nickname", "계좌"), ("acct_no", "계좌번호"), ("partner_name", "거래처"),
    ("divisions", "회계단위"),
    ("deposit_bank_count", "입금 은행 건수"), ("deposit_bank_total", "입금 은행 합계"),
    ("deposit_voucher_count", "입금 전표 건수"), ("deposit_voucher_total", "입금 전표 합계"),
    ("deposit_diff", "입금 차이"),
    ("withdrawal_bank_count", "출금 은행 건수"), ("withdrawal_bank_total", "출금 은행 합계"),
    ("withdrawal_voucher_count", "출금 전표 건수"), ("withdrawal_voucher_total", "출금 전표 합계"),
    ("withdrawal_diff", "출금 차이"),
    ("status_text", "상태"),
]
EXPORT_UNMATCHED_COLUMNS = [
    ("day", "일자"), ("nickname", "계좌"), ("direction", "구분"), ("side", "쪽"), ("amount", "금액"),
    ("voucher_no", "전표번호"), ("division_code", "회계단위"), ("text", "적요"), ("memo", "메모/관리번호"),
]


def _won(value: Any) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("1"))


def _text(value: Any) -> str:
    return str(value or "").strip()


def normalize_bank_rows(raw_rows: "list[dict[str, Any]]") -> "list[dict[str, Any]]":
    """CB2_ACCT_HIS 원천 행 → 매칭 엔진이 쓰는 모양."""
    rows = []
    for raw in raw_rows:
        day_text = _text(raw.get("ACCT_TXDAY"))
        rows.append({
            "key": _text(raw.get("UNIQUE_FIELD")),
            "bank_cd": _text(raw.get("BANK_CD")),
            "acct_no": _text(raw.get("ACCT_NO")),
            "nickname": _text(raw.get("ACCT_NICKNAME")),
            "day": date(int(day_text[:4]), int(day_text[4:6]), int(day_text[6:8])),
            "time": _text(raw.get("ACCT_TXTIME")),
            "inout": _text(raw.get("INOUT_GUBUN")),
            "amount": _won(raw.get("TX_AMT")),
            "jeokyo": _text(raw.get("JEOKYO")),
            "memo": _text(raw.get("Memo")),
        })
    return rows


def load_voucher_lines(db: Session, date_from: date, date_to: date) -> "list[dict[str, Any]]":
    rows = db.scalars(
        select(VoucherCache).where(
            VoucherCache.account_code == BANK_ACCOUNT_CODE,
            VoucherCache.voucher_date >= date_from,
            VoucherCache.voucher_date <= date_to,
        ).order_by(VoucherCache.voucher_date, VoucherCache.voucher_no, VoucherCache.line_no)
    ).all()
    return [{
        "key": row.id,
        "day": row.voucher_date,
        "division_code": _text(row.division_code),
        "drcr": _text(row.debit_credit),
        "amount": _won(row.amount),
        "voucher_no": _text(row.voucher_no),
        "line_no": _text(row.line_no),
        "partner_code": _text(row.partner_code),
        "partner_name": _text(row.partner_name),
        "remark": _text(row.remark),
        "management_no": _text(row.management_no),
        "approved": _text(row.document_status) != "0",
    } for row in rows]


def load_account_map(db: Session) -> "list[BankAccountMap]":
    """배치가 쓰는 매핑(active) + 대사 전용 매핑(reconcile_only, 지사 계좌 등)."""
    return list(db.scalars(select(BankAccountMap).where(
        or_(BankAccountMap.active == "Y", BankAccountMap.reconcile_only == "Y"))).all())


def load_bundles(db: Session, date_from: date, date_to: date) -> "dict[str, str]":
    """배치가 보낸 거래의 unique_field → 작성번호(menu_sq). 같은 번호 = 같은 전표."""
    rows = db.execute(
        select(DepositOutbox.unique_field, DepositOutbox.menu_sq).where(
            DepositOutbox.status == "S",
            DepositOutbox.menu_sq.is_not(None),
            DepositOutbox.tx_day >= date_from,
            DepositOutbox.tx_day <= date_to,
        )
    ).all()
    return {_text(uf): str(menu_sq) for uf, menu_sq in rows}


def cache_synced_at(db: Session) -> "str | None":
    stamp = db.execute(select(func.max(VoucherCache.synced_at))).scalar()
    return stamp.strftime("%Y-%m-%d %H:%M") if stamp else None


def _serialize_bank(row: "dict[str, Any]") -> "dict[str, Any]":
    return {**row, "day": row["day"].isoformat(), "amount": int(row["amount"])}


def _serialize_line(line: "dict[str, Any]") -> "dict[str, Any]":
    return {**line, "day": line["day"].isoformat(), "amount": int(line["amount"])}


def _serialize_side(side: "dict[str, Any]") -> "dict[str, Any]":
    return {
        "bank_count": side["bank_count"], "bank_total": int(side["bank_total"]),
        "voucher_count": side["voucher_count"], "voucher_total": int(side["voucher_total"]),
        "diff": int(side["diff"]), "status": side["status"],
        "pairs": [{**p, "amount": int(p["amount"])} for p in side["pairs"]],
        "unmatched_bank": [_serialize_bank(r) for r in side["unmatched_bank"]],
        "unmatched_lines": [_serialize_line(line) for line in side["unmatched_lines"]],
        "unapproved_count": side["unapproved_count"],
    }


def _group_rows(bank: list, lines: list, by_partner: dict) -> "tuple[dict[tuple, dict[str, list]], dict[tuple, list]]":
    """(일자, 계좌) 묶음과, 매핑 없는 거래처의 전표줄 묶음(일자, 거래처코드).

    사이버브랜치에는 본사 계좌와 일부 지사 계좌만 있다. 매핑 없는 거래처의 전표는 대개
    사이버브랜치가 모르는 지사 계좌라 대사 대상이 아니다 — 숨기지는 않되 따로 둔다.
    """
    groups: "dict[tuple, dict[str, list]]" = defaultdict(lambda: {"bank": [], "lines": []})
    voucher_only: "dict[tuple, list]" = defaultdict(list)
    for row in bank:
        groups[(row["day"], (row["bank_cd"], row["acct_no"]))]["bank"].append(row)
    for line in lines:
        mapped = by_partner.get(line["partner_code"])
        if mapped is None:
            voucher_only[(line["day"], line["partner_code"])].append(line)
        else:
            groups[(line["day"], (mapped.bank_cd, mapped.acct_no))]["lines"].append(line)
    return groups, voucher_only


def _row_status(mapped: bool, matched: "dict[str, dict[str, Any]]") -> str:
    if not mapped:
        return UNMAPPED
    return max((matched["deposit"]["status"], matched["withdrawal"]["status"]), key=_STATUS_RANK.get)


def _voucher_only_rows(voucher_only: "dict[tuple, list]") -> "list[dict[str, Any]]":
    rows = []
    for (day, partner_code), lines in voucher_only.items():
        item: "dict[str, Any]" = {
            "day": day.isoformat(), "partner_code": partner_code, "partner_name": lines[0]["partner_name"],
            "divisions": sorted({line["division_code"] for line in lines}),
        }
        for name, drcr in (("deposit", "3"), ("withdrawal", "4")):
            side = [line for line in lines if line["drcr"] == drcr]
            item[f"{name}_count"] = len(side)
            item[f"{name}_total"] = int(sum((line["amount"] for line in side), Decimal(0)))
        rows.append(item)
    rows.sort(key=lambda r: (r["day"], r["divisions"], r["partner_name"]))
    return rows


def build_report(db: Session, date_from: date, date_to: date, division: "str | None" = None, *,
                 bank_rows: "list[dict[str, Any]] | None" = None) -> "dict[str, Any]":
    """기간의 계좌×일자 대사 리포트. bank_rows 를 주면(시험) 사이버브랜치를 읽지 않는다."""
    raw = bank_rows if bank_rows is not None else fetch_transactions(
        date_from.strftime("%Y%m%d"), date_to.strftime("%Y%m%d"))
    bank = normalize_bank_rows(raw)
    lines = load_voucher_lines(db, date_from, date_to)
    if division:
        lines = [line for line in lines if line["division_code"] == division]
    maps = load_account_map(db)
    by_acct = {(m.bank_cd, m.acct_no): m for m in maps}
    by_partner = {_text(m.partner_code): m for m in maps}
    bundles = load_bundles(db, date_from, date_to)

    rows = []
    groups, voucher_only = _group_rows(bank, lines, by_partner)
    for (day, (bank_cd, acct_no)), group in groups.items():
        divisions = sorted({line["division_code"] for line in group["lines"]})
        mapping = by_acct.get((bank_cd, acct_no))
        # 회계단위로 거르면 그 회계단위 전표가 있는 계좌만 — 단, 매핑 없는 계좌는 어느
        # 회계단위인지 모르니 늘 보여 준다(손봐야 할 것이 사라지면 안 된다).
        if division and mapping is not None and division not in divisions:
            continue
        # 별명은 사이버브랜치 것 우선, 없으면(새 계좌) 매핑 표에 적어 둔 별명
        nickname = (group["bank"][0]["nickname"] if group["bank"] else "") or _text(mapping.nickname if mapping else "")
        matched = match_account_day(group["bank"], group["lines"], bundles)
        rows.append({
            "day": day.isoformat(), "bank_cd": bank_cd, "acct_no": acct_no, "nickname": nickname,
            "partner_code": _text(mapping.partner_code) if mapping else None,
            "partner_name": _text(mapping.partner_name) if mapping else None,
            "mapped": mapping is not None,
            "divisions": divisions,
            "deposit": _serialize_side(matched["deposit"]),
            "withdrawal": _serialize_side(matched["withdrawal"]),
            "cancelled": [{**p, "amount": int(p["amount"])} for p in matched["cancelled"]],
            "status": _row_status(mapping is not None, matched),
        })
    rows.sort(key=lambda r: (r["day"], 0 if r["mapped"] else 1, r["nickname"] or ""))
    only_rows = _voucher_only_rows(voucher_only)
    return {
        "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
        "division": division,
        "synced_at": cache_synced_at(db),
        "summary": _summary(rows, only_rows),
        "division_totals": _division_totals(lines),
        "rows": rows,
        "voucher_only": only_rows,
    }


def _summary(rows: "list[dict[str, Any]]", voucher_only: "list[dict[str, Any]]") -> "dict[str, Any]":
    summary: "dict[str, Any]" = {
        "accounts": len(rows), "mismatched": 0, "total_only": 0, "unmapped": 0,
        "voucher_only": len(voucher_only),
        "voucher_only_deposit_total": sum(r["deposit_total"] for r in voucher_only),
        "voucher_only_withdrawal_total": sum(r["withdrawal_total"] for r in voucher_only),
    }
    for name in ("deposit", "withdrawal"):
        side = {"bank_count": 0, "bank_total": 0, "voucher_count": 0, "voucher_total": 0}
        for row in rows:
            for key in side:
                side[key] += row[name][key]
        side["diff"] = side["bank_total"] - side["voucher_total"]
        summary[name] = side
    for row in rows:
        if row["status"] == DIFF:
            summary["mismatched"] += 1
        elif row["status"] == TOTAL_ONLY:
            summary["total_only"] += 1
        if not row["mapped"]:
            summary["unmapped"] += 1
    return summary


def _division_totals(lines: "list[dict[str, Any]]") -> "list[dict[str, Any]]":
    totals: "dict[str, dict[str, int]]" = defaultdict(
        lambda: {"debit_count": 0, "debit_total": 0, "credit_count": 0, "credit_total": 0})
    for line in lines:
        side = "debit" if line["drcr"] == "3" else "credit"
        totals[line["division_code"]][f"{side}_count"] += 1
        totals[line["division_code"]][f"{side}_total"] += int(line["amount"])
    return [{"division_code": code, **values} for code, values in sorted(totals.items())]


def export_sheets(report: "dict[str, Any]") -> "list[tuple[str, list, list]]":
    """엑셀 두 장 — 계좌 요약, 미일치 건. (시트명, 열, 행) 목록."""
    summary_rows = []
    unmatched = []
    for row in report["rows"]:
        label = row["nickname"] or row["partner_name"] or ""
        flat: "dict[str, Any]" = {
            "day": row["day"], "nickname": label, "acct_no": row["acct_no"] or "",
            "partner_name": row["partner_name"] or "", "divisions": ", ".join(row["divisions"]),
            "status_text": STATUS_TEXT.get(row["status"], row["status"]),
        }
        for name, direction in (("deposit", "입금"), ("withdrawal", "출금")):
            side = row[name]
            for key in ("bank_count", "bank_total", "voucher_count", "voucher_total", "diff"):
                flat[f"{name}_{key}"] = side[key]
            for item in side["unmatched_bank"]:
                unmatched.append({"day": row["day"], "nickname": label, "direction": direction, "side": "은행",
                                  "amount": item["amount"], "voucher_no": "", "division_code": "",
                                  "text": item["jeokyo"], "memo": item["memo"]})
            for item in side["unmatched_lines"]:
                unmatched.append({"day": row["day"], "nickname": label, "direction": direction, "side": "전표",
                                  "amount": item["amount"], "voucher_no": item["voucher_no"],
                                  "division_code": item["division_code"], "text": item["remark"],
                                  "memo": item["management_no"]})
        summary_rows.append(flat)
    return [("계좌 요약", EXPORT_SUMMARY_COLUMNS, summary_rows), ("미일치 건", EXPORT_UNMATCHED_COLUMNS, unmatched)]
