"""일계표 대사 — 순수 매칭 엔진 (계좌 × 일자 한 묶음).

8/25 실측 모양을 그대로 옮긴 골든: 약식 17건→전표 10줄(묶음), 급여 이체 36건→21줄
(합계 일치·건수 다름), 1:1 정확 금액, 남는 것. 은행 쪽은 INOUT_GUBUN('2' 입금/'1' 출금),
전표 쪽은 debit_credit('3' 차변/'4' 대변)이다.
"""

from datetime import date
from decimal import Decimal

from app.services.bank_reconcile_match import (
    DIFF, MATCHED, TOTAL_ONLY, match_account_day, match_side, tokens,
)

DAY = date(2026, 8, 25)


def bank(key, amount, *, inout="2", jeokyo="", memo=""):
    return {"key": key, "day": DAY, "inout": inout, "amount": Decimal(amount), "jeokyo": jeokyo, "memo": memo,
            "bank_cd": "10000004", "acct_no": "48420101128982", "nickname": "남부터미널", "time": "100000"}


def line(key, amount, *, drcr="3", remark="", management_no=None, division="1000", approved=True):
    return {"key": key, "day": DAY, "drcr": drcr, "amount": Decimal(amount), "remark": remark,
            "management_no": management_no, "division_code": division, "voucher_no": f"{key:05d}",
            "line_no": "00001", "partner_code": "01-04-0001", "partner_name": "국민남부", "approved": approved}


def test_금액이_하나씩_맞으면_전부_짝지어진다():
    result = match_side([bank("a", 52_800), bank("b", 85_800)], [line(1, 85_800), line(2, 52_800)], {})
    assert result["status"] == MATCHED
    assert result["bank_total"] == 138_600 and result["voucher_total"] == 138_600 and result["diff"] == 0
    assert {(p["kind"], p["amount"]) for p in result["pairs"]} == {("exact", 52_800), ("exact", 85_800)}
    assert result["unmatched_bank"] == [] and result["unmatched_lines"] == []


def test_약식_묶음은_배치_묶음번호로_한_줄에_맞춘다():
    """국민남부 8/25: 약식 9건이 outbox menu_sq 50744 한 전표의 합계줄 1개가 됐다."""
    yak = [bank(f"y{i}", amt, jeokyo=f"40057{i:04d}/대체입금/") for i, amt in enumerate(
        [52_800, 52_800, 52_800, 85_800, 88_000, 52_800, 55_000, 88_000, 88_000])]
    bundles = {row["key"]: "50744" for row in yak}
    other = bank("g1", 2_412_300, jeokyo="302218930/대체입금/", memo="01-2608-3-2601")
    lines = [line(1, sum(r["amount"] for r in yak), remark="약식평가수수료 입금"),
             line(2, 2_412_300, remark="수수료입금", management_no="01-2608-3-2601")]
    result = match_side(yak + [other], lines, bundles)
    assert result["status"] == MATCHED
    bundle = next(p for p in result["pairs"] if p["kind"] == "bundle")
    assert len(bundle["bank"]) == 9 and bundle["lines"] == [1]
    assert result["bank_count"] == 10 and result["voucher_count"] == 2


def test_같은_금액이_여럿이면_적요_토큰이_맞는_줄을_고른다():
    rows = [bank("a", 50_000, jeokyo="302218930/대체입금/"), bank("b", 50_000, jeokyo="302215867/대체입금/")]
    lines = [line(1, 50_000, remark="302215867"), line(2, 50_000, remark="302218930")]
    result = match_side(rows, lines, {})
    by_bank = {p["bank"][0]: p["lines"][0] for p in result["pairs"]}
    assert by_bank == {"a": 2, "b": 1}


def test_합계는_같은데_건수가_다르면_소집합으로_찾고_못_찾으면_합계일치로_둔다():
    # 급여 이체: 은행 3건이 전표 1줄로 합쳐 기표된 경우 → 소집합 짝
    grouped = match_side([bank("a", 100), bank("b", 200), bank("c", 300)], [line(1, 600)], {})
    assert grouped["status"] == MATCHED
    assert grouped["pairs"][0]["kind"] == "group" and sorted(grouped["pairs"][0]["bank"]) == ["a", "b", "c"]
    # 반대 방향: 은행 1건이 전표 2줄로 나뉜 경우
    split = match_side([bank("a", 600)], [line(1, 250), line(2, 350)], {})
    assert split["status"] == MATCHED and sorted(split["pairs"][0]["lines"]) == [1, 2]
    # 합계만 같고 어떤 조합도 안 맞으면 '합계 일치·건수 다름'
    odd = match_side([bank("a", 100), bank("b", 200)], [line(1, 150), line(2, 150)], {})
    assert odd["status"] == TOTAL_ONLY and odd["diff"] == 0
    assert [r["key"] for r in odd["unmatched_bank"]] == ["a", "b"]
    assert [r["key"] for r in odd["unmatched_lines"]] == [1, 2]


def test_차이가_나면_남는_건이_양쪽에_그대로_보인다():
    result = match_side([bank("a", 1_000), bank("b", 500)], [line(1, 1_000), line(2, 400)], {})
    assert result["status"] == DIFF and result["diff"] == 100          # 은행 − 전표
    assert [r["key"] for r in result["unmatched_bank"]] == ["b"]
    assert [r["key"] for r in result["unmatched_lines"]] == [2]


def test_미승인_전표줄은_짝지어도_표시가_남는다():
    result = match_side([bank("a", 1_000)], [line(1, 1_000, approved=False)], {})
    assert result["status"] == MATCHED
    assert result["unapproved_count"] == 1


def test_입금은_차변과_출금은_대변과만_맞춘다():
    rows = [bank("in", 1_000, inout="2"), bank("out", 7_000, inout="1")]
    lines = [line(1, 1_000, drcr="3"), line(2, 7_000, drcr="4")]
    result = match_account_day(rows, lines, {})
    assert result["deposit"]["status"] == MATCHED and result["deposit"]["bank_count"] == 1
    assert result["withdrawal"]["status"] == MATCHED and result["withdrawal"]["voucher_count"] == 1
    # 방향이 어긋난 줄은 같은 금액이라도 짝이 되지 않는다
    crossed = match_account_day([bank("in", 1_000, inout="2")], [line(1, 1_000, drcr="4")], {})
    assert crossed["deposit"]["status"] == DIFF and crossed["withdrawal"]["status"] == DIFF


def test_같은_날_같은_금액의_입금과_취소_출금은_서로_상쇄한다():
    """8/21 광명제일: 2,574,100 입금 뒤 같은 금액이 '취소'로 출금됐고 전표는 양쪽 다 없다 —
    둘을 상쇄로 묶어야 '차이'가 아니다. '취소' 표시가 없는 같은 금액 입·출금은 상쇄하지 않는다."""
    rows = [
        bank("d", 2_574_100, inout="2", jeokyo="260720092/현금/3564-006/"),
        bank("w", 2_574_100, inout="1", jeokyo="의창새마을금고/취소/6152-001/"),
        bank("x", 1_000, inout="2"),
    ]
    result = match_account_day(rows, [line(1, 1_000)], {})
    assert result["cancelled"] == [{"deposit": "d", "withdrawal": "w", "amount": 2_574_100}]
    assert result["deposit"]["status"] == MATCHED and result["deposit"]["bank_count"] == 1
    assert result["withdrawal"]["status"] == MATCHED and result["withdrawal"]["bank_count"] == 0

    plain = match_account_day([bank("d", 500, inout="2"), bank("w", 500, inout="1")], [], {})
    assert plain["cancelled"] == []
    assert plain["deposit"]["status"] == DIFF and plain["withdrawal"]["status"] == DIFF


def test_양쪽_다_비면_빈_결과다():
    result = match_side([], [], {})
    assert result["status"] == MATCHED and result["bank_count"] == 0 and result["pairs"] == []


def test_토큰은_감정서번호와_긴_숫자만_뽑는다():
    assert tokens("302218930/대체입금/ 01-2608-3-2601") == {"302218930", "01-2608-3-2601"}
    assert tokens("타행급여91건/인터넷출금이체/") == set()
    assert tokens(None) == set()
