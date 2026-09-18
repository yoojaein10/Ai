"""상여 순수 계산 규칙 (app/services/bonus/rules.py) — 엑셀 수식과 1원 단위로 맞춘다.

숫자는 ★★2026년 성과상여.xlsx 26.08월 시트에서 그대로 가져왔다 (2026-08-25 분석).
"""

from app.services.bonus import rules
from app.services.bonus.rules import (
    associate_doc_calc,
    classify_manager,
    extract_doc_ids,
    manager_names,
    shareholder_doc_calc,
    survey_payout,
    travel_shortfall,
)


def test_이관된_함수가_새_경로에서_같이_동작한다():
    assert travel_shortfall(40_000, 60_000) == 20_000
    assert travel_shortfall(10_000, 3_000) == 0
    assert extract_doc_ids("012607-4-0236-1 전자수입인지") == ["01-2607-4-0236"]
    assert manager_names("윤도,공(장재원)") == ["윤도", "장재원"]
    assert classify_manager("공(유영조)", None) == ("공통", "유영조")
    assert classify_manager("김기도", "so") == ("평동", "김기도")
    calc = shareholder_doc_calc("담보", 1_000_000, 0)
    assert (calc["indemnity"], calc["association_fee"]) == (15_000, 14_800)
    assert associate_doc_calc("담보", 560_800, 0)["indemnity"] == 8_412  # 김기도 01-2607-3-2182
    assert survey_payout(10_000, {"최병천": 3_000, "정우종": 1_000}, ["정우종"]) == 7_000


def test_절사는_엑셀_ROUNDDOWN처럼_0_방향이다():
    assert rules.rounddown(-7_731_900, -3) == -7_731_000
    assert rules.rounddown(30_217_677.42, -3) == 30_217_000
    assert rules.rounddown(905_950, -1) == 905_950
    assert rules.rounddown(905_999, -1) == 905_990
    assert rules.rounddown(12.34, 0) == 12


def test_소득세_주민세는_엑셀_절사_규칙을_따른다():
    """강무진 26.08: Y 30,197,000 → Z 9,059,000 → AA 905,900."""
    assert rules.income_tax(30_197_000) == 9_059_000
    assert rules.resident_tax(9_059_000) == 905_900
    # 이영은(소속, 30%): AD 634,900 → 190,000 → 19,000
    assert rules.income_tax(634_900, rate=0.30) == 190_000
    assert rules.resident_tax(190_000) == 19_000
    # 소속 기본 15%: 184,000 → 27,000 → 2,700 (홍현석 총괄표 08)
    assert rules.income_tax(184_000, rate=0.15) == 27_000
    assert rules.resident_tax(27_000) == 2_700
    assert rules.income_tax(0) == 0


def test_법인카드_한도는_일반쟁송을_빼고_사람_단위로_천원_절사한다():
    rows = [
        {"assessed": 27_860_000, "work_type": "정비사업"},   # 25.12 r7 AD = 1,393,000
        {"assessed": 5_000_000, "work_type": "일반쟁송"},    # 제외
        {"assessed": 8_750_000, "work_type": "컨설팅"},      # 437,500
    ]
    assert rules.card_limit(rows) == 1_830_000  # (1,393,000 + 437,500) → 천원 절사
    assert rules.card_limit([]) == 0
    assert rules.is_litigation("일반쟁송") is True
    assert rules.is_litigation("법원 및 공매") is False
    assert rules.is_litigation(None) is False


def test_소속평가사_상여는_건별_한계누진이다():
    """김혜수 26.02: L 136,655,640 → 1,000,000 + 3,750,000 + 24,000,000 + (L-1억)×35%."""
    assert rules.progressive_bonus(552_388) == 110_477.6           # 김기도 담보, 20%
    assert rules.progressive_bonus(5_000_000) == 1_000_000
    assert rules.progressive_bonus(20_000_000) == 4_750_000
    assert rules.progressive_bonus(100_000_000) == 28_750_000
    assert rules.progressive_bonus(136_655_640) == 41_579_474
    assert rules.progressive_bonus(0) == 0
    assert rules.progressive_bonus(-100) == 0


def test_수수료_계정은_감정수수료_하나로_고정한다():
    """4010002 기타수수료(사본발급 등)·4010003 공시지가등수익은 상여 원천이 아니다."""
    assert rules.FEE_ACCOUNTS == ("4010001",)
    assert rules.HQ_DIVISION == "1000"


def test_공통건_요율_규칙은_거래처_업무구분_사람_순이다():
    """2026-08-27 재무팀 확인: 산업은행 4%(+윤도 23%), 국공유재산·법원 15% 하한 30만, 보상 15%, 그 외 사람 요율 아니면 3%."""
    from app.services.bonus.rules import channel_owner, common_rate_rule, is_woori

    assert common_rate_rule("담보", "KDB산업은행 김포지점") == (4.0, 0.0, "CUSTOMER")
    assert channel_owner("한국산업은행 수원지점") == ("윤도", 23.0) and channel_owner("신한은행 백궁지점장") is None
    assert common_rate_rule("국공유재산", "한국토지주택공사 경기북부지역본부") == (15.0, 300_000.0, "WORK")
    assert common_rate_rule("법원 및 공매", "서울북부지방법원 경매9계", 3.0) == (3.0, 0.0, "PERSON")     # 유영조는 3%, 하한 없음
    assert common_rate_rule("보상", "중앙토지수용위원회사무국") == (15.0, 0.0, "WORK")
    assert common_rate_rule("가격자문", "신한은행 백궁지점장") == (3.0, 0.0, "DEFAULT")
    assert common_rate_rule("일반거래", "어느 회사", 10.0) == (10.0, 0.0, "PERSON")                      # 이영은 10%
    assert is_woori("우리은행 여신업무센터(시흥동지점) 50%") and not is_woori("신한은행 백궁지점장")
