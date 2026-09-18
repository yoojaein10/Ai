"""사유 표현 통일 — 운영(보수기준 점검) 형식이 기준.

두 화면이 같은 APW_IW_SusuWhy.Code 1~45를 쓰면서 표현만 달랐다. 우리 AB 핵심어를
운영 코드·조문 라벨로 바꿔 후보 목록에 합칠 수 있어야 한다. 억지로 붙이면 오탐이 되므로
대응 코드가 없는 사유는 코드 없이 참고로만 남긴다.
"""

from app.services import fee_basis_evidence as bridge
from app.services.fee_basis_rules import FEE_CODE_LABELS
from app.services.fee_basis_evidence import _APW_CODE_LABELS


def test_both_screens_use_the_same_45_codes():
    """코드 집합이 어긋나면 후보 목록에 넣을 수 없다."""
    assert set(_APW_CODE_LABELS) == set(FEE_CODE_LABELS)
    assert len(FEE_CODE_LABELS) == 45


def test_simple_reason_maps_to_one_code():
    assert bridge.fee_codes_for("CONSULTING") == (24,)
    assert bridge.fee_codes_for("RENT") == (39,)
    assert bridge.fee_codes_for("VOLUME") == (23,)
    assert bridge.fee_codes_for("DEVELOPMENT_LAND") == (20,)


def test_reappraisal_band_picks_the_matching_article():
    """재평가는 기간 구간마다 조문·할인율이 다르다(70%/50%/30%/10%)."""
    assert bridge.fee_codes_for("REAPPRAISAL", "3개월이내재평가") == (14,)
    assert bridge.fee_codes_for("REAPPRAISAL", "6개월이내재평가") == (15,)
    assert bridge.fee_codes_for("REAPPRAISAL", "1년이내재평가") == (16,)
    assert bridge.fee_codes_for("REAPPRAISAL", "2년이내재평가") == (17,)


def test_reappraisal_without_a_band_picks_no_code():
    """구간을 못 읽으면 할인율을 특정할 수 없어 확정 코드를 고르지 않는다."""
    assert bridge.fee_codes_for("REAPPRAISAL", "재평가확인") == ()


def test_retrospective_uses_the_general_article_not_the_court_one():
    """대법원예규 §32는 법원 감정에만 쓴다. 일반 소급은 제5조다."""
    assert bridge.fee_codes_for("RETROSPECTIVE") == (bridge.RETROSPECTIVE_CODE,)
    assert bridge.RETROSPECTIVE_CODE == 2
    assert bridge.RETROSPECTIVE_COURT_CODE == 35


def test_reasons_without_an_article_code_are_not_forced():
    """운영 45개 체계에 없는 사유를 억지로 붙이면 오탐이 된다."""
    for reason in bridge.UNMAPPED_REASONS:
        assert bridge.fee_codes_for(reason) == ()


def test_candidate_has_the_operational_shape():
    """운영 화면이 그대로 렌더링할 수 있어야 한다."""
    item = {
        "suggested_reason_code": "CONSULTING",
        "suggested_opinion": "컨설팅",
        "suggested_reason_label": "컨설팅·자문용역",
        "evidence_level": "DIRECT",
        "evidence": [{"selected": True, "page_no": 17}],
    }

    candidates = bridge.to_candidates(item)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["code"] == 24
    assert candidate["label"] == FEE_CODE_LABELS[24]
    assert candidate["source"] == "본문(교정본)"
    assert candidate["page"] == 17
    # 근거 등급과 AB 핵심어를 함께 실어 재무팀 엑셀도 채울 수 있게 한다.
    assert candidate["grade"] == "DIRECT"
    assert candidate["ab_keyword"] == "컨설팅"


def test_unmapped_reason_becomes_a_reference_row_without_a_code():
    item = {
        "suggested_reason_code": "COMBINED_BILLING",
        "suggested_opinion": "합산청구",
        "suggested_reason_label": "합산·분할·대표 청구",
        "evidence_level": "CONTEXT_ONLY",
    }

    candidate = bridge.to_candidates(item)[0]

    assert candidate["code"] is None
    assert "코드없음" in candidate["source"]
    assert candidate["ab_keyword"] == "합산청구"


def test_row_without_a_reason_yields_nothing():
    assert bridge.to_candidates({"suggested_reason_code": ""}) == []


def test_grade_maps_to_a_source_label_for_every_level():
    """등급을 빠뜨리면 화면에 '확인필요'로만 보여 근거 강도를 알 수 없다."""
    from app.services import fee_basis_evidence as evidence

    for level in (
        evidence.DIRECT, evidence.STRUCTURED_CASE_SIGNAL, evidence.CONTEXT_ONLY,
        evidence.CALCULATED, evidence.NO_DOCUMENT_LEVEL, evidence.AMBIGUOUS,
        evidence.NONE,
    ):
        assert level in bridge.SOURCE_BY_LEVEL


def test_code_converts_back_to_the_finance_ab_keyword():
    """재무팀이 엑셀을 계속 쓰면 운영 코드에서 AB 열을 만들어야 한다."""
    assert bridge.ab_keyword_for(24) == "컨설팅"
    assert bridge.ab_keyword_for(39) == "임료감정"
    assert bridge.ab_keyword_for(2) == "소급감정"
    assert bridge.ab_keyword_for(16) == "1년이내재평가"
    assert bridge.ab_keyword_for(17) == "2년이내재평가"
    assert bridge.ab_keyword_for(None) == ""


def test_every_mapped_code_produces_a_keyword():
    """코드는 45개인데 AB 핵심어가 비면 엑셀 칸이 빈다."""
    blanks = [
        code for code in FEE_CODE_LABELS if not bridge.ab_keyword_for(code)
    ]

    assert blanks == []
