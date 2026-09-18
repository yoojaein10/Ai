"""총괄표(사람별 지급 요약)와 회계 전표 라인 (엑셀 '총괄표 NN' 시트 + 하단 분개)."""

from typing import Any

SUMMARY_KEYS = ("pretax", "income_tax", "resident_tax", "other_deduct", "payment", "card_limit")


def summarize(shareholders, common, associates) -> "list[dict[str, Any]]":
    """이름별로 주주 Y + 공통건 AD + 소속 AD 를 합친다 (엑셀 총괄표 L/M/N/O/P)."""
    by_name: "dict[str, dict[str, Any]]" = {}
    for group in (shareholders, common, associates):
        for entry in group:
            row = by_name.setdefault(entry["name"], {
                "name": entry["name"], "kinds": [], "retired": entry.get("retired", False),
                **{key: 0.0 for key in SUMMARY_KEYS},
            })
            row["kinds"].append(entry["kind"])
            for key in SUMMARY_KEYS:
                row[key] += float(entry["totals"].get(key) or 0)
    return [by_name[name] for name in sorted(by_name)]


def journal_lines(summary_rows: "list[dict[str, Any]]") -> "list[dict[str, Any]]":
    """엑셀 총괄표 하단 분개: (차)임원상여 = 산정금액 합 / (대)예수금 소득세+주민세 · 미수금 기타공제 · 보통예금 지급액."""
    pretax = sum(float(row["pretax"] or 0) for row in summary_rows)
    withholding = sum(float(row["income_tax"] or 0) + float(row["resident_tax"] or 0) for row in summary_rows)
    other = sum(float(row["other_deduct"] or 0) for row in summary_rows)
    payment = sum(float(row["payment"] or 0) for row in summary_rows)
    return [
        {"account": "임원상여", "side": "차변", "amount": pretax, "remark": "성과상여 산정금액"},
        {"account": "예수금", "side": "대변", "amount": withholding, "remark": "소득세·주민세"},
        {"account": "미수금", "side": "대변", "amount": other, "remark": "기타공제"},
        {"account": "보통예금", "side": "대변", "amount": payment, "remark": "지급액"},
    ]
