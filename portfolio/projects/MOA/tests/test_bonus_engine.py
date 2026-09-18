"""상여 계산 엔진(순수) — 엑셀 26.08 시트 값 그대로 재현한다.

주주: 행(감정서×사람) → 요율 블록별 산출액 Q → 상여 → Y(천원절사) → 소득세·주민세 → 지급.
사람 단위 항목(전월 가변비·미납비이월·감정서경비·화환)은 **산출액이 가장 큰 블록에 한 번**.
평·동: 소속은 건별 한계누진, 공통건은 행별 요율(기본 3%), 사람 합계에 지급률·소득세율.
"""

from datetime import date

from app.services.bonus.engine import Row, associate_person, shareholder_person


def _row(doc, fee, work="정비사업", **extra):
    return Row(doc_id=doc, person="누구", kind="SHAREHOLDER", work_type=work, fee=fee, **extra)


def test_강무진_26_08_주주_합계를_그대로_재현한다():
    """H 80,392,881 · K 803,928.81 · P 879,014.64 · J 3,125,744 · O 40,000 · W 20,000
    → Q 75,544,193.55 → 상여 30,217,677 → Y 30,197,000 → 소득세 9,059,000 → 주민세 905,900 → 지급 20,232,100."""
    rows = [
        _row("01-2503-5-0042", 21_000_000, "컨설팅", rate=40, block_from=date(2021, 3, 1)),   # 협회비 면제
        _row("01-2604-1-0252", 59_392_881, "정비사업", rate=40, block_from=date(2021, 3, 1), expense_fee=40_000),
    ]
    result = shareholder_person(rows, variable_auto=3_125_744, deductions=[{"kind": "WREATH", "amount": 20_000}])
    totals = result["totals"]
    assert round(totals["assessed"]) == 80_392_881
    assert round(totals["indemnity"], 2) == 803_928.81
    assert round(totals["association_fee"], 4) == 879_014.6388
    assert round(totals["payout_base"], 4) == 75_544_193.5512
    assert round(totals["bonus"], 2) == 30_217_677.42
    assert totals["pretax"] == 30_197_000
    assert totals["income_tax"] == 9_059_000
    assert totals["resident_tax"] == 905_900
    assert totals["payment"] == 20_232_100
    assert totals["unpaid_carry_out"] == 0
    assert totals["card_limit"] == 4_019_000          # ROUNDDOWN(80,392,881 × 5%, -3)
    assert len(result["blocks"]) == 1 and result["blocks"][0]["rate"] == 40


def test_산출액이_음수면_상여는_0이고_음수가_다음_달로_이월된다():
    """권오억 26.08: 행 없이 전월 가변비 2,693,660 → Q −2,693,660 → 상여 0, 미납비용 −2,693,660."""
    result = shareholder_person([], variable_auto=2_693_660)
    assert result["totals"]["payout_base"] == -2_693_660
    assert result["totals"]["bonus"] == 0 and result["totals"]["payment"] == 0
    assert result["totals"]["unpaid_carry_out"] == -2_693_660

    # 다음 달: 미납비이월 M 으로 들어와 산출액에서 빠진다
    nxt = shareholder_person([_row("01-2608-3-0001", 10_000_000, "담보", rate=40)], carry_in=2_693_660)
    assert round(nxt["totals"]["payout_base"], 2) == round(10_000_000 - 150_000 - 148_000 - 2_693_660, 2)
    assert nxt["totals"]["carry_in"] == 2_693_660


def test_요율_블록이_둘이면_사람_단위_공제는_산출액이_큰_블록에_한_번_들어간다():
    """이영준 26.08: 40% 블록 Q 3,770,294 (Y 1,508,000 / 지급 1,010,800),
    30% 블록 Q 7,479,700 에 화환 350,000 → Y 1,893,000 / 지급 1,269,300."""
    rows = [
        _row("01-2607-3-2255", 3_808_378, "컨설팅", rate=40, block_from=date(2026, 7, 8)),
        _row("01-2604-3-1272", 7_555_252.35, "컨설팅", rate=30, block_from=date(2024, 7, 1)),
    ]
    result = shareholder_person(rows, deductions=[{"kind": "WREATH", "amount": 350_000}])
    by_rate = {block["rate"]: block for block in result["blocks"]}
    assert by_rate[40]["pretax"] == 1_508_000 and by_rate[40]["payment"] == 1_010_800
    assert by_rate[30]["pretax"] == 1_893_000 and by_rate[30]["payment"] == 1_269_300
    assert by_rate[30]["wreath"] == 350_000 and by_rate[40]["wreath"] == 0
    assert result["totals"]["pretax"] == 3_401_000
    assert result["totals"]["payment"] == 2_280_100


def test_공제는_단계별로_들어간다():
    rows = [_row("01-2608-3-0001", 10_000_000, "컨설팅", rate=40)]
    base = shareholder_person(rows)["totals"]
    assert base["payout_base"] == 9_900_000 and base["pretax"] == 3_960_000

    q_stage = shareholder_person(rows, deductions=[
        {"kind": "VARIABLE_ADJ", "amount": 100_000}, {"kind": "UNPAID_CARRY", "amount": 200_000},
        {"kind": "DOC_EXPENSE", "amount": 300_000}, {"kind": "MISC", "amount": 400_000},
    ])["totals"]
    assert q_stage["payout_base"] == 9_900_000 - 1_000_000
    assert q_stage["variable_cost"] == 100_000 and q_stage["doc_expense"] == 300_000

    y_stage = shareholder_person(rows, deductions=[
        {"kind": "HANDLING", "amount": 50_000}, {"kind": "PENALTY", "amount": 400_000}, {"kind": "INSURANCE", "amount": 100_000},
    ])["totals"]
    assert y_stage["pretax"] == 3_960_000 + 50_000 - 500_000   # 3,510,000 (천원 단위라 절사 없음)

    ac_stage = shareholder_person(rows, deductions=[{"kind": "OTHER_DEDUCT", "amount": 74_400}])["totals"]
    assert ac_stage["other_deduct"] == 74_400
    assert ac_stage["payment"] == 3_960_000 - 1_188_000 - 118_800 - 74_400

    # 선지급은 엑셀처럼 세전(Y)에서 뺀다: 김형식 26.08 Y = ROUNDDOWN(R…) − 20,000,000
    advance = shareholder_person(rows, deductions=[{"kind": "ADVANCE_PAID", "amount": 1_000_000}])["totals"]
    assert advance["pretax"] == 2_960_000 and advance["advance_paid"] == 1_000_000
    assert advance["income_tax"] == 888_000
    # 가변비 환입(음수 가변비): 김남수 26.08 J = −3,289,000 → 산출액에 더한다
    credit = shareholder_person(rows, variable_auto=500_000, deductions=[{"kind": "VARIABLE_CREDIT", "amount": 800_000}])["totals"]
    assert credit["variable_cost"] == -300_000 and credit["payout_base"] == 9_900_000 + 300_000


def test_물건조사비는_세전에_더하고_법인카드는_일반쟁송을_뺀다():
    rows = [
        _row("01-2608-3-0001", 10_000_000, "컨설팅", rate=40, survey_fee=10_000),
        _row("01-2608-2-0002", 5_000_000, "일반쟁송", rate=40),
    ]
    totals = shareholder_person(rows)["totals"]
    assert totals["survey_fee"] == 10_000
    # 일반쟁송은 손배 1%·협회비 1.48% 다 든다: (9,900,000 + 4,876,000)×40% + 10,000 = 5,920,400 → 5,920,000
    assert totals["pretax"] == 5_920_000
    assert totals["card_limit"] == 500_000          # 일반쟁송 제외 10,000,000 × 5%


def test_요율이_없는_행은_상여를_만들지_않고_경고한다():
    result = shareholder_person([_row("01-2608-3-0001", 1_000_000, "담보", rate=None)])
    assert result["totals"]["bonus"] == 0
    assert result["blocks"][0]["rate"] is None
    assert any("요율" in w for w in result["warnings"])


def test_이영은_소속_합계는_지급률_70퍼센트와_소득세_30퍼센트를_쓴다():
    """공(이영은) 10% 건 9,166,600 → L 9,074,934 → 상여 907,493.4 → AD 634,900 → 190,000 → 19,000 → 425,900."""
    rows = [Row(doc_id="01-2508-4-0279", person="이영은", kind="COMMON", work_type="일반거래", fee=9_166_600, rate=10)]
    totals = associate_person(rows, pay_ratio=0.7, tax_rate=0.30)["totals"]
    assert totals["indemnity"] == 91_666 and totals["assessed"] == 9_074_934
    assert round(totals["bonus"], 1) == 907_493.4
    assert totals["pretax"] == 634_900
    assert totals["income_tax"] == 190_000 and totals["resident_tax"] == 19_000
    assert totals["payment"] == 425_900


def test_소속평가사_대형건은_한계누진으로_계산한다():
    """김혜수: 138,036,000 → L 136,655,640 → 41,579,474 → AD 41,579,000 → 15% 6,236,000 → 623,600 → 34,719,400."""
    rows = [Row(doc_id="01-2510-4-0348", person="김혜수", kind="ASSOCIATE", work_type="일반거래", fee=138_036_000)]
    totals = associate_person(rows, pay_ratio=1.0, tax_rate=0.15)["totals"]
    assert totals["assessed"] == 136_655_640
    assert totals["bonus"] == 41_579_474
    assert totals["pretax"] == 41_579_000
    assert (totals["income_tax"], totals["resident_tax"], totals["payment"]) == (6_236_000, 623_600, 34_719_400)


def test_공통건은_기본_3퍼센트이고_행별_요율을_덮어쓸_수_있다():
    """공(김기석) 가격자문 10,000 → L 9,900 → 297 (26.08 평·동 r8)."""
    three = Row(doc_id="01-2606-6-0406", person="김기석", kind="COMMON", work_type="가격자문", fee=10_000)
    assert round(associate_person([three])["totals"]["bonus"], 2) == 297
    four = Row(doc_id="01-2606-6-0406", person="김기석", kind="COMMON", work_type="가격자문", fee=10_000, rate=4)
    assert round(associate_person([four])["totals"]["bonus"], 2) == 396
    # 소속 손배는 담보 1.5% 그 외 1% 를 ROUND, 법인카드는 합계(I) 기준 5%
    result = associate_person([Row(doc_id="d", person="김기도", kind="ASSOCIATE", work_type="담보", fee=560_800)])
    assert result["totals"]["indemnity"] == 8_412 and result["totals"]["card_limit"] == 28_000


def test_평동_공제도_단계별로_들어간다():
    rows = [Row(doc_id="d", person="정인수", kind="ASSOCIATE", work_type="담보", fee=1_000_000)]
    base = associate_person(rows)["totals"]           # L 985,000 → 197,000 → AD 197,000
    assert base["pretax"] == 197_000
    totals = associate_person(rows, deductions=[
        {"kind": "HANDLING", "amount": 10_000}, {"kind": "WREATH", "amount": 80_000}, {"kind": "OTHER_DEDUCT", "amount": 5_000},
    ])["totals"]
    assert totals["pretax"] == 127_000                # ROUNDDOWN(197,000 + 10,000 − 80,000, -3)
    assert totals["payment"] == 127_000 - 19_000 - 1_900 - 5_000


def test_감정서경비_환입은_당월감정서경비에서_뺀다():
    """송정선 26.03 O = −1,500,000 — 앞 달에 뺀 잡급을 돌려준 것. 대장에는 양수 + EXPENSE_CREDIT 로 둔다."""
    result = shareholder_person(
        [Row(doc_id="01-2607-3-0001", person="송정선", work_type="담보", fee=10_000_000, rate=40)],
        deductions=[{"kind": "DOC_EXPENSE", "amount": 40_000}, {"kind": "EXPENSE_CREDIT", "amount": 1_500_000}],
    )
    assert result["totals"]["doc_expense"] == -1_460_000


def test_서명료_행은_손배_협회비를_내지_않고_공통건_하한은_30만이다():
    """캡스톤 01-2606-5-0085: 안창덕 2.5% 서명료 행은 H 만 (엑셀 r375 에 K·P 수식 없음). 국공유재산·법원 공통건은 정액 300,000 하한."""
    signer = shareholder_person([Row(doc_id="01-2606-5-0085", person="안창덕", work_type="일반거래", fee=125_000, rate=40, signing=True)])
    row = signer["rows"][0]
    assert row["assessed"] == 125_000 and row["indemnity"] == 0 and row["association_fee"] == 0
    floor = associate_person([Row(doc_id="01-2606-1-0386", person="김치암", kind="COMMON", work_type="국공유재산", fee=1_291_000, rate=15, min_bonus=300_000)])
    assert floor["rows"][0]["bonus"] == 300_000                                   # 1,278,090 × 15% = 191,713 < 하한
    big = associate_person([Row(doc_id="01-2603-1-0002", person="김정원", kind="COMMON", work_type="국공유재산", fee=46_317_150, rate=15, min_bonus=300_000)])
    assert big["rows"][0]["bonus"] > 6_000_000
