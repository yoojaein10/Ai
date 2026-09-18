"""여러 달 상여 검색 (2026-08-27) — 지급월 구간 × 감정서번호·유치자 필터.

달마다 bonus_report_v2 를 그대로 쓰므로 여기서는 report_fn 을 가짜로 바꿔
구간 전개·평탄화·필터·정렬·자름만 본다.
"""

from datetime import date

import pytest

from app.services.bonus.schedule import BonusMasterError
from app.services.bonus.search import MAX_MONTHS, flatten_report, period_range, search_bonus


def _row(doc, person, *, kind="SHAREHOLDER", fee=1_000_000, rate=40.0, applied_rate=None, bonus=None):
    return {
        "doc_id": doc, "person": person, "kind": kind, "work_type": "담보", "customer_name": "어느 은행",
        "receipt_date": date(2026, 6, 10), "rate": rate, "applied_rate": applied_rate,
        "share_pct": 100.0, "fee": fee, "assessed": fee, "bonus": bonus, "flags": ["PAID_BY_BUNDLE"],
    }


def _report(period, *, shareholders=(), common=(), associates=(), held=(), status="OPEN"):
    def group(entries):
        return [{"name": name, "rows": list(rows)} for name, rows in entries]

    return {
        "period": period, "status": status,
        "shareholders": group(shareholders), "common": group(common), "associates": group(associates),
        "held": list(held),
    }


# ── period_range ─────────────────────────────────────────────────────────


def test_구간은_해를_넘겨_오름차순으로_전개된다():
    assert period_range("202608", "202608") == ["202608"]
    assert period_range("202611", "202702") == ["202611", "202612", "202701", "202702"]


def test_구간이_거꾸로거나_형식이_틀리면_거부한다():
    with pytest.raises(BonusMasterError):
        period_range("202609", "202608")
    for bad in ("2026-8", "202613", "202600", ""):
        with pytest.raises(BonusMasterError):
            period_range(bad, "202608")


def test_구간은_최대_12달이다():
    assert len(period_range("202601", "202612")) == MAX_MONTHS
    with pytest.raises(BonusMasterError):
        period_range("202601", "202701")


# ── flatten_report ───────────────────────────────────────────────────────


def test_평탄화는_세_그룹_행과_보류_행을_한_줄씩_만든다():
    report = _report(
        "202608",
        shareholders=[("강무진", [_row("01-2607-3-0001", "강무진")])],
        common=[("신상우", [_row("01-2607-3-0002", "신상우", kind="COMMON", rate=None, applied_rate=3.0, bonus=30_000)])],
        associates=[("이영은", [_row("01-2607-3-0003", "이영은", kind="ASSOCIATE", bonus=200_000)])],
        held=[{"doc_id": "01-2607-3-0009", "person": None, "reason": "HELD_UNPAID", "fee_total": 500_000, "outstanding": 100_000}],
    )
    rows = flatten_report(report)
    assert [(r["period"], r["person"], r["kind"], r["doc_id"]) for r in rows] == [
        ("202608", "강무진", "SHAREHOLDER", "01-2607-3-0001"),
        ("202608", "신상우", "COMMON", "01-2607-3-0002"),
        ("202608", "이영은", "ASSOCIATE", "01-2607-3-0003"),
        ("202608", "", None, "01-2607-3-0009"),
    ]
    assert rows[1]["rate"] == 3.0                       # 공통건은 applied_rate 를 요율로
    assert rows[0]["rate"] == 40.0 and rows[0]["held_reason"] is None
    assert rows[3]["held_reason"] == "HELD_UNPAID" and rows[3]["fee"] == 500_000


# ── search_bonus ─────────────────────────────────────────────────────────


def _reports_by_period(reports):
    def fn(db, period, *, scope_person=None):
        report = reports[period]
        if scope_person is None:
            return report
        return {
            **report,
            **{g: [p for p in report[g] if p["name"] == scope_person] for g in ("shareholders", "common", "associates")},
            "held": [h for h in report["held"] if h.get("person") in (None, scope_person)],
        }
    return fn


REPORTS = {
    "202607": _report("202607", status="CLOSED", shareholders=[
        ("강무진", [_row("01-2606-3-0001", "강무진")]),
        ("김형식", [_row("01-2606-A-0002", "김형식")]),
    ]),
    "202608": _report("202608", shareholders=[
        ("강무진", [_row("01-2607-3-0001", "강무진"), _row("01-2606-a-0002", "강무진")]),
    ], held=[{"doc_id": "01-2606-3-0001", "person": "김형식", "reason": "ALREADY_PAID"}]),
}


def test_여러_달을_묶어_최신_달부터_돌려주고_상태를_함께_알린다():
    result = search_bonus(None, "202607", "202608", report_fn=_reports_by_period(REPORTS))
    assert result["months"] == [{"period": "202607", "status": "CLOSED"}, {"period": "202608", "status": "OPEN"}]
    assert [r["period"] for r in result["rows"]] == ["202608"] * 3 + ["202607"] * 2
    assert result["total"] == 5 and result["truncated"] is False


def test_감정서번호는_대소문자_없이_부분_일치다():
    result = search_bonus(None, "202607", "202608", doc_id=" 2606-A ", report_fn=_reports_by_period(REPORTS))
    assert [(r["period"], r["person"], r["doc_id"]) for r in result["rows"]] == [
        ("202608", "강무진", "01-2606-a-0002"), ("202607", "김형식", "01-2606-A-0002"),
    ]


def test_유치자는_부분_일치고_보류_행도_같이_잡힌다():
    result = search_bonus(None, "202607", "202608", person="김형", report_fn=_reports_by_period(REPORTS))
    assert [(r["period"], r["doc_id"], r["held_reason"]) for r in result["rows"]] == [
        ("202608", "01-2606-3-0001", "ALREADY_PAID"), ("202607", "01-2606-A-0002", None),
    ]


def test_개인_범위는_본인_행만_남긴다():
    result = search_bonus(None, "202607", "202608", scope_person="강무진", report_fn=_reports_by_period(REPORTS))
    assert {r["person"] for r in result["rows"]} == {"강무진"}
    assert result["total"] == 3


def test_행이_넘치면_자르고_알린다():
    result = search_bonus(None, "202607", "202608", report_fn=_reports_by_period(REPORTS), max_rows=2)
    assert result["truncated"] is True and result["total"] == 5 and len(result["rows"]) == 2
