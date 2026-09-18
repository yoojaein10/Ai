from app.services.bonus import (
    _shareholder_totals,
    associate_doc_calc,
    classify_manager,
    extract_doc_ids,
    manager_names,
    person_share,
    shareholder_doc_calc,
    survey_payout,
)


def test_shareholder_totals_apply_deductions_and_row_rate():
    # 행이 하나면 공제 전액이 그 행에 안분 → 기존 '산출액 전체 × 요율'과 동일
    group = {
        "name": "강무진", "dept": "ju",
        "docs": [{
            "base_fee": 10_000_000, "assessed": 10_000_000,
            "indemnity": 150_000, "association_fee": 148_000,
            "rate": 45,
        }],
        "deductions": [
            {"label": "가변비", "amount": 1_000_000},
            {"label": "기타", "amount": 200_000},
        ],
    }
    totals = _shareholder_totals(group)["totals"]
    # 산출액 = 산정 - 손배 - 협회비 - 수기공제 합
    assert totals["payout_base"] == 10_000_000 - 150_000 - 148_000 - 1_200_000
    assert totals["deduction_total"] == 1_200_000
    assert totals["bonus_selected"] == round(totals["payout_base"] * 0.45, 2)


def test_shareholder_totals_row_rates_differ_per_doc():
    # 행별 요율: 공제는 행별 산출액 비율로 안분한 뒤 각 행의 요율을 곱한다
    group = {
        "name": "강무진", "dept": "ju",
        "docs": [
            {"base_fee": 0, "assessed": 6_000_000, "indemnity": 0,
             "association_fee": 0, "rate": 45},
            {"base_fee": 0, "assessed": 4_000_000, "indemnity": 0,
             "association_fee": 0, "rate": 30},
            {"base_fee": 0, "assessed": 1_000_000, "indemnity": 0,
             "association_fee": 0},  # 미저장 행은 기본 40%
        ],
        "deductions": [{"label": "가변비", "amount": 1_100_000}],
    }
    result = _shareholder_totals(group)
    docs, totals = result["docs"], result["totals"]
    # 안분: 6/11, 4/11, 1/11 → 600,000 / 400,000 / 100,000
    assert docs[0]["bonus_amount"] == round((6_000_000 - 600_000) * 0.45, 2)
    assert docs[1]["bonus_amount"] == round((4_000_000 - 400_000) * 0.30, 2)
    assert docs[2]["rate"] == 40
    assert docs[2]["bonus_amount"] == round((1_000_000 - 100_000) * 0.40, 2)
    assert totals["bonus_selected"] == round(
        docs[0]["bonus_amount"] + docs[1]["bonus_amount"] + docs[2]["bonus_amount"], 2
    )


def test_shareholder_totals_defaults_to_40_percent():
    group = {
        "name": "고세욱", "dept": "ju",
        "docs": [{
            "base_fee": 1_000_000, "assessed": 1_000_000,
            "indemnity": 10_000, "association_fee": 14_800,
        }],
    }
    result = _shareholder_totals(group)
    totals = result["totals"]
    assert result["docs"][0]["rate"] == 40
    assert totals["bonus_selected"] == round(totals["payout_base"] * 0.4, 2)
    assert totals["deduction_total"] == 0


def test_shareholder_settlement_matches_finance_sheet():
    # 재무팀 성과상여 시트(2026-06 강무진) 총계 재현:
    # 산정수수료 90,603,248 / 손배 906,032 / 협회비 415,329 / 가변비 936,175 / 화환 40,000
    group = {
        "name": "강무진", "dept": "ju",
        "docs": [{
            "base_fee": 90_603_248, "assessed": 90_603_248,
            "indemnity": 906_032, "association_fee": 415_329, "rate": 40,
            "variable_cost": 936_175, "wreath": 40_000,  # 행별 수기 입력
        }],
    }
    totals = _shareholder_totals(group)["totals"]
    # 상여기준액(10) = 4 - (가변비+손배+협회비) = 88,345,712
    assert totals["payout_base"] == 90_603_248 - 936_175 - 906_032 - 415_329
    # 산정상여금(11) = 기준액 × 40%
    assert totals["bonus_selected"] == round(totals["payout_base"] * 0.4, 2)
    # 세전(14) = 11 - 화환공제, 천원 절사 → 시트 값 35,298,000
    assert totals["pretax"] == 35_298_000
    assert totals["tax"] == round(35_298_000 * 0.33)
    assert totals["after_tax"] == totals["pretax"] - totals["tax"]
    assert totals["payment"] == totals["after_tax"]  # 기타공제 0
    # 카드(19) = 산정수수료 × 5% 천원 절사 → 시트 값 4,530,000
    assert totals["card"] == 4_530_000


def test_shareholder_settlement_expense_auto_and_override():
    def make_doc():
        return {
            "base_fee": 10_000_000, "assessed": 10_000_000, "indemnity": 0,
            "association_fee": 0, "expense_fee": 120_000, "survey_fee": 50_000,
        }
    # 감정서경비 미입력 → 행 자동값(공부발급비+기타실비 안분) 사용
    totals = _shareholder_totals({"name": "가", "dept": "ju", "docs": [make_doc()]})["totals"]
    assert totals["doc_expense_auto"] == 120_000
    assert totals["doc_expense"] == 120_000
    assert totals["payout_base"] == 10_000_000 - 120_000
    # 세전 = 상여 + 물건조사비(가산), 천원 절사
    assert totals["pretax"] == int(((10_000_000 - 120_000) * 0.4 + 50_000) / 1000) * 1000
    # 행별 수기 덮어쓰기(expense_override) → 입력값 사용
    doc = make_doc() | {"expense_override": 0}
    totals = _shareholder_totals({"name": "가", "dept": "ju", "docs": [doc]})["totals"]
    assert totals["doc_expense"] == 0
    assert totals["payout_base"] == 10_000_000


def test_shareholder_row_fields_deduct_per_row_before_rate():
    # 행별 수기(가변비 등)는 그 행에서만 차감 — 요율이 다른 행에 안분되지 않는다
    group = {
        "name": "나", "dept": "ju",
        "docs": [
            {"base_fee": 0, "assessed": 6_000_000, "indemnity": 0,
             "association_fee": 0, "rate": 45, "variable_cost": 1_000_000},
            {"base_fee": 0, "assessed": 4_000_000, "indemnity": 0,
             "association_fee": 0, "rate": 30},
        ],
    }
    result = _shareholder_totals(group)
    docs, totals = result["docs"], result["totals"]
    assert docs[0]["bonus_amount"] == round((6_000_000 - 1_000_000) * 0.45, 2)
    assert docs[1]["bonus_amount"] == round(4_000_000 * 0.30, 2)
    # 행별 상여기준액 합 = 합계 10.상여기준액
    assert docs[0]["payout_base"] == 5_000_000
    assert docs[1]["payout_base"] == 4_000_000
    assert totals["variable_cost"] == 1_000_000
    assert totals["payout_base"] == 9_000_000


def test_travel_shortfall_only_when_claims_exceed_billed():
    from app.services.bonus import travel_shortfall
    # 여비 40,000 / 조사자 청구 60,000 → 부족분 20,000 차감
    assert travel_shortfall(40_000, 60_000) == 20_000
    # 여비 10,000 / 청구 3,000 → 여비가 남으므로 차감 없음
    assert travel_shortfall(10_000, 3_000) == 0
    assert travel_shortfall(0, 40_000) == 40_000    # 여비 미청구인데 출장비 지급
    assert travel_shortfall(40_000, 0) == 0          # 청구 없음
    assert travel_shortfall(40_000, 40_000) == 0     # 정확히 일치


def test_shareholder_doc_calc_travel_fee_reduces_assessed():
    # 산정수수료 = 순수수료 - 부족출장비(여비) + 토지조사비. 손배·협회비는 순수수료 기준 유지
    calc = shareholder_doc_calc("담보", 1_000_000, 200_000, travel_fee=150_000)
    assert calc["assessed"] == 1_050_000
    assert calc["indemnity"] == 15_000
    assert calc["association_fee"] == 14_800


def test_person_share_scales_doc_expenses_by_ratio():
    share = person_share(
        person="김형식", in_price=4_000_000, base_fee=10_000_000, land_fee=100_000,
        ratio_names=None, ratio_values=None, doc_person_count=2,
        travel_fee=50_000, expense_fee=30_000,
    )
    assert share["travel_fee"] == 20_000   # 40% 안분
    assert share["expense_fee"] == 12_000


def test_survey_payout_sole_investigator_gets_uploaded_amount():
    # 평가자=조사자 단독 → 통합 업로드값 그대로 (issue 4번)
    assert survey_payout(10_000, {"정우종": 3_000}, ["정우종"]) == 10_000
    assert survey_payout(10_000, None, ["정우종"]) == 10_000


def test_survey_payout_subtracts_other_investigators_claims():
    # 평가자 정우종, 조사자 정우종+최병천 → 업로드값 - 최병천 청구
    assert survey_payout(10_000, {"정우종": 3_000, "최병천": 3_000}, ["정우종"]) == 7_000


def test_extract_doc_ids_normalizes_variants():
    assert extract_doc_ids("01-2511-4-0359/01-2511-3-3640 전자수입인지-김예린") == [
        "01-2511-4-0359", "01-2511-3-3640",
    ]
    assert extract_doc_ids("012607-4-0236-1 종로중앙") == ["01-2607-4-0236"]
    assert extract_doc_ids("화곡초일대 모아타운 전자수입인지") == []


def test_manager_names_unwraps_common_marker():
    assert manager_names("윤도,공(장재원)") == ["윤도", "장재원"]
    assert manager_names("정우종") == ["정우종"]
    assert manager_names(None) == []


def test_totals_person_variable_applies_to_summary_only():
    # 전월 가변비(사람 단위)는 합계(5)와 상여기준액에만 반영 — 행별 안분처럼 공제
    def make_doc(**extra):
        return {
            "base_fee": 1_000_000, "assessed": 1_000_000, "indemnity": 0,
            "association_fee": 0, "expense_fee": 0, "survey_fee": 0,
            "travel_fee": 0, "land_fee": 0,
        } | extra
    group = {"name": "테스트", "docs": [make_doc()], "variable_auto": 300_000}
    totals = _shareholder_totals(group)["totals"]
    assert totals["variable_cost"] == 300_000
    assert totals["variable_auto"] == 300_000
    assert totals["payout_base"] == 700_000
    # 행 상여 = (100만 - 안분 30만) × 40%
    assert group["docs"][0]["bonus_amount"] == 280_000
    # 행별 가변비 입력은 추가 조정분으로 합산된다
    group = {
        "name": "테스트", "docs": [make_doc(variable_cost=100_000)],
        "variable_auto": 300_000,
    }
    totals = _shareholder_totals(group)["totals"]
    assert totals["variable_cost"] == 400_000
    assert totals["payout_base"] == 600_000


def test_person_share_uses_approved_in_price_first():
    share = person_share(
        person="김형식", in_price=4_000_000, base_fee=10_000_000, land_fee=100_000,
        ratio_names="김형식,조경미", ratio_values="40,60", doc_person_count=2,
    )
    assert share["fee"] == 4_000_000
    assert share["land_fee"] == 40_000          # 배분 비율(40%)만큼 토지조사비도 안분
    assert share["estimated"] is False


def test_person_share_falls_back_to_charge_ratio():
    share = person_share(
        person="조경미", in_price=0, base_fee=10_000_000, land_fee=0,
        ratio_names="김형식,조경미", ratio_values="40,60", doc_person_count=2,
    )
    assert share["fee"] == 6_000_000
    assert share["estimated"] is True


def test_person_share_equal_split_when_no_ratio():
    share = person_share(
        person="아무개", in_price=0, base_fee=9_000_000, land_fee=0,
        ratio_names=None, ratio_values=None, doc_person_count=3,
    )
    assert share["fee"] == 3_000_000
    assert share["estimated"] is True


def test_classify_manager_common_extracts_inner_name():
    assert classify_manager("공(유영조)", None) == ("공통", "유영조")
    assert classify_manager("공(김기석)", "ju") == ("공통", "김기석")


def test_classify_manager_by_dept():
    assert classify_manager("김은집", "so") == ("평동", "김은집")
    assert classify_manager("강무진", "ju") == ("주주", "강무진")
    assert classify_manager("김형식", "sim") == ("주주", "김형식")
    # Seat_userinfo에 없는 사람은 주주로 두고 화면에서 부서 미확인 표시
    assert classify_manager("조영동", None) == ("주주", "조영동")


def test_shareholder_doc_calc_rates():
    # 담보: 손배 1.5%, 협회비 1.48%
    calc = shareholder_doc_calc("담보", 1_000_000, 0)
    assert calc["assessed"] == 1_000_000
    assert calc["indemnity"] == 15_000
    assert calc["association_fee"] == 14_800
    # 컨설팅: 손배 1%, 협회비 면제
    calc = shareholder_doc_calc("컨설팅", 10_000_000, 0)
    assert calc["indemnity"] == 100_000
    assert calc["association_fee"] == 0
    # 가격자문: 손배 1.5%, 협회비 면제. 토지조사비는 산정금액에 합산
    calc = shareholder_doc_calc("가격자문", 1_000_000, 200_000)
    assert calc["assessed"] == 1_200_000
    assert calc["indemnity"] == 15_000
    assert calc["association_fee"] == 0


def test_associate_doc_calc():
    # 평동: 주주와 같은 19컬럼 구조 — 손배는 담보 1.5% / 그외(가격자문 포함) 1% 반올림,
    # 협회비 면제. 산정수수료 = 순수 - 여비 + 토지, 손배는 상여기준액 단계에서 차감된다.
    calc = associate_doc_calc("담보", 754_400, 0)
    assert calc["indemnity"] == 11_316
    assert calc["assessed"] == 754_400
    assert calc["association_fee"] == 0.0
    calc = associate_doc_calc("가격자문", 10_000, 0, travel_fee=1_000)
    assert calc["indemnity"] == 100
    assert calc["assessed"] == 9_000


def test_associate_totals_default_20_percent_matches_old_formula():
    # 기존 '산정금액(합계-손배)×20%'와 동일해야 한다: 기준액 = 산정수수료 - 손배, 상여 = 기준액×20%
    from app.services.bonus import _associate_totals
    group = {
        "name": "김은집", "dept": "so",
        "docs": [{"base_fee": 754_400, **associate_doc_calc("담보", 754_400, 0)}],
    }
    result = _associate_totals(group)
    docs, totals = result["docs"], result["totals"]
    assert docs[0]["rate"] == 20
    assert totals["payout_base"] == 754_400 - 11_316  # = 기존 산정금액 743,084
    assert totals["bonus_selected"] == round(743_084 * 0.2, 2)
    assert totals["common_count"] == 0
