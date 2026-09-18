"""보수표 계산 회귀 — 이전 구현(D:/A10Bridge/tests/test_fee_review.py)에서 이식.

여기 박힌 기대값은 재무팀 엑셀과 전수 대사가 끝난 실측값이다. 계산식을 손볼 일이
생기면 이 테스트가 먼저 깨져야 한다.
"""

from datetime import date
from math import ceil, floor

import pytest

from app.services.fee_basis import (
    FEE_RULESET_CUTOFF,
    RULESET_CURRENT,
    RULESET_PREVIOUS,
    deviation,
    evaluate,
    fee_bands,
    ruleset_for,
)


def test_fee_band_boundaries():
    """1구간은 정액이라 밴드가 없고, 구간 선택은 `amount <= limit`(상한 포함)이다."""
    assert fee_bands(50_000_000) == (250_000, 250_000, 250_000)
    standard, lower, upper = fee_bands(500_000_000)
    assert standard == 745_000
    assert lower == 646_000
    assert upper == 844_000


def test_fee_band_pre_2025_revision_is_50k_lower():
    """종전표는 기준·하한·상한 세 값 모두 정확히 50,000원 낮다 (종전표 12건 전수 확인)."""
    current = fee_bands(2_532_000_000)
    previous = fee_bands(2_532_000_000, ruleset="pre-2025-334")
    assert previous == tuple(value - 50_000 for value in current)


def test_fee_band_matches_finance_team_workbook_examples():
    """재무팀 원본 엑셀 표본 5건 — 3·4·6구간과 최상위(1조 초과), 현행·종전 양쪽."""
    examples = [
        (542_851_140, "2025-334", (783_566.026, 676_852.8208, 890_279.2312)),
        (2_532_000_000, "pre-2025-334", (2_370_600, 1_936_480, 2_804_720)),
        (3_633_000_000, "2025-334", (3_301_400, 2_691_120, 3_911_680)),
        (15_774_420_000, "2025-334", (11_359_652, 9_137_721.6, 13_581_582.4)),
        (
            3_483_311_687_767,
            "2025-334",
            (555_226_168.7767, 444_230_935.02136, 666_221_402.53204),
        ),
    ]
    for amount, ruleset, expected in examples:
        actual = fee_bands(amount, ruleset=ruleset)
        assert actual == pytest.approx(expected, abs=0.001)


def test_bands_are_not_a_simple_80_120_percent_of_standard():
    """하한·상한을 기준수수료 × 0.8/1.2로 계산하면 틀린다 — 구간 상수가 서로 다르다."""
    standard, lower, upper = fee_bands(500_000_000)
    assert lower != pytest.approx(standard * 0.8)
    assert upper != pytest.approx(standard * 1.2)


def test_unsupported_ruleset_is_rejected():
    with pytest.raises(ValueError):
        fee_bands(1_000_000_000, ruleset="2099-999")


def test_floor_and_ceiling_are_inclusive_operating_boundaries():
    """원 단위 경계: 하한 floor 이상·상한 ceil 이하가 '기준 내'.

    15,774,420,000원 건은 하한 9,137,721.6 / 상한 13,581,582.4로 둘 다 소수라
    floor·ceil 방향을 제대로 검증한다.
    """
    _, lower, upper = fee_bands(15_774_420_000)
    low_bound, high_bound = floor(lower), ceil(upper)

    assert deviation(low_bound, lower, upper) == "기준 내"
    assert deviation(low_bound - 2, lower, upper) == "하한 미만"
    assert deviation(high_bound, lower, upper) == "기준 내"
    assert deviation(high_bound + 2, lower, upper) == "상한 초과"


def test_one_won_short_of_the_band_is_not_an_outlier():
    """APWorks가 하한보다 정확히 1원 적게 끊는 건이 있다 — 이탈로 칠하면 헛짚는다.

    2026-04 상반 01-2603-3-1032: 하한 791,131.8112 / 청구 791,130.
    재무팀 확정 엑셀도 격차율 -0.0000023으로 계산하고 의견을 달지 않았다.
    """
    _, lower, upper = fee_bands(701_571_960)

    assert lower == pytest.approx(791_131.8112)
    assert deviation(791_130, lower, upper) == "기준 내"
    # 원 단위 절사로 설명되지 않는 폭은 그대로 이탈이다.
    assert deviation(791_129, lower, upper) == "하한 미만"


def test_missing_fee_is_not_treated_as_zero_fee_outlier():
    """NULL 수수료를 0원으로 바꾸면 안 된다 — '하한 미만'이 아니라 '수수료 미입력'."""
    item = evaluate(appraisal_amount=1_000_000_000, actual_fee=None)

    assert item["actual_fee"] is None
    assert item["actual_rate"] is None
    assert item["deviation_direction"] == "수수료 미입력"
    assert item["decision_status"] == "수수료 미입력"


def test_zero_fee_is_distinct_from_missing_fee():
    """실제로 0원이 청구된 건은 '수수료 미입력'이 아니라 '하한 미만'이다."""
    item = evaluate(appraisal_amount=1_000_000_000, actual_fee=0)

    assert item["actual_fee"] == 0
    assert item["deviation_direction"] == "하한 미만"


def test_receipt_date_only_proposes_ruleset_and_stays_unconfirmed():
    """접수일은 용역 계약일이 아니다 — 계산은 보여주되 버전은 확정하지 않는다."""
    item = evaluate(
        appraisal_amount=1_000_000_000,
        actual_fee=1_100_000,
        receipt_date=date(2025, 3, 1),
    )

    assert item["fee_ruleset_code"] == RULESET_PREVIOUS
    assert item["fee_ruleset_status"] == "UNCONFIRMED"
    assert item["contract_date"] is None
    assert item["contract_date_source"] == "UNKNOWN"


def test_contract_date_confirms_the_ruleset():
    before = ruleset_for(contract_date=date(2025, 3, 16))
    on_cutoff = ruleset_for(contract_date=FEE_RULESET_CUTOFF)

    assert before["fee_ruleset_code"] == RULESET_PREVIOUS
    assert before["fee_ruleset_status"] == "CONFIRMED_FROM_CONTRACT_RULE"
    assert on_cutoff["fee_ruleset_code"] == RULESET_CURRENT


def test_no_date_at_all_falls_back_to_current_table_unconfirmed():
    """근거가 아무것도 없으면 현행표로 참고 계산만 하고 미확정으로 남긴다 (계획서 §13-4)."""
    version = ruleset_for()

    assert version["fee_ruleset_code"] == RULESET_CURRENT
    assert version["fee_ruleset_status"] == "UNCONFIRMED"
