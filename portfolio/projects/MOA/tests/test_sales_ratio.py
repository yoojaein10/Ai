"""매출입력 인정비율 규칙 테스트 (공(XXX) 건 한정).

인정비율표는 시행일(TABLE_EFFECTIVE_DATE) 전까지 적용되지 않는다 —
현행 관행은 '공() = 실적 미인정(0%)'이고 우리은행만 절반이다.
표 자체의 비율은 `in_effect` 픽스처로 시행 상태를 만들어 검증한다.
"""

from datetime import date

import pytest

from app.services import sales_ratio
from app.services.sales_ratio import (
    category,
    expected_ratio,
    is_solo_processing,
    is_table_in_effect,
    joint_name,
    ratio_basis,
)

WOORI = "우리은행 여신업무센터(평창동지점)장"
EFFECTIVE = date(2026, 8, 1)
AFTER = date(2026, 8, 10)
BEFORE = date(2026, 7, 20)


@pytest.fixture
def in_effect(monkeypatch):
    """인정비율표가 시행된 상태로 만든다."""
    monkeypatch.setattr(sales_ratio, "TABLE_EFFECTIVE_DATE", EFFECTIVE)
    return EFFECTIVE


# --- 공(XXX) 판정 -------------------------------------------------------
def test_joint_name_extracted():
    assert joint_name("공(조경미)") == "조경미"
    assert joint_name("조경미") == ""
    assert joint_name("공병호") == ""


def test_solo_when_charge_is_only_the_joint_person():
    assert is_solo_processing("공(신상우)", "신상우") is True


def test_joint_when_other_investigators_present():
    assert is_solo_processing("공(이동진)", "최윤석") is False
    assert is_solo_processing("공(안창덕)", "이지운,안창덕") is False


# --- 업무 매핑 ----------------------------------------------------------
def test_purpose_decides_before_work_for_jongjeon_jonghu():
    """종전·종후는 대분류가 정비사업/보상/국공유재산에 걸쳐 있어 세부목적이 우선."""
    assert category("보상", "주택재개발(종후)") == "종후평가"
    assert category("국공유재산", "주택재건축(종전)") == "보상·종전·SH"


def test_court_split_by_purpose():
    assert category("법원 및 공매", "민사소송") == "소송평가"
    assert category("법원 및 공매", "공매(NPL)") == "경매(공매)평가"
    assert category("법원 및 공매", "법원경매") == "경매(공매)평가"


def test_public_asset_treated_as_its_own_category():
    """국공유재산은 재무 답변(2026-07-29)대로 일반거래 취급 20/15 — SH 여부와 무관."""
    assert category("국공유재산", "(國)임료(사용료)", "서울주택도시공사 사장") \
        == "국공유재산(일반거래 취급)"
    assert category("국공유재산", "(공)매입매각", "강서구청장") == "국공유재산(일반거래 취급)"
    assert category("담보", "제1금융권담보", "Sh수협은행 반월당금융센터") == "담보평가"


def test_unlisted_work_has_no_category():
    for work in ("가격자문", "컨설팅", "기업관련",
                 "유동화자산", "공시업무", "기타 공공", "도시개발사업"):
        assert category(work, "") is None


# --- 시행일 게이트 ------------------------------------------------------
def test_table_not_in_effect_when_date_undefined():
    assert sales_ratio.TABLE_EFFECTIVE_DATE is None  # 재무팀 확정 대기
    assert is_table_in_effect(AFTER) is False
    assert is_table_in_effect(None) is False


def test_table_in_effect_only_from_effective_date(in_effect):
    assert is_table_in_effect(BEFORE) is False
    assert is_table_in_effect(EFFECTIVE) is True
    assert is_table_in_effect(AFTER) is True
    assert is_table_in_effect(None) is False  # 입력일 불명은 미시행 취급(오탐 방지)


# --- 기대 비율: 시행 전(현행 관행) --------------------------------------
def test_non_joint_is_always_full():
    assert expected_ratio("신상우", WOORI, "담보", "제1금융권담보", "신상우") == 1.0


def test_woori_joint_is_always_half_regardless_of_work():
    assert expected_ratio("공(조경미)", WOORI, "담보", "제1금융권담보", "이주원") == 0.5
    assert expected_ratio("공(조경미)", WOORI, "담보", "제1금융권담보", "조경미") == 0.5


def test_joint_is_unrecognized_before_effective_date():
    """전수 확인(2026-07-30): 공() 872건 중 811건이 매출입력 없음 = 미인정."""
    assert expected_ratio("공(김현동)", "신한은행 역촌동지점장", "담보",
                          "제1금융권담보", "김현동") == 0.0
    # 표에 없는 업무도 마찬가지로 미인정 (공() 가격자문·공시업무 전부 입력 없음)
    assert expected_ratio("공(송정선)", "(주)GS건설", "컨설팅",
                          "기타자문및컨설팅", "송정선") == 0.0


def test_woori_exception_survives_before_effective_date():
    """우리은행은 시행 전에도 절반 — 실측 56건이 0.50."""
    assert expected_ratio("공(신상우)", WOORI, "담보", "제1금융권담보",
                          "신상우", BEFORE) == 0.5


# --- 기대 비율: 시행 후(표 적용) ----------------------------------------
def test_table_applied_for_non_woori_joint(in_effect):
    # 담보: 단독 15% / 공동 10%
    assert expected_ratio("공(김현동)", "신한은행 역촌동지점장", "담보",
                          "제1금융권담보", "김현동", AFTER) == 0.15
    assert expected_ratio("공(김현동)", "신한은행 역촌동지점장", "담보",
                          "제1금융권담보", "박준용", AFTER) == 0.10


def test_public_asset_rates_are_20_and_15(in_effect):
    sh = "서울주택도시개발공사 사장"
    assert expected_ratio("공(최병산)", sh, "국공유재산",
                          "(市)임료(사용료)", "최병산", AFTER) == 0.20
    assert expected_ratio("공(최병산)", sh, "국공유재산",
                          "(市)임료(사용료)", "김해원", AFTER) == 0.15


def test_lawsuit_solo_is_full_rate(in_effect):
    assert expected_ratio("공(정우종)", "법무법인", "법원 및 공매",
                          "민사소송", "정우종", AFTER) == 1.0
    assert expected_ratio("공(정우종)", "법무법인", "법원 및 공매",
                          "민사소송", "김철수", AFTER) == 0.5


def test_unlisted_work_is_full_after_effective_date(in_effect):
    assert expected_ratio("공(송정선)", "(주)GS건설", "컨설팅",
                          "기타자문및컨설팅", "송정선", AFTER) == 1.0


def test_before_effective_date_still_unrecognized(in_effect):
    """시행일 이전 입력분은 표를 적용하지 않는다 — 소급 오탐 방지."""
    assert expected_ratio("공(김현동)", "신한은행 역촌동지점장", "담보",
                          "제1금융권담보", "김현동", BEFORE) == 0.0


# --- 근거 문구 ----------------------------------------------------------
def test_basis_text_names_rule():
    assert ratio_basis("공(조경미)", WOORI, "담보", "제1금융권담보", "이주원") \
        == "우리은행 공동유치(무조건 절반)"
    assert ratio_basis("안창덕", "류기륜", "일반거래", "시가참고", "이지운,안창덕") \
        == "단독 유치(전액)"


def test_basis_text_says_unrecognized_before_effective_date():
    assert ratio_basis("공(김현동)", "신한은행", "담보", "제1금융권담보", "김현동") \
        == "공(이름) 유치 — 현행 관행상 실적 미인정(인정비율표 미시행)"


def test_basis_text_names_table_after_effective_date(in_effect):
    assert ratio_basis("공(김현동)", "신한은행", "담보",
                       "제1금융권담보", "김현동", AFTER) == "담보평가 단독처리 15%"
