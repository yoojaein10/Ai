"""입금현황 '국민 약식수수료' 한 줄 + 인쇄 정렬 (2026-08-27 사용자 요청).

400* 의뢰번호(국민 약식) 입금은 감정서번호 접두사(01_ 등)로 시작하지 않아 입금현황에
아예 안 보였다. 매출실적처럼 '국민 약식수수료' 한 줄로 묶되, 입금현황은 부가세 포함
금액이다. 첫 페이지 맨 위에 한 줄, 합계 바에도 더한다.

2026-08-28: 금액 원천을 요약 캐시(최근 입금일 기준 누적)에서 **기간 안 전표**로
바꿨다 — 발급수수료→본수수료처럼 한 번호에 입금이 두 번 오면 과거분까지 끼어
재무팀 집계와 안 맞았다(8/27 실측 906,400 vs 897,600).
"""

from datetime import date
from pathlib import Path

import pytest

from app.services.receivables import KB_SIMPLE_DOC_ID, kb_simple_row_wanted, kb_simple_sql

ROOT = Path(__file__).resolve().parents[1]
RECEIVABLES = (ROOT / "app" / "services" / "receivables.py").read_text(encoding="utf-8")
JS = (ROOT / "desktop" / "ui" / "receivables.js").read_text(encoding="utf-8")
HTML = (ROOT / "desktop" / "ui" / "receivables.html").read_text(encoding="utf-8")


def test_묶음_행은_입금현황_첫_페이지에_감정서를_고르는_조건이_없을_때만():
    assert kb_simple_row_wanted(mode="received", page=1)
    assert not kb_simple_row_wanted(mode="outstanding", page=1)
    assert not kb_simple_row_wanted(mode="received", page=2)
    for key in ("doc_id", "customer_name", "manager", "scope_person"):
        assert not kb_simple_row_wanted(mode="received", page=1, **{key: "x"}), key
    assert not kb_simple_row_wanted(mode="received", page=1, pay_statuses=["완납"])
    assert not kb_simple_row_wanted(mode="received", page=1, bill_from=1)
    assert not kb_simple_row_wanted(mode="received", page=1, outstanding_to=1)


def test_묶음_SQL은_전표를_기간과_회계단위로_거른다():
    sql, params = kb_simple_sql(date_from="2026-08-01", date_to="2026-08-25", division_code="1000")
    assert "v.management_no LIKE '400%'" in sql and "dbo.a10_voucher_cache v" in sql
    # 요약 캐시로 되돌리면 '최근 입금일 기준 누적'이라 두 번 입금 건에서 부푼다
    assert "a10_receivable_summary" not in sql
    assert "v.division_code = :kb_division" in sql and params["kb_division"] == "1000"
    assert params["kb_date_from"] == "2026-08-01" and params["kb_date_to"] == "2026-08-25"
    assert "v.voucher_date = :kb_date_to" in sql                 # 종료일 당일 입금(합계 바 둘째 줄)
    # 취소·정정(차변)을 뺀 순액이어야 한다 — 매출실적의 400* 줄과 같은 셈법
    assert "WHEN v.debit_credit = '4' THEN v.amount ELSE -v.amount" in sql
    sql, params = kb_simple_sql(date_from=None, date_to=None, division_code=None)
    assert "kb_division" not in sql and "kb_date_from" not in sql and params == {}


@pytest.mark.integration
def test_실데이터_8월27일은_재무팀_집계와_같다():
    """8/27 약식 = 전표 00050(829,400) + 00076(68,200) = 897,600원 55건 —
    재무팀 수기 집계와 대조 확인한 날(2026-08-28). 요약 캐시 기준이던 예전
    코드는 7월 발급수수료 4건이 끼어 906,400원이 나왔다."""
    from app.database import get_session_factory
    from app.services.receivables import kb_simple_fee_row

    db = get_session_factory()()
    try:
        row = kb_simple_fee_row(
            db, date_from=date(2026, 8, 27), date_to=date(2026, 8, 27),
            division_code="1000",
        )
    finally:
        db.close()
    assert row is not None
    assert row["received_amount"] == 897600
    assert row["daily_received_amount"] == 897600
    assert row["kb_simple_docs"] == 55
    assert row["outstanding_amount"] == 0.0


def test_목록에_끼워_넣고_화면은_묶음_행의_상세_클릭을_막는다():
    assert KB_SIMPLE_DOC_ID == "국민 약식수수료"
    assert "kb_simple_fee_row(" in RECEIVABLES and "result[\"total\"] = total + 1" in RECEIVABLES
    assert "row.kb_simple" in JS and "kb-simple" in JS
    assert "receivables.js?v=20260827-1" in HTML


def test_증빙_발행_여부는_한_함수로_붙인다():
    """입금현황·미수금현황·감정서 LIST 가 같은 규칙을 쓴다."""
    assert "def attach_proof_issued(" in RECEIVABLES
    assert RECEIVABLES.count("attach_proof_issued(self.db, items)") >= 1


def test_인쇄는_소재지를_왼쪽_나머지는_가운데():
    """2026-08-27 사용자 요청 — 인쇄 표에 소재지 열(왼쪽 정렬), 나머지 칸·머리글은 가운데."""
    print_block = JS[JS.index("function buildPrintHtml"):JS.index("function fitPrintZoom")]
    assert print_block.count('<th class="left">소재지</th>') == 2          # 입금현황·미수금현황 둘 다
    assert print_block.count("<td class=\"left\">${escapeHtml(row.address||'-')}</td>") == 2
    assert ".print-area th, .print-area td{ text-align: center; }" in HTML
    assert ".print-area th.left, .print-area td.left{ text-align: left; }" in HTML
