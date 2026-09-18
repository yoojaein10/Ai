"""엑셀 지급 시트 ↔ 새 엔진 리포트 대조 (순수 함수). 스크립트 scripts/bonus_compare_excel.py 가 쓴다.

주주 시트: 상세행(감정서×행)을 다음 '주주 합계' 행의 주인에게 귀속 — H(산정)·F(순수수료).
          합계행: Q 산출, R~U 상여, Y 산정금액, Z 소득세, AA 주민세, AB 기타공제, AC 지급, AE 미납비용.
평·동 시트: 상세행 D 담당자('공(이름)' 은 괄호 안), L 산정, AA 상여. 합계행(C='주주 합계'|'소속 합계')
          AD 산정, AE 소득세, AF 지방세, AG 기타공제, AH 지급.
"""

import re
from collections import defaultdict
from typing import Any

_DOC = re.compile(r"^\d\d-\d{4}")


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _doc(value: Any) -> str:
    return str(value).split(",")[0].strip()


def read_shareholder_sheet(ws) -> "dict[str, Any]":
    """값 워크북의 'NN월-주주' 시트 → rows[(doc, owner)] = {fee, assessed}, totals[owner] = 합계 합."""
    rows: "dict[tuple[str, str], dict[str, float]]" = {}
    totals: "dict[str, dict[str, float]]" = defaultdict(lambda: defaultdict(float))
    pending: "list[int]" = []
    for r in range(7, ws.max_row + 1):
        head = ws.cell(r, 1).value
        if isinstance(head, str) and _DOC.match(head):
            pending.append(r)
            continue
        if not (isinstance(head, str) and "합계" in head):
            continue
        owner = str(ws.cell(r, 4).value or "").strip()
        for pr in pending:
            key = (_doc(ws.cell(pr, 1).value), owner)
            entry = rows.setdefault(key, {"fee": 0.0, "assessed": 0.0})
            entry["fee"] += _num(ws.cell(pr, 6).value)
            entry["assessed"] += _num(ws.cell(pr, 8).value)
        pending = []
        bonus = sum(_num(ws.cell(r, c).value) for c in (18, 19, 20, 21))
        for key, col in (("payout_base", 17), ("pretax", 25), ("income_tax", 26), ("resident_tax", 27),
                         ("other_deduct", 28), ("payment", 29), ("unpaid_carry_out", 31), ("card_limit", 30)):
            totals[owner][key] += _num(ws.cell(r, col).value)
        totals[owner]["bonus"] += bonus
        totals[owner]["blocks"] += 1
    return {"rows": rows, "totals": {k: dict(v) for k, v in totals.items()}}


def read_associate_sheet(ws) -> "dict[str, Any]":
    """값 워크북의 'NN월-평.동' 시트 → rows[(doc, person)] = {fee, assessed, bonus}, totals[person] = {kind, ...}."""
    rows: "dict[tuple[str, str], dict[str, float]]" = {}
    totals: "dict[str, dict[str, Any]]" = {}
    pending: "list[int]" = []
    for r in range(8, ws.max_row + 1):
        head = ws.cell(r, 1).value
        label = str(ws.cell(r, 3).value or "").strip()
        if isinstance(head, str) and _DOC.match(head):
            pending.append(r)
            continue
        if label not in ("주주 합계", "소속 합계"):
            continue
        owner = str(ws.cell(r, 4).value or "").strip()
        for pr in pending:
            key = (_doc(ws.cell(pr, 1).value), owner)
            entry = rows.setdefault(key, {"fee": 0.0, "assessed": 0.0, "bonus": 0.0})
            entry["fee"] += _num(ws.cell(pr, 7).value)
            entry["assessed"] += _num(ws.cell(pr, 12).value)
            entry["bonus"] += _num(ws.cell(pr, 27).value)
        pending = []
        totals[owner] = {
            "kind": "COMMON" if label == "주주 합계" else "ASSOCIATE",
            "bonus": _num(ws.cell(r, 27).value), "pretax": _num(ws.cell(r, 30).value),
            "income_tax": _num(ws.cell(r, 31).value), "resident_tax": _num(ws.cell(r, 32).value),
            "other_deduct": _num(ws.cell(r, 33).value), "payment": _num(ws.cell(r, 34).value),
        }
    return {"rows": rows, "totals": totals}


def _report_rows(report: "dict[str, Any]") -> "dict[tuple[str, str], dict[str, float]]":
    rows: "dict[tuple[str, str], dict[str, float]]" = {}
    for group in ("shareholders", "common", "associates"):
        for person in report.get(group, []):
            for row in person["rows"]:
                entry = rows.setdefault((row["doc_id"], person["name"]), {"fee": 0.0, "assessed": 0.0})
                entry["fee"] += float(row["fee"] or 0)
                entry["assessed"] += float(row["assessed"] or 0)
    return rows


def _close(a: float, b: float, tolerance: float = 0.01, floor: float = 1000.0) -> bool:
    return abs(a - b) <= max(floor, abs(b) * tolerance)


def compare(report: "dict[str, Any]", shareholder_sheet: "dict[str, Any]", associate_sheet: "dict[str, Any]") -> "dict[str, Any]":
    """리포트 vs 시트. 감정서 커버리지·(감정서,사람) 산정 일치·사람별 합계 차이를 돌려준다."""
    excel_rows = {**shareholder_sheet["rows"], **associate_sheet["rows"]}
    engine_rows = _report_rows(report)
    excel_docs = {doc for doc, _ in excel_rows}
    engine_docs = {doc for doc, _ in engine_rows}
    held_docs = {h["doc_id"] for h in report.get("held", [])}
    pairs_both = set(excel_rows) & set(engine_rows)
    pairs_close = sorted(k for k in pairs_both if _close(engine_rows[k]["assessed"], excel_rows[k]["assessed"]))

    person_diffs = []
    engine_people = {p["name"]: p for p in report.get("shareholders", [])}
    for name, excel in shareholder_sheet["totals"].items():
        engine = engine_people.get(name)
        if excel.get("blocks", 0) and not any(excel.get(k) for k in ("pretax", "payout_base")) and engine is None:
            continue  # 빈 블록만 있는 사람
        totals = engine["totals"] if engine else {}
        person_diffs.append({
            "name": name, "kind": "SHAREHOLDER",
            "excel": {k: excel.get(k, 0.0) for k in ("payout_base", "bonus", "pretax", "income_tax", "resident_tax", "payment", "unpaid_carry_out")},
            "engine": {k: float(totals.get(k) or 0) for k in ("payout_base", "bonus", "pretax", "income_tax", "resident_tax", "payment", "unpaid_carry_out")},
        })
    engine_assoc = {p["name"]: p for p in report.get("associates", [])}
    engine_common = {p["name"]: p for p in report.get("common", [])}
    for name, excel in associate_sheet["totals"].items():
        engine = (engine_common if excel["kind"] == "COMMON" else engine_assoc).get(name)
        totals = engine["totals"] if engine else {}
        person_diffs.append({
            "name": name, "kind": excel["kind"],
            "excel": {k: excel.get(k, 0.0) for k in ("bonus", "pretax", "income_tax", "resident_tax", "payment")},
            "engine": {k: float(totals.get(k) or 0) for k in ("bonus", "pretax", "income_tax", "resident_tax", "payment")},
        })
    for diff in person_diffs:
        diff["pretax_close"] = _close(diff["engine"]["pretax"], diff["excel"]["pretax"])
        diff["payment_exact"] = abs(diff["engine"]["payment"] - diff["excel"]["payment"]) < 1
        diff["gap"] = diff["engine"]["pretax"] - diff["excel"]["pretax"]
    person_diffs.sort(key=lambda d: -abs(d["gap"]))
    return {
        "docs": {
            "excel": len(excel_docs), "engine": len(engine_docs), "both": len(excel_docs & engine_docs),
            "excel_only": sorted(excel_docs - engine_docs), "engine_only": sorted(engine_docs - excel_docs),
            "held_in_excel": sorted(held_docs & excel_docs),
        },
        "pairs": {"excel": len(excel_rows), "engine": len(engine_rows), "both": len(pairs_both), "close": len(pairs_close)},
        "persons": person_diffs,
    }
