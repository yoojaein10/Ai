"""적용 요율 — 원천값(APW_BILL)과 금액에서 역산한 실효율.

요율은 계산값이 아니라 수임 시 정하는 선택값이다. 종전에는 0.8을 상수로 박아 넣어
2026-03 재무팀 엑셀 469행 중 73행(15%)을 틀리게 표시했다.
"""

from app.services import fee_basis as rate

# 실측 규모 — 기준 x 0.8 이 하한이 아니다(구간마다 누진상수가 다르다).
STANDARD = 2_370_600.0
LOWER = 1_936_480.0
UPPER = 2_804_720.0


def described(billed, **source):
    return rate.describe(
        source or None, billed_fee=billed, standard_fee=STANDARD,
        lower_fee=LOWER, upper_fee=UPPER,
    )


def test_lower_band_rate_explains_the_billed_fee():
    """실측 01-2510-3-3519: Rate 0.8 · Dc 1.0 → 청구 = 하한."""
    result = described(LOWER, susu_rate=0.8, susu_dc=1.0)

    assert result["applied_rate"] == 0.8
    assert result["rate_explained"] is True
    assert result["rate_label"] == "0.8"
    assert result["rate_applied_fee"] == LOWER


def test_discount_is_shown_with_the_rate():
    """실측 01-2502-3-0543: Rate 0.8 · Dc 0.7 → 청구 = 하한 x 0.7 (1년내 재의뢰 할인)."""
    result = described(LOWER * 0.7, susu_rate=0.8, susu_dc=0.7)

    assert result["rate_explained"] is True
    assert result["rate_label"] == "0.8 x0.7"
    # 요율적용금액에는 할인을 곱하지 않는다 — 재무팀 엑셀 Y열이 그 정의다.
    assert result["rate_applied_fee"] == LOWER


def test_applied_fee_is_the_band_not_the_discounted_amount():
    """실측 2026-05 대조: 할인을 곱했더니 엑셀과 9건이 어긋났다.

    01-2602-3-0636 은 엑셀 Y 81,939,370 인데 우리는 x0.7 한 57,357,559 였다.
    """
    result = described(LOWER * 0.7, susu_rate=0.8, susu_dc=0.7)

    assert result["rate_applied_fee"] == LOWER
    assert result["rate_applied_fee"] != LOWER * 0.7


def test_standard_band_is_not_the_lower_band():
    """기준율(1.0)로 청구한 건을 하한으로 재면 요율이 틀린다."""
    result = described(STANDARD, susu_rate=1.0, susu_dc=1.0)

    assert result["rate_explained"] is True
    assert result["rate_label"] == "1"
    # 실효율은 청구/기준이라 1.0 이다.
    assert abs(result["effective_rate"] - 1.0) < 1e-9


def test_unexplained_amount_shows_the_effective_rate():
    """정액 컨설팅·합산청구처럼 보수표 밖에서 정해진 건(실측 10%)."""
    result = described(4_000_000, susu_rate=1.0, susu_dc=1.0)

    assert result["rate_explained"] is False
    assert "실효" in result["rate_label"]


def test_missing_source_rate_falls_back_to_the_effective_rate():
    """원천에 요율이 없는 건(APW_BILL 32,381건)은 역산값만 근사로 알려준다."""
    result = described(LOWER)

    assert result["applied_rate"] is None
    assert result["rate_label"].startswith("실효")


def test_conflicting_bill_rows_do_not_pick_a_rate():
    result = described(LOWER, susu_rate=0.8, susu_dc=1.0, conflict=True)

    assert result["rate_conflict"] is True
    assert result["rate_label"] == "요율 원천 충돌"
    assert result["rate_explained"] is False


def test_blank_amounts_do_not_crash():
    result = rate.describe(
        {"susu_rate": 0.8}, billed_fee=None, standard_fee=None,
        lower_fee=None, upper_fee=None,
    )

    assert result["effective_rate"] is None
    assert result["rate_explained"] is False


def test_band_map_covers_the_three_legal_rates():
    """보수기준은 80~120% 범위다. 그 세 밴드가 매핑돼 있어야 한다."""
    assert rate.BAND_BY_RATE == {
        0.8: "lower_fee", 1.0: "standard_fee", 1.2: "upper_fee",
    }


def test_out_of_band_rate_still_reports_the_rate_and_effective():
    """SusuRate 0.9·1.1 은 하한·기준·상한 어느 밴드도 아니다(실측 존재 값).

    금액은 특정할 수 없지만 요율·실효율은 보여야 빈칸의 이유를 안다.
    """
    result = described(LOWER * 0.9, susu_rate=0.9, susu_dc=1.0)

    assert result["rate_applied_fee"] is None
    assert result["applied_rate"] == 0.9
    assert result["rate_label"].startswith("0.9")
    assert "실효" in result["rate_label"]
