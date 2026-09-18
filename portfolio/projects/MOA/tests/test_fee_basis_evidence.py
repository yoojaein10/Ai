"""보수기준 검토 판정을 운영 후보 목록에 합치는 규칙.

운영 규칙을 덮지 않는다. 같은 코드는 근거만 보강하고, 새 코드는 뒤에 붙인다.
운영 쪽이 우리보다 나은 판정(LWorkinfo 기반, min_hits, 지명 제외)이 있어서다.
"""

from pathlib import Path

from app.services import fee_basis_evidence as merge

UI = Path(__file__).resolve().parent.parent / "desktop" / "ui"


def test_same_code_keeps_the_operational_candidate_and_adds_our_evidence():
    existing = [{
        "code": 24, "label": "제11조 상담·자문 등",
        "source": "목적", "evidence": "업무 '컨설팅'", "page": None,
    }]
    ours = [{
        "code": 24, "label": "제11조 상담·자문 등",
        "source": "본문(교정본)", "evidence": "'컨설팅' 3회 — …", "page": 17,
        "grade": "DIRECT", "ab_keyword": "컨설팅",
    }]

    merged = merge._merge_candidates(existing, ours)

    assert len(merged) == 1
    assert merged[0]["code"] == 24
    # 어느 쪽이 봤는지 남는다.
    assert merged[0]["source"] == "목적+보수검토"
    assert "'컨설팅' 3회" in merged[0]["evidence"]
    assert "업무 '컨설팅'" in merged[0]["evidence"]
    assert merged[0]["grade"] == "DIRECT"
    assert merged[0]["ab_keyword"] == "컨설팅"


def test_new_code_is_appended_not_replacing():
    existing = [{"code": 1, "label": "제4조① 요율체계(기본)",
                 "source": "기본", "evidence": "특이 신호 없음"}]
    ours = [{"code": 16, "label": "제6조 할인-재평가 1년내(30%)",
             "source": "계산", "evidence": "1년 이내 동일물건 재평가",
             "grade": "CALCULATED", "ab_keyword": "1년이내재평가"}]

    merged = merge._merge_candidates(existing, ours)

    assert [c["code"] for c in merged] == [1, 16]
    assert merged[1]["source"].startswith("보수검토")


def test_codeless_candidate_does_not_collide_with_another_codeless_one():
    """코드 없는 후보는 서로 합쳐지면 안 된다 — 다른 사유다."""
    existing = [{"code": None, "label": "합산청구", "source": "보수검토(코드없음)",
                 "evidence": "합산·분할·대표 청구"}]
    ours = [{"code": None, "label": "할인/할증", "source": "확인필요(코드없음)",
             "evidence": "할인·할증·적용요율", "grade": "CONTEXT_ONLY",
             "ab_keyword": "할인/할증"}]

    merged = merge._merge_candidates(existing, ours)

    assert len(merged) == 2


def test_adapter_excludes_the_client_name_from_reason_detection():
    """의뢰처 상호에 '자산운용'이 들어가도 그 업무라고 볼 수 없다."""
    adapter = merge._adapter_item({
        "doc_id": "01-2606-3-1769",
        "source_row_number": 3,
        "work": "일반거래",
        "purpose": "시가참고",
        "cust_name": "(주)코크렙52호위탁관리부동산투자회사",
        "receipt_date": "2026-06-02",
    })

    joined = " ".join(str(v) for v in adapter.values())
    assert "코크렙" not in joined
    assert adapter["purpose_name"] == "시가참고"
    assert adapter["work_name"] == "일반거래"
    # 전 행이 근거 탐색 대상이다 — 운영 화면의 목적이 미입력 보수기준을 메꾸는 것이다.
    assert adapter["review_target"] is True


def test_adapter_normalizes_the_doc_id_for_jun_lookup():
    adapter = merge._adapter_item({
        "doc_id": "01-2606-3-1769", "source_row_number": 1,
    })

    assert adapter["doc_id_normalized"] == "01260631769"


def test_doc_id_normalizer_is_self_contained_and_matches_jun_key_format():
    assert merge.normalize_doc_id(" 01-2606-a/01769 ") == "012606A01769"
    assert merge.normalize_doc_id(None) == ""


def test_gap_amount_uses_the_crossed_bound():
    """차액은 넘어선 쪽 경계 기준이다. 반대 경계로 재면 부호·크기가 틀린다."""
    below = merge._gap_amount({
        "actual_fee": 900, "lower_fee": 1_000, "upper_fee": 1_500,
        "deviation_direction": "하한 미만",
    })
    above = merge._gap_amount({
        "actual_fee": 1_600, "lower_fee": 1_000, "upper_fee": 1_500,
        "deviation_direction": "상한 초과",
    })

    assert below == -100
    assert above == 100
    assert merge._gap_amount({"actual_fee": None, "lower_fee": 1}) is None


def test_empty_list_does_not_call_the_engine():
    assert merge.attach_review_evidence([]) == {}


def test_screen_warns_when_an_evidence_source_failed():
    script = (UI / "fee-basis.html").read_text(encoding="utf-8")

    assert "summary.jun_error" in script
    assert "JUN 근거 조회 실패" in script
    assert "summary.prior_error" in script


def test_gap_amount_is_none_when_the_row_is_within_the_band():
    """기준 내 행에 하한 대비 차액을 넘기면 `수수료차액발생 0`이 붙는다(실측 54건)."""
    assert merge._gap_amount({
        "actual_fee": 1_200, "lower_fee": 1_000, "upper_fee": 1_500,
        "deviation_direction": "기준 내",
    }) is None
    assert merge._gap_amount({
        "actual_fee": 1_200, "lower_fee": 1_000, "upper_fee": 1_500,
        "deviation_direction": "",
    }) is None


def test_only_rows_that_need_an_opinion_are_flagged():
    """조치할 필요가 없는 기준 내 행을 확인 큐에 넣으면 63건이 노이즈가 된다."""
    assert merge._needs_opinion({"deviation_direction": "하한 미만"}) is True
    assert merge._needs_opinion({"deviation_direction": "상한 초과"}) is True
    assert merge._needs_opinion({"deviation_direction": "수수료 미입력"}) is True
    # 비교 자체가 불가한 행도 담당자가 봐야 한다.
    assert merge._needs_opinion({
        "deviation_direction": None, "fee_state": "수수료 원천 충돌",
    }) is True
    assert merge._needs_opinion({"deviation_direction": "기준 내"}) is False
    assert merge._needs_opinion({"deviation_direction": "기준 내", "fee_state": ""}) is False


def test_primary_prefers_a_cross_verified_candidate():
    """양쪽 규칙이 같은 결론이면 교차검증된 것이라 가장 믿을 만하다."""
    primary = merge.pick_primary([
        {"code": 38, "label": "보상평가종가", "source": "목적", "grade": "CONTEXT_ONLY"},
        {"code": 23, "label": "종량제", "source": "목적+보수검토",
         "grade": "STRUCTURED_CASE_SIGNAL"},
    ])

    assert primary["code"] == 23


def test_primary_never_picks_the_base_rate_when_another_reason_exists():
    """기본 요율체계는 '특이 신호 없음'이라는 뜻이다."""
    primary = merge.pick_primary([
        {"code": merge.BASE_RATE_CODE, "label": "요율체계", "source": "기본"},
        {"code": 40, "label": "법원 소송평가", "source": "보수검토:본문(교정본)",
         "grade": "DIRECT"},
    ])

    assert primary["code"] == 40


def test_base_rate_is_used_when_it_is_the_only_candidate():
    primary = merge.pick_primary([
        {"code": merge.BASE_RATE_CODE, "label": "요율체계", "source": "기본"},
    ])

    assert primary["code"] == merge.BASE_RATE_CODE


def test_stronger_grade_wins_between_two_reasons():
    """APWorks 사건 사유가 정황보다 강하다."""
    primary = merge.pick_primary([
        {"code": 39, "label": "임대료", "source": "목적", "grade": "CONTEXT_ONLY"},
        {"code": 23, "label": "종량제", "source": "보수검토:APWorks사건",
         "grade": "STRUCTURED_CASE_SIGNAL"},
    ])

    assert primary["code"] == 23


def test_codeless_candidate_loses_to_one_with_an_article_code():
    """조문을 특정한 후보가 대표여야 한다."""
    primary = merge.pick_primary([
        {"code": None, "label": "차액", "source": "보수검토:계산", "grade": "CALCULATED"},
        {"code": 24, "label": "상담·자문", "source": "목적", "grade": "CONTEXT_ONLY"},
    ])

    assert primary["code"] == 24


def test_primary_ignores_the_entered_code():
    """입력값을 순위에 넣으면 담당자가 고른 값이 늘 대표가 되어 불일치가 사라진다."""
    candidates = [
        {"code": 1, "label": "요율체계", "source": "기본"},
        {"code": 40, "label": "법원 소송평가", "source": "보수검토:본문(교정본)",
         "grade": "DIRECT"},
    ]

    # 입력 코드가 1이어도 대표는 근거가 강한 40이다 → 화면에 불일치가 드러난다.
    assert merge.pick_primary(candidates)["code"] == 40


def test_no_candidates_yields_no_primary():
    assert merge.pick_primary([]) is None
