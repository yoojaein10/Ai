"""리포트 조립 (2단계 13) — 후보 → 행 → 사람별 합계. 원천은 전부 가짜로 바꿔 규칙만 본다."""

from dataclasses import dataclass, field
from datetime import date

from app.services.bonus.report import Readers, bonus_report_v2
from app.services.bonus.schedule import RateBlock

PERIOD = "202608"  # 입금월 2026-07


def _cand(doc, fee, *, outstanding=0, last=date(2026, 7, 10), billed=None, received=None, sources=("SALES", "PAID")):
    return {
        "doc_id": doc, "sources": list(sources), "fee_total": fee, "fee_month": fee, "first_sale_date": last,
        "billed": fee * 1.1 if billed is None else billed, "received": fee * 1.1 if received is None else received,
        "outstanding": outstanding, "last_received_date": last, "pay_result": "입금완료", "paid_date": last,
    }


def _meta(work="담보", manager="강무진", customer="어느 은행", receipt=date(2026, 6, 10), **extra):
    return {
        "receipt_date": receipt, "work_type": work, "customer_name": customer, "manager": manager,
        "investigator": "", "base_fee": 0, "cut_fee": 0, "land_fee": 0, "travel_billed": 0, "travel_claimed": 0,
        "survey_fee": 0, "ratio_names": None, "ratio_values": None, **extra,
    }


@dataclass
class Fake:
    """readers 가 돌려줄 값 — 필요한 것만 채운다."""
    candidates: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    gaprice: dict = field(default_factory=dict)
    booking: dict = field(default_factory=dict)
    claims: dict = field(default_factory=dict)
    variable: dict = field(default_factory=dict)
    active: set = field(default_factory=lambda: {"강무진", "김형식", "조근렬", "김기석", "이영은", "안창덕", "유승민"})
    depts: dict = field(default_factory=dict)
    manual_shares: dict = field(default_factory=dict)
    schedule: dict = field(default_factory=lambda: {
        "강무진": [RateBlock("강무진", date(2021, 3, 1), None, 40.0)],
        "김형식": [RateBlock("김형식", date(2021, 3, 1), None, 40.0)],
        "조근렬": [RateBlock("조근렬", date(2021, 3, 1), None, 40.0)],
        "김기석": [RateBlock("김기석", date(2024, 7, 1), None, 30.0)],
        "유승민": [RateBlock("유승민", date(2025, 2, 18), None, 40.0)],
    })
    persons: list = field(default_factory=lambda: [
        {"person": "강무진", "kind": "SHAREHOLDER", "pay_ratio": 1.0, "tax_rate": 0.30, "memo": None},
        {"person": "김형식", "kind": "SHAREHOLDER", "pay_ratio": 1.0, "tax_rate": 0.30, "memo": None},
        {"person": "조근렬", "kind": "SHAREHOLDER", "pay_ratio": 1.0, "tax_rate": 0.30, "memo": None},
        {"person": "김기석", "kind": "SHAREHOLDER", "pay_ratio": 1.0, "tax_rate": 0.30, "memo": None},
        {"person": "유승민", "kind": "SHAREHOLDER", "pay_ratio": 1.0, "tax_rate": 0.30, "memo": None},
        {"person": "이영은", "kind": "ASSOCIATE", "pay_ratio": 0.7, "tax_rate": 0.30, "memo": None},
    ])
    paid: dict = field(default_factory=dict)
    carry: "dict | None" = field(default_factory=dict)
    status: "str | None" = None
    result_rows: list = field(default_factory=list)
    deductions: dict = field(default_factory=dict)
    overrides: dict = field(default_factory=dict)
    expenses: tuple = field(default_factory=lambda: ({}, []))
    pending: dict = field(default_factory=dict)
    voucher_rows: list = field(default_factory=list)
    synced: list = field(default_factory=list)
    simple: tuple = (0.0, 0)

    def readers(self) -> Readers:
        return Readers(
            candidate_docs=lambda db, a, b: self.candidates,
            simple_appraisal=lambda db, a, b: self.simple,
            voucher_expenses=lambda db, a, b, known_docs=None: self.expenses,
            doc_meta=lambda db, docs: {d: self.meta[d] for d in docs if d in self.meta},
            gaprice_allocations=lambda db, docs: self.gaprice,
            booking_shares=lambda db, docs: self.booking,
            survey_claims=lambda db, docs: self.claims,
            variable_costs=lambda db, standmon: self.variable,
            active_names=lambda db: self.active,
            dept_by_name=lambda db: self.depts,
            load_shares=lambda db, docs: self.manual_shares,
            load_schedule=lambda db: self.schedule,
            list_persons=lambda db: self.persons,
            already_paid=lambda db, docs: self.paid,
            carry_in=lambda db, period: self.carry,
            close_status=lambda db, period: self.status,
            load_result=lambda db, period: self.result_rows,
            load_deductions=lambda db, period: self.deductions,
            load_overrides=lambda db, period: self.overrides,
            pending_deductions=lambda db: self.pending,
            voucher_expense_rows=lambda db, a, b: self.voucher_rows,
            sync_voucher_candidates=lambda db, rows, ratios, **kw: self.synced.append((rows, ratios, kw.get("apply_period"))) or [],
        )


def _report(fake, **kw):
    return bonus_report_v2(None, PERIOD, readers=fake.readers(), **kw)


def _person(report, name, group="shareholders"):
    return next(p for p in report[group] if p["name"] == name)


def test_기본_흐름_후보가_사람별_행과_합계가_된다():
    fake = Fake(
        candidates=[_cand("01-2607-3-0001", 10_000_000), _cand("01-2503-5-0042", 40_000_000)],
        meta={"01-2607-3-0001": _meta("담보", "강무진"), "01-2503-5-0042": _meta("컨설팅", "김형식,강무진,조근렬", "신림 (김5 강2.5 조2.5)")},
        manual_shares={"01-2503-5-0042": {
            "김형식": {"share_pct": 50.0, "bc_pct": None, "source": "SEED", "note": None},
            "강무진": {"share_pct": 25.0, "bc_pct": None, "source": "SEED", "note": None},
            "조근렬": {"share_pct": 25.0, "bc_pct": None, "source": "SEED", "note": None},
        }},
        variable={"강무진": 100_000},
    )
    report = _report(fake)
    assert report["period"] == "202608" and report["perf_month"] == "202607" and report["status"] == "OPEN"
    kang = _person(report, "강무진")
    assert [(r["doc_id"], r["fee"], r["share_source"], r["rate"]) for r in kang["rows"]] == [
        ("01-2503-5-0042", 10_000_000, "SEED", 40.0), ("01-2607-3-0001", 10_000_000, "EQUAL", 40.0),
    ]
    assert kang["totals"]["variable_cost"] == 100_000
    assert _person(report, "김형식")["rows"][0]["fee"] == 20_000_000
    assert {p["name"] for p in report["shareholders"]} == {"강무진", "김형식", "조근렬"}
    assert report["held"] == [] and report["associates"] == []
    summary = {row["name"]: row for row in report["summary"]}
    assert summary["강무진"]["payment"] == kang["totals"]["payment"]
    assert summary["강무진"]["pretax"] == kang["totals"]["pretax"]


def test_보류_사유가_전해지고_INCLUDE_오버라이드는_보류를_끌어온다():
    unpaid = _cand("01-2604-4-0153", 8_471_000, outstanding=9_318_100, last=None)
    fake = Fake(candidates=[unpaid], meta={"01-2604-4-0153": _meta("일반거래", "강무진")})
    held = _report(fake)["held"]
    assert held == [{"doc_id": "01-2604-4-0153", "reason": "HELD_UNPAID", "fee_total": 8_471_000, "outstanding": 9_318_100, "last_received_date": None}]

    fake.overrides = {("01-2604-4-0153", "강무진"): {"INCLUDE": None}}
    report = _report(fake)
    row = _person(report, "강무진")["rows"][0]
    assert row["doc_id"] == "01-2604-4-0153" and "INCLUDED_BY_OVERRIDE" in row["flags"]
    assert report["held"] == []


def test_후보에_없는_감정서를_포함하면_수수료_오버라이드가_필요하다():
    fake = Fake(candidates=[], meta={"01-2604-3-1076": _meta("담보", "유승민")},
                overrides={("01-2604-3-1076", "유승민"): {"INCLUDE": None, "FEE": 580_000}})
    report = _report(fake)
    row = _person(report, "유승민")["rows"][0]
    assert row["fee"] == 580_000 and "NO_CANDIDATE" in row["flags"]
    fake.overrides = {("01-2604-3-1076", "유승민"): {"INCLUDE": None}}
    report = _report(fake)
    assert any("FEE" in w for w in report["warnings"])


def test_EXCLUDE_는_그_사람의_행만_뺀다():
    fake = Fake(candidates=[_cand("01-2503-5-0042", 40_000_000)],
                meta={"01-2503-5-0042": _meta("컨설팅", "김형식,강무진")},
                overrides={("01-2503-5-0042", "강무진"): {"EXCLUDE": None}})
    report = _report(fake)
    assert {p["name"] for p in report["shareholders"]} == {"김형식"}
    assert _person(report, "김형식")["rows"][0]["fee"] == 20_000_000    # 균등 지분은 담당자 수 기준 그대로


def test_기지급_감정서는_차액만_행이_되고_같으면_행이_없다():
    fake = Fake(candidates=[_cand("01-2603-1-0155", 300_000), _cand("01-2603-1-0156", 284_000)],
                meta={"01-2603-1-0155": _meta("국공유재산", "안창덕"), "01-2603-1-0156": _meta("국공유재산", "안창덕")},
                schedule={"안창덕": [RateBlock("안창덕", date(2021, 3, 1), None, 40.0)]},
                persons=[{"person": "안창덕", "kind": "SHAREHOLDER", "pay_ratio": 1.0, "tax_rate": 0.30, "memo": None}],
                paid={("01-2603-1-0155", "안창덕"): 284_000, ("01-2603-1-0156", "안창덕"): 284_000})
    report = _report(fake)
    rows = _person(report, "안창덕")["rows"]
    assert [(r["doc_id"], r["fee"], "ADJUST" in r["flags"]) for r in rows] == [("01-2603-1-0155", 16_000, True)]
    assert any(h["reason"] == "ALREADY_PAID" and h["doc_id"] == "01-2603-1-0156" for h in report["held"])


def test_요율_구간_밖이면_경고하고_요율이_없으면_상여를_안_만든다():
    """닫힌 구간 뒤에 접수된 건(구간 사이 틈)은 가장 최근 블록으로 폴백하고 경고한다."""
    fake = Fake(candidates=[_cand("01-2607-3-0001", 1_000_000)],
                meta={"01-2607-3-0001": _meta("담보", "강무진", receipt=date(2020, 6, 1))},
                schedule={"강무진": [RateBlock("강무진", date(2019, 1, 1), date(2019, 12, 31), 40.0)]})
    report = _report(fake)
    row = _person(report, "강무진")["rows"][0]
    assert row["rate"] == 40.0 and row["rate_source"] == "FALLBACK_LATEST" and row["block_from"] == date(2019, 1, 1)
    assert any("강무진" in w and "요율" in w for w in report["warnings"])

    # 요율표가 아예 없는 주주는 소속 누진으로 계산하고 알린다 (윤도: 평·동 시트 '주주 합계'로만 나온다)
    fake.schedule = {}
    report = _report(fake)
    assert report["shareholders"] == []
    row = _person(report, "강무진", "associates")["rows"][0]
    assert row["kind"] == "ASSOCIATE" and "NO_SCHEDULE" in row["flags"]
    assert any("강무진" in w and "요율표" in w for w in report["warnings"])


def test_퇴사자는_보류이고_INCLUDE_하면_들어온다():
    fake = Fake(candidates=[_cand("01-2606-1-0382", 6_675_016)], meta={"01-2606-1-0382": _meta("정비사업", "김주환")},
                schedule={"김주환": [RateBlock("김주환", None, None, 40.0)]}, active={"강무진"})
    report = _report(fake)
    assert report["shareholders"] == []
    assert report["held"] == [{"doc_id": "01-2606-1-0382", "person": "김주환", "reason": "RETIRED", "fee": 6_675_016}]
    fake.overrides = {("01-2606-1-0382", "김주환"): {"INCLUDE": None}}
    report = _report(fake)
    assert _person(report, "김주환")["retired"] is True and report["held"] == []


def test_공통건은_주주면_공통건_묶음으로_소속이면_소속_합계로_간다():
    fake = Fake(
        candidates=[_cand("01-2606-6-0406", 10_000), _cand("01-2508-4-0279", 9_166_600)],
        meta={"01-2606-6-0406": _meta("가격자문", "공(김기석)"), "01-2508-4-0279": _meta("일반거래", "공(이영은)")},
        overrides={("01-2508-4-0279", "이영은"): {"RATE": 10}},
    )
    report = _report(fake)
    assert report["shareholders"] == []                     # 김기석은 공통건뿐이라 주주표에 행이 없다
    common = _person(report, "김기석", "common")
    assert common["rows"][0]["kind"] == "COMMON" and round(common["totals"]["bonus"], 2) == 297
    assert common["totals"]["tax_rate"] == 0.30 and common["totals"]["pay_ratio"] == 1.0
    lee = _person(report, "이영은", "associates")
    assert lee["rows"][0]["kind"] == "COMMON" and lee["rows"][0]["rate"] == 10
    assert lee["totals"]["payment"] == 425_900                # 이영은 70%·30% 골든


def test_우리은행_공동유치는_지분표가_있으면_주주_행이다():
    fake = Fake(candidates=[_cand("01-2606-3-2029", 2_000_000)],
                meta={"01-2606-3-2029": _meta("담보", "공(김형식)", "우리은행 여신업무센터(가든파이브지점) 50%")},
                manual_shares={"01-2606-3-2029": {"김형식": {"share_pct": 50.0, "bc_pct": None, "source": "SEED", "note": None}}})
    report = _report(fake)
    row = _person(report, "김형식")["rows"][0]
    assert row["kind"] == "SHAREHOLDER" and row["fee"] == 1_000_000 and row["share_source"] == "SEED"
    assert report["common"] == []


def test_승인_배분이_전부면_배분받은_사람만_행이_된다():
    fake = Fake(candidates=[_cand("01-2503-5-0042", 40_000_000)],
                meta={"01-2503-5-0042": _meta("컨설팅", "김형식,강무진,조근렬")},
                gaprice={"01-2503-5-0042": {"김형식": 20_000_000, "강무진": 20_000_000}})
    report = _report(fake)
    assert {p["name"] for p in report["shareholders"]} == {"김형식", "강무진"}
    assert _person(report, "강무진")["rows"][0]["share_source"] == "IN_PRICE"
    assert _person(report, "강무진")["rows"][0]["fee"] == 20_000_000


def test_전월_마감이_없으면_이월_0_과_경고이고_있으면_뺀다():
    fake = Fake(candidates=[_cand("01-2607-3-0001", 10_000_000)], meta={"01-2607-3-0001": _meta("담보", "강무진")}, carry=None)
    report = _report(fake)
    assert any("마감" in w and "이월" in w for w in report["warnings"])
    assert _person(report, "강무진")["totals"]["carry_in"] == 0
    fake.carry = {"강무진": 2_693_660}
    assert _person(_report(fake), "강무진")["totals"]["carry_in"] == 2_693_660


def test_마감된_달은_스냅샷을_돌려준다():
    fake = Fake(status="CLOSED", result_rows=[{"period": "202608", "person": "강무진", "kind": "SHAREHOLDER", "doc_id": None, "payment": 1}])
    report = _report(fake)
    assert report["status"] == "CLOSED" and report["rows"] == fake.result_rows
    assert report["shareholders"][0]["totals"]["payment"] == 1 and report["summary"][0]["payment"] == 1


def test_마감된_달도_개인_범위는_본인_것만_본다():
    """2026-08-27: 스냅샷 경로가 scope_person 을 건너뛰어 남의 지급액이 보이던 구멍."""
    fake = Fake(status="CLOSED", result_rows=[
        {"period": "202608", "person": "강무진", "kind": "SHAREHOLDER", "doc_id": None, "payment": 1},
        {"period": "202608", "person": "김형식", "kind": "SHAREHOLDER", "doc_id": None, "payment": 2},
        {"period": "202608", "person": "김형식", "kind": "SHAREHOLDER", "doc_id": "01-2607-3-0001", "fee": 5},
    ])
    report = _report(fake, scope_person="강무진")
    assert [p["name"] for p in report["shareholders"]] == ["강무진"]
    assert [s["name"] for s in report["summary"]] == ["강무진"]
    full = _report(fake)
    assert {p["name"] for p in full["shareholders"]} == {"강무진", "김형식"}


def test_경비_전표는_자동으로_빼지_않고_대장_후보로_넘긴다():
    """2026-08-27: 전표 자동 반영을 끈다 — 같은 비용이 대장(엑셀·수기)과 두 번 빠지던 것. 전표는 대기 후보가 된다."""
    voucher = {"key": "20260806:00012:1", "voucher_date": date(2026, 8, 6), "account_name": "세금과공과금", "amount": 40_000,
               "remark": "01-2607-3-0001 수입인지", "doc_ids": ["01-2607-3-0001"]}
    company = {"key": "20260810:00014:1", "voucher_date": date(2026, 8, 10), "account_name": "세금과공과금", "amount": 10_068_920,
               "remark": "26.7월분 주민세 종업원분", "doc_ids": []}
    named = {"key": "20260811:00015:1", "voucher_date": date(2026, 8, 11), "account_name": "세금과공과금", "amount": 20_000,
             "remark": "수택동 재개발정비사업조합 수입인지-김형식", "doc_ids": []}
    fake = Fake(candidates=[_cand("01-2607-3-0001", 10_000_000)], meta={"01-2607-3-0001": _meta("담보", "강무진")},
                voucher_rows=[voucher, company, named])
    report = _report(fake)
    assert _person(report, "강무진")["totals"]["doc_expense"] == 0                    # 자동 반영 없음
    assert [n["remark"] for n in report["expense_notes"]] == ["26.7월분 주민세 종업원분"]   # 감정서도 사람도 없는 전표만 참고
    assert report["expense_notes"][0]["voucher_date"] == "2026-08-10"
    rows, ratios, apply_period = fake.synced[0]
    assert ratios == {("01-2607-3-0001", "강무진"): 100.0} and apply_period == PERIOD   # 감정서 공제는 바로 적용
    assert [r.get("persons") for r in rows] == [None, [], ["김형식"]]                # 감정서 없는 전표는 적요 이름이 붙는다
    fake.synced.clear()
    _report(fake, scope_person="강무진")
    assert fake.synced == []                                                          # 개인 범위 조회는 후보를 만들지 않는다


def test_이번_달_행에_없는_감정서_전표는_적요_이름_아니면_담당자에게_후보로_간다():
    """엑셀 감정서관련비용공제내역은 감정서가 그 달 상여에 없어도 담당자에게 뺐다 — 같은 규칙."""
    fake = Fake(candidates=[_cand("01-2607-3-0001", 10_000_000)],
                meta={"01-2607-3-0001": _meta("담보", "강무진"), "01-2606-5-0094": _meta("담보", "김형식"), "01-2605-4-0180": _meta("일반거래", "조근렬")},
                voucher_rows=[
                    {"key": "k1", "voucher_date": date(2026, 8, 6), "account_name": "세금과공과금", "amount": 20_000, "remark": "01-2606-5-0094 수입인지", "doc_ids": ["01-2606-5-0094"]},
                    {"key": "k2", "voucher_date": date(2026, 8, 7), "account_name": "세금과공과금", "amount": 150_000, "remark": "01-2605-4-0180 전자수입인지-강무진,유승민", "doc_ids": ["01-2605-4-0180"]},
                    {"key": "k3", "voucher_date": date(2026, 8, 8), "account_name": "세금과공과금", "amount": 5_000, "remark": "01-2607-3-0001 수입인지-김형식", "doc_ids": ["01-2607-3-0001"]},
                ])
    _report(fake)
    _, ratios, _ = fake.synced[0]
    assert ratios == {
        ("01-2607-3-0001", "강무진"): 100.0,                          # 이번 달 행 → 행 지분 (적요 이름보다 우선)
        ("01-2606-5-0094", "김형식"): 100.0,                          # 행에 없음 → 감정서 담당자
        ("01-2605-4-0180", "강무진"): 50.0, ("01-2605-4-0180", "유승민"): 50.0,   # 적요 끝의 이름들에게 균등
    }


def test_우리은행_공_주주이사는_50_지분_주주_행이고_다른_공_은_공통건이다():
    """재무팀 규칙 4: 유치자가 공(주주이사)인 우리은행 건은 순수수료 50% (엑셀 26.05~26.08 공(신상우)·공(조경미) 전부 50%)."""
    fake = Fake(candidates=[_cand("01-2604-3-1108", 2_000_000), _cand("01-2607-6-0433", 100_000)],
                meta={"01-2604-3-1108": _meta("담보", "공(유승민)", "우리은행 여신업무센터(시흥동지점)"),
                      "01-2607-6-0433": _meta("가격자문", "공(김기석)", "신한은행 백궁지점장")})
    report = _report(fake)
    woori = _person(report, "유승민")["rows"][0]
    assert (woori["fee"], woori["share_pct"], woori["share_source"], woori["kind"]) == (1_000_000, 50.0, "WOORI", "SHAREHOLDER")
    common = _person(report, "김기석", "common")["rows"][0]
    assert common["kind"] == "COMMON" and common["applied_rate"] == 3.0


def test_서명료_2_5_는_주인_토지조사비에서_빼고_손배_협회비는_주인이_전액_낸다():
    """재무팀 규칙 3: 캡스톤 건 안창덕 2.5% 서명료 — 협회비·손배는 김정원이 전액 (엑셀 26.08 r80/r375)."""
    fake = Fake(candidates=[_cand("01-2606-5-0085", 5_000_000)],
                meta={"01-2606-5-0085": _meta("일반거래", "김정원", "캡스톤자산운용(주)")},
                manual_shares={"01-2606-5-0085": {
                    "김정원": {"share_pct": 100.0, "bc_pct": None, "source": "SEED", "note": None},
                    "안창덕": {"share_pct": 2.5, "bc_pct": None, "source": "SEED", "note": "캡스톤자산운용㈜ (2.5%)"},
                }},
                active={"김정원", "안창덕"},
                persons=[{"person": "김정원", "kind": "SHAREHOLDER", "pay_ratio": 1.0, "tax_rate": 0.30, "memo": None},
                         {"person": "안창덕", "kind": "SHAREHOLDER", "pay_ratio": 1.0, "tax_rate": 0.30, "memo": None}],
                schedule={"김정원": [RateBlock("김정원", date(2021, 3, 1), None, 40.0)], "안창덕": [RateBlock("안창덕", date(2021, 3, 1), None, 40.0)]})
    report = _report(fake)
    owner = _person(report, "김정원")["rows"][0]
    assert (owner["fee"], owner["assessed"], owner["indemnity"], owner["association_fee"]) == (5_000_000, 4_875_000, 50_000, 74_000)
    assert "SIGNING_PAID" in owner["flags"]
    signer = _person(report, "안창덕")["rows"][0]
    assert (signer["fee"], signer["assessed"], signer["indemnity"], signer["association_fee"]) == (125_000, 125_000, 0, 0)
    assert "SIGNING_FEE" in signer["flags"]


def test_산업은행_건은_담당_공_4_와_윤도_23_이_따로_받고_국공유재산_공통건은_하한_30만이다():
    """재무팀 규칙 7: KDB 건은 공(장재원) 4% + 윤도 23% (엑셀 26.08 평·동 r27~29 / r33~35). 규칙 6: 국공유재산 정액 300,000 하한."""
    fake = Fake(candidates=[_cand("01-2604-3-1240", 2_327_200), _cand("01-2606-1-0386", 1_291_000)],
                meta={"01-2604-3-1240": _meta("담보", "윤도,공(장재원)", "KDB산업은행 김포지점장"),      # APW 담당 표기 그대로
                      "01-2606-1-0386": _meta("국공유재산", "공(김치암)", "한국토지주택공사 경기북부지역본부")},
                active={"장재원", "윤도", "김치암"},
                persons=[{"person": p, "kind": "SHAREHOLDER", "pay_ratio": 1.0, "tax_rate": 0.30, "memo": None} for p in ("장재원", "윤도", "김치암")])
    report = _report(fake)
    jang = _person(report, "장재원", "common")["rows"][0]
    yoon = _person(report, "윤도", "common")["rows"][0]
    assert (jang["applied_rate"], jang["rate_source"], jang["fee"]) == (4.0, "CUSTOMER", 2_327_200)     # 공(X) 도 전액 기준
    assert (yoon["applied_rate"], yoon["rate_source"], yoon["doc_id"], yoon["fee"]) == (23.0, "CHANNEL", "01-2604-3-1240", 2_327_200)
    assert all(p["name"] != "윤도" for p in report["shareholders"] + report["associates"])              # 지분 행으로는 안 나온다
    # 요율표 없는 채널 주인의 공제(자동차세 107,480)는 빈 주주 블록이 아니라 공통건 합계에서 빠진다 (엑셀 평·동 AC)
    fake.deductions = {"윤도": [{"kind": "INSURANCE", "amount": 107_480}]}
    report = _report(fake)
    assert _person(report, "윤도", "common")["totals"]["wreath"] == 107_480
    assert all(p["name"] != "윤도" for p in report["shareholders"])
    kim = _person(report, "김치암", "common")["rows"][0]
    assert (kim["applied_rate"], kim["bonus"]) == (15.0, 300_000)


def test_scope_person_은_그_사람만_남긴다():
    fake = Fake(candidates=[_cand("01-2607-3-0001", 10_000_000), _cand("01-2607-3-0002", 5_000_000)],
                meta={"01-2607-3-0001": _meta("담보", "강무진"), "01-2607-3-0002": _meta("담보", "김형식")})
    report = _report(fake, scope_person="김형식")
    assert [p["name"] for p in report["shareholders"]] == ["김형식"]
    assert [row["name"] for row in report["summary"]] == ["김형식"]


def test_행의_순수수료는_기초수수료_빼기_절사이고_전표는_후보_판정에만_쓴다():
    """엑셀 F = 기초수수료 − 절사금액 (7/7 실측). 전표 4010001 은 여비·실비까지 든 수수료합계라 더 크다."""
    fake = Fake(candidates=[_cand("01-2606-3-2095", 1_071_000)],
                meta={"01-2606-3-2095": _meta("담보", "김예린", base_fee=949_854, cut_fee=4)},
                schedule={"김예린": [RateBlock("김예린", date(2022, 7, 1), None, 30.0)]},
                persons=[{"person": "김예린", "kind": "SHAREHOLDER", "pay_ratio": 1.0, "tax_rate": 0.30, "memo": None}],
                active={"김예린"})
    row = _person(_report(fake), "김예린")["rows"][0]
    assert row["fee"] == 949_850


def test_공통_담당자는_지분을_나누지_않고_전액의_3퍼센트를_따로_받는다():
    """'윤도,공(장재원)': 윤도가 100%, 장재원은 공통건(전액 L × 3%). Booking 의 공(장재원) 50% 는 무시한다."""
    fake = Fake(candidates=[_cand("01-2604-3-1240", 2_327_200)],
                meta={"01-2604-3-1240": _meta("담보", "윤도,공(장재원)", base_fee=2_327_200)},
                booking={"01-2604-3-1240": {"윤도": 50.0, "공(장재원)": 50.0}},
                schedule={"윤도": [RateBlock("윤도", None, None, 40.0)], "장재원": [RateBlock("장재원", None, None, 40.0)]},
                persons=[{"person": "윤도", "kind": "SHAREHOLDER", "pay_ratio": 1.0, "tax_rate": 0.30, "memo": None},
                         {"person": "장재원", "kind": "SHAREHOLDER", "pay_ratio": 1.0, "tax_rate": 0.30, "memo": None}],
                active={"윤도", "장재원"})
    report = _report(fake)
    yun = _person(report, "윤도")["rows"][0]
    assert yun["fee"] == 2_327_200 and yun["share_pct"] == 100 and yun["kind"] == "SHAREHOLDER"
    jang = _person(report, "장재원", "common")["rows"][0]
    assert jang["fee"] == 2_327_200 and jang["kind"] == "COMMON" and jang["share_source"] == "COMMON"
    assert [p["name"] for p in report["shareholders"]] == ["윤도"]


def test_승인_배분의_공_이름은_공통건_사람이지_지분_사람이_아니다():
    fake = Fake(candidates=[_cand("01-2603-3-0907", 793_000)],
                meta={"01-2603-3-0907": _meta("담보", "공(정인수)", base_fee=793_000)},
                gaprice={"01-2603-3-0907": {"공(정인수)": 793_000}},
                persons=[{"person": "정인수", "kind": "ASSOCIATE", "pay_ratio": 1.0, "tax_rate": 0.15, "memo": None}],
                schedule={}, active={"정인수"})
    report = _report(fake)
    rows = _person(report, "정인수", "associates")["rows"]
    assert [(r["kind"], r["fee"]) for r in rows] == [("COMMON", 793_000)]
    assert report["shareholders"] == [] and report["common"] == []


def test_소속이었다가_주주가_된_사람은_접수일이_요율_구간에_들면_주주_행이다():
    """정인수 '2026년 7월~' 30%: 7월 접수 건은 주주 30%, 그 전 접수 건은 소속(누진)."""
    fake = Fake(candidates=[_cand("01-2607-3-0001", 1_000_000), _cand("01-2604-3-1379", 543_400)],
                meta={"01-2607-3-0001": _meta("담보", "정인수", receipt=date(2026, 7, 5), base_fee=1_000_000),
                      "01-2604-3-1379": _meta("담보", "정인수", receipt=date(2026, 4, 10), base_fee=543_400)},
                schedule={"정인수": [RateBlock("정인수", date(2026, 7, 1), None, 30.0)]},
                persons=[{"person": "정인수", "kind": "ASSOCIATE", "pay_ratio": 1.0, "tax_rate": 0.15, "memo": None}],
                active={"정인수"})
    report = _report(fake)
    share = _person(report, "정인수")["rows"]
    assert [(r["doc_id"], r["rate"], r["rate_source"]) for r in share] == [("01-2607-3-0001", 30.0, "SCHEDULE")]
    assoc = _person(report, "정인수", "associates")["rows"]
    assert [(r["doc_id"], r["kind"]) for r in assoc] == [("01-2604-3-1379", "ASSOCIATE")]
    assert not any("정인수" in w and "요율" in w for w in report["warnings"])


def test_주주라도_첫_요율_구간_전에_접수된_건은_소속으로_본다():
    """김혜수 '2026년 7월~' 30% 주주: 그 전에 접수된 대형건은 소속 누진(15%)으로 — 당시엔 소속이었다."""
    fake = Fake(candidates=[_cand("01-2510-4-0348", 138_036_000)],
                meta={"01-2510-4-0348": _meta("일반거래", "김혜수", receipt=date(2025, 10, 1), base_fee=138_036_000)},
                schedule={"김혜수": [RateBlock("김혜수", date(2026, 7, 1), None, 30.0)]},
                persons=[{"person": "김혜수", "kind": "SHAREHOLDER", "pay_ratio": 1.0, "tax_rate": 0.30, "memo": None}],
                active={"김혜수"})
    report = _report(fake)
    assert report["shareholders"] == []
    row = _person(report, "김혜수", "associates")["rows"][0]
    assert row["kind"] == "ASSOCIATE" and "FORMER_ASSOCIATE" in row["flags"]
    assert _person(report, "김혜수", "associates")["totals"]["tax_rate"] == 0.15


def test_국민약식은_입금월_전표_합의_50_를_김형수_가격자문_한_줄로_넣는다():
    """관리번호 400* 약식평가수수료(4010002)는 APW 마스터에 없다 — 엑셀은 매달 '국민약식' 한 줄(김형수). 실측 9개월 중 7개월 정확히 50%."""
    fake = Fake(candidates=[], simple=(16_908_000.0, 381), active={"김형수"},
                persons=[{"person": "김형수", "kind": "SHAREHOLDER", "pay_ratio": 1.0, "tax_rate": 0.30, "memo": None}],
                schedule={"김형수": [RateBlock("김형수", date(2021, 3, 1), None, 40.0)]})
    report = _report(fake)
    row = _person(report, "김형수")["rows"][0]
    assert row["doc_id"] == "KB약식-202607" and row["work_type"] == "가격자문" and "SIMPLE_APPRAISAL" in row["flags"]
    assert (row["fee"], row["share_pct"], row["share_source"], row["rate"]) == (8_454_000, 50.0, "SIMPLE", 40.0)
    assert row["association_fee"] == 0 and row["indemnity"] == 8_454_000 * 0.015           # 가격자문: 협회비 면제, 손배 1.5%
    assert not any("찾지 못했습니다" in w for w in report["warnings"])
    assert _report(Fake(candidates=[], simple=(0.0, 0)))["shareholders"] == []              # 약식 전표가 없으면 행도 없다
