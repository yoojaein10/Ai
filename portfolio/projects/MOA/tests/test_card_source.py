"""카드내역 DB(CB2_APPR) → CardUsage 변환 검증.

DB 접속 없이 행 변환(row_to_usage)과 엑셀 파이프라인(validate)과의 합류를 확인한다.
"""

from decimal import Decimal

from app.services import card_vouchers as cv
from app.services.card_source import row_to_usage


def _row(**over):
    base = {
        "CARD_NO": "5404-9780-0128-3967",
        "APPR_DATE": "20260731",
        "APPR_TIME": "083100",
        "APPR_NO": 'REDACTED_CONFIGURE_LOCALLY78',
        "Use_Name": "홍길동  ",
        "CHAIN_NM": "정진식당",
        "CHAIN_ID": "484-03-00117",
        "APPR_AMT": Decimal("269000.00"),
        "APPR_TAX": Decimal("24455.00"),
        "SUPPLY_AMT": Decimal("244545.00"),
        "DEDUCT_YN": "Y",
        "CANCEL_YN": None,
    }
    base.update(over)
    return base


def test_row_to_usage_normalizes_like_excel_parser():
    usage = row_to_usage(_row(), 1)
    assert usage.card_no == "5404978001283967"          # 숫자만
    assert usage.merchant_biz_no == "4840300117"        # 숫자만 10자리
    assert usage.user_name == "홍길동"                   # 공백 제거
    assert usage.use_date == "20260731"
    assert usage.total == Decimal("269000.00")
    assert usage.supply + usage.vat == usage.total
    assert usage.deductible is True
    assert usage.canceled is False
    assert usage.purpose == "" and usage.account_code == ""  # 계정은 화면에서 지정
    assert usage.remark == "3967.07.31. 정진식당"  # 카드끝4자리.월.일. 가맹점 (재무팀 관행)


def test_deduct_yn_only_y_is_deductible():
    assert row_to_usage(_row(DEDUCT_YN="Y"), 1).deductible is True
    assert row_to_usage(_row(DEDUCT_YN="X"), 1).deductible is False
    assert row_to_usage(_row(DEDUCT_YN="N"), 1).deductible is False
    assert row_to_usage(_row(DEDUCT_YN=None), 1).deductible is False


def test_canceled_row_flagged():
    assert row_to_usage(_row(CANCEL_YN="Y"), 1).canceled is True
    assert row_to_usage(_row(CANCEL_YN="1"), 1).canceled is True
    assert row_to_usage(_row(CANCEL_YN=""), 1).canceled is False


def test_dedup_key_matches_excel_source_for_same_approval():
    """같은 승인건은 엑셀에서 오든 DB에서 오든 같은 dedup_key여야 한다."""
    from_db = row_to_usage(_row(), 1)
    from_excel = cv.CardUsage(
        row_no=2, card_no="5404978001283967", card_alias="법인1",
        user_name="홍길동", use_date="20260731", appr_no='REDACTED_CONFIGURE_LOCALLY78',
        merchant="정진식당", merchant_biz_no="4840300117",
        total=Decimal("269000"), supply=Decimal("244545"), vat=Decimal("24455"),
        purpose="복리후생비", deductible=True, canceled=False,
    )
    assert from_db.dedup_key == from_excel.dedup_key


def test_validate_holds_db_rows_without_account():
    """DB 건은 계정 미매핑 보류로 시작하고, 이미 전표가 있으면 중복 보류가 붙는다."""
    usage = row_to_usage(_row(), 1)
    cv.validate([usage], known_keys=set())
    assert any(h.startswith("계정 미매핑") for h in usage.holds)

    dup = row_to_usage(_row(), 1)
    cv.validate([dup], known_keys={dup.dedup_key})
    assert "이미 전표가 생성된 건" in dup.holds


def test_validate_amount_check_applies_to_db_rows():
    bad = row_to_usage(_row(SUPPLY_AMT=Decimal("100"), APPR_TAX=Decimal("10")), 1)
    cv.validate([bad], known_keys=set())
    assert any(h.startswith("금액 불일치") for h in bad.holds)
