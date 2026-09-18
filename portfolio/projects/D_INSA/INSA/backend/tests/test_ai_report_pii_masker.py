from app.services.ai_report.pii_masker import PiiMasker


def test_mask_employee_id_and_name():
    masker = PiiMasker(employee_names=["홍길동", "김철수"])
    masked, restore = masker.mask_identifier(emp_id=1, name="홍길동", role="employee")
    assert masked == "__INSA_EMP_001__"
    assert restore[masked] == "홍길동(E001)"


def test_mask_rater_uses_separate_namespace():
    masker = PiiMasker(employee_names=["홍길동", "김철수"])
    masker.mask_identifier(emp_id=1, name="홍길동", role="employee")
    masked_rater, _ = masker.mask_identifier(emp_id=2, name="김철수", role="rater")
    assert masked_rater.startswith("__INSA_RATER_")
    assert masked_rater != "__INSA_EMP_002__"


def test_mask_comment_replaces_employee_names():
    masker = PiiMasker(employee_names=["홍길동", "김철수", "박영희"])
    text = "홍길동 사원과 김철수 대리가 협업했습니다"
    masked, restore = masker.mask_text(text)
    assert "홍길동" not in masked
    assert "김철수" not in masked
    assert "협업" in masked
    assert masker.unmask(masked, restore) == text


def test_long_names_match_first():
    """이름이 substring으로 충돌하면 긴 이름부터 매칭."""
    masker = PiiMasker(employee_names=["김철수", "김철"])
    masked, _ = masker.mask_text("김철수 사원")
    assert "수 사원" not in masked


def test_same_name_returns_same_placeholder():
    masker = PiiMasker(employee_names=["홍길동"])
    masked1, restore = masker.mask_text("홍길동 사원")
    masked2, _ = masker.mask_text("홍길동 사원의 보고서", existing_restore=restore)
    placeholder1 = masked1.replace(" 사원", "")
    placeholder2 = masked2.replace(" 사원의 보고서", "")
    assert placeholder1 == placeholder2


def test_unmask_handles_missing_placeholder_gracefully():
    masker = PiiMasker(employee_names=["홍길동"])
    restore = {"__INSA_EMP_001__": "홍길동(E001)"}
    text = "직원분의 강점은..."
    assert masker.unmask(text, restore) == text


def test_mask_text_preserves_existing_audit_form_from_mask_identifier():
    """mask_text는 mask_identifier가 설정한 audit form('name(Eemp_id)')을 덮어쓰지 않음."""
    masker = PiiMasker(employee_names=["홍길동"])
    placeholder, restore = masker.mask_identifier(emp_id=1, name="홍길동", role="employee")
    masked, restore = masker.mask_text("홍길동의 보고서", existing_restore=restore)
    assert restore[placeholder] == "홍길동(E001)"  # not "홍길동"
