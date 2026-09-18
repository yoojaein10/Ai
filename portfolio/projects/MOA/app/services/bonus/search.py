"""여러 달 상여 검색 — 지급월 구간을 훑어 (감정서 × 사람) 행을 평평하게 편다.

달마다 bonus_report_v2 를 그대로 쓴다: 마감(CLOSED)·엑셀 이력 달은 스냅샷을 읽고
열린 달만 계산한다. 감정서번호·유치자는 부분 일치(대소문자 무시)이고,
보류 행도 사유와 함께 나온다 — "이 감정서가 왜 상여에 없지?"에 바로 답하기 위해서다.
"""

import re
from typing import Any, Callable

from app.services.bonus.report import bonus_report_v2
from app.services.bonus.schedule import BonusMasterError

MAX_MONTHS = 12
MAX_ROWS = 2000
_PERIOD = re.compile(r"^(\d{4})(0[1-9]|1[0-2])$")
_GROUPS = (("shareholders", "SHAREHOLDER"), ("common", "COMMON"), ("associates", "ASSOCIATE"))


def period_range(period_from: str, period_to: str) -> "list[str]":
    """지급월 구간(양끝 포함)을 오름차순으로. 거꾸로거나 MAX_MONTHS 를 넘으면 거부."""
    first, last = _PERIOD.match(str(period_from or "")), _PERIOD.match(str(period_to or ""))
    if not first or not last:
        raise BonusMasterError("지급월은 YYYYMM 이어야 합니다.")
    start = int(first.group(1)) * 12 + int(first.group(2)) - 1
    end = int(last.group(1)) * 12 + int(last.group(2)) - 1
    if start > end:
        raise BonusMasterError("시작 지급월이 끝 지급월보다 늦습니다.")
    if end - start + 1 > MAX_MONTHS:
        raise BonusMasterError(f"지급월 구간은 {MAX_MONTHS}달 이내여야 합니다.")
    return [f"{month // 12}{month % 12 + 1:02d}" for month in range(start, end + 1)]


def _flat_row(period: str, person: str, row: "dict[str, Any]", group_kind: str) -> "dict[str, Any]":
    kind = row.get("kind") or group_kind
    return {
        "period": period, "person": person, "kind": kind, "doc_id": row.get("doc_id") or "",
        "work_type": row.get("work_type"), "customer_name": row.get("customer_name"),
        "receipt_date": row.get("receipt_date"),
        "rate": row.get("applied_rate") if kind == "COMMON" else row.get("rate"),
        "share_pct": row.get("share_pct"), "fee": row.get("fee"),
        "assessed": row.get("assessed"), "bonus": row.get("bonus"),
        "flags": list(row.get("flags") or []), "held_reason": None,
    }


def flatten_report(report: "dict[str, Any]") -> "list[dict[str, Any]]":
    """리포트 → 평평한 행 목록. 세 그룹의 (감정서 × 사람) 행 + 보류 목록."""
    period = report["period"]
    rows: "list[dict[str, Any]]" = []
    for group, group_kind in _GROUPS:
        for entry in report.get(group, []):
            rows.extend(_flat_row(period, entry["name"], row, group_kind) for row in entry.get("rows", []))
    for held in report.get("held", []):
        rows.append({
            "period": period, "person": held.get("person") or "", "kind": None,
            "doc_id": held.get("doc_id") or "", "work_type": None, "customer_name": None,
            "receipt_date": None, "rate": None, "share_pct": None,
            "fee": held.get("fee_total", held.get("fee")), "assessed": None, "bonus": None,
            "flags": [], "held_reason": held.get("reason"),
        })
    return rows


def search_bonus(
    db,
    period_from: str,
    period_to: str,
    *,
    doc_id: "str | None" = None,
    person: "str | None" = None,
    scope_person: "str | None" = None,
    report_fn: "Callable[..., dict[str, Any]]" = bonus_report_v2,
    max_rows: int = MAX_ROWS,
) -> "dict[str, Any]":
    periods = period_range(period_from, period_to)
    doc_needle = (doc_id or "").strip().upper()
    person_needle = (person or "").strip()
    months: "list[dict[str, Any]]" = []
    rows: "list[dict[str, Any]]" = []
    for period in periods:
        report = report_fn(db, period, scope_person=scope_person)
        months.append({"period": period, "status": report.get("status") or "OPEN"})
        rows.extend(flatten_report(report))
    if scope_person:
        rows = [row for row in rows if row["person"] in ("", scope_person)]
    if doc_needle:
        rows = [row for row in rows if doc_needle in str(row["doc_id"]).upper()]
    if person_needle:
        rows = [row for row in rows if person_needle in row["person"]]
    rows.sort(key=lambda row: (row["person"], str(row["doc_id"])))
    rows.sort(key=lambda row: row["period"], reverse=True)   # 안정 정렬 — 최신 달 먼저, 그 안에서 사람·감정서 순
    return {
        "period_from": periods[0], "period_to": periods[-1], "months": months,
        "rows": rows[:max_rows], "total": len(rows), "truncated": len(rows) > max_rows,
    }
