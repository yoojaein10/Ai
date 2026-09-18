import pytest

from app.services import fee_basis_evidence as evidence


_REAL_APW_BILL_REASONS = evidence._apw_bill_reasons


@pytest.fixture(autouse=True)
def _no_live_apw_bill(monkeypatch):
    """단위 테스트가 APWorks 원천 DB를 암묵적으로 조회하지 않게 한다."""
    monkeypatch.setattr(evidence, "_apw_bill_reasons", lambda docs: {})
    monkeypatch.setattr(evidence, "_prior_reappraisals", lambda docs: {})


def item(**overrides):
    value = {
        "source_row_number": 3,
        "doc_id": "01-2607-A-0001",
        "doc_id_normalized": "012607A0001",
        "purpose_name": "기타 자문 및 컨설팅",
        "purpose_code": "82",
        "work_name": "일반실적",
        "work_code": "00",
        "title": "부동산 컨설팅 업무",
        "customer_name": "의뢰인",
        "review_target": True,
        "comparability": "COMPARABLE",
        "deviation_direction": "하한 미만",
        "actual_fee": 800_000,
        "lower_fee": 1_000_000,
        "upper_fee": 1_500_000,
        "source_row_json": {},
    }
    value.update(overrides)
    return value


def test_jun_direct_candidate_becomes_concise_reason_without_raw_quote(
    monkeypatch,
):
    row = item()
    monkeypatch.setattr(evidence, "_apw_reasons", lambda docs: {})
    monkeypatch.setattr(evidence, "_fetch_jun", lambda items: {
        row["doc_id_normalized"]: {
            "search_state": evidence.FOUND,
            "evidence": [{
                "source": "JUN",
                "reason_code": "CONSULTING",
                "reason_label": "컨설팅·자문용역",
                "page_no": 2,
                "file_name": "감정평가서.pdf",
                "file_role": "report",
                "evidence_sentence": "본 건은 부동산 컨설팅 업무를 목적으로 한다.",
                "confidence": 0.93,
                "direct_candidate": True,
            }],
        },
    })

    summary = evidence.enrich_items([row])

    assert row["evidence_level"] == evidence.DIRECT
    assert row["suggested_reason_code"] == "CONSULTING"
    assert row["suggested_reason_label"] == "컨설팅·자문용역"
    assert row["suggested_opinion"] == "컨설팅"
    assert "JUN" not in row["suggested_opinion"]
    assert "p.2" not in row["suggested_opinion"]
    assert "본 건은 부동산 컨설팅 업무를 목적으로 한다." not in (
        row["suggested_opinion"]
    )
    assert row["source_row_json"]["AB"] == row["suggested_opinion"]
    assert summary["direct"] == 1


def test_context_reason_wins_over_generic_fee_phrase_in_same_document(
    monkeypatch,
):
    row = item(customer_name="테스트자산운용 주식회사")
    monkeypatch.setattr(evidence, "_apw_reasons", lambda docs: {})
    monkeypatch.setattr(evidence, "_fetch_jun", lambda items: {
        row["doc_id_normalized"]: {
            "search_state": evidence.FOUND,
            "evidence": [
                {
                    "source": "JUN",
                    "reason_code": "CONSULTING",
                    "reason_label": "컨설팅·자문용역",
                    "confidence": 0.95,
                    "direct_candidate": True,
                },
                {
                    "source": "JUN",
                    "reason_code": "DISCOUNT_SURCHARGE",
                    "reason_label": "할인·할증·적용요율",
                    "confidence": 0.91,
                    "direct_candidate": True,
                },
            ],
        },
    })

    evidence.enrich_items([row])

    assert row["suggested_reason_code"] == "CONSULTING"
    assert row["suggested_opinion"] == "컨설팅"


def test_apworks_fee_rule_is_used_without_exposing_source_name(monkeypatch):
    row = item(purpose_name="", title="")
    monkeypatch.setattr(evidence, "_apw_reasons", lambda docs: {
        row["doc_id"]: [{
            "source": "APWORKS",
            "storage_key": 17,
            "display_code": 13,
            "contents": "동일물건 재평가",
            "item_note": "",
            "rule_note": "",
        }],
    })
    monkeypatch.setattr(evidence, "_fetch_jun", lambda items: {
        row["doc_id_normalized"]: {
            "search_state": evidence.NO_DOCUMENT,
            "evidence": [],
        },
    })

    evidence.enrich_items([row])

    assert row["evidence_level"] == evidence.STRUCTURED_CASE_SIGNAL
    assert row["suggested_reason_code"] == "REAPPRAISAL"
    assert row["suggested_reason_label"] == "3개월 이내 동일물건 재평가"
    assert row["suggested_opinion"] == "3개월이내재평가"
    assert "APWorks" not in row["suggested_opinion"]
    assert row["search_state"] == evidence.NO_DOCUMENT


def test_apworks_fee_rule_takes_priority_over_jun_keyword(monkeypatch):
    row = item()
    monkeypatch.setattr(evidence, "_apw_reasons", lambda docs: {
        row["doc_id"]: [{
            "source": "APWORKS",
            "storage_key": 23,
            "display_code": 39,
            "contents": "임료 평가",
            "item_note": "",
            "rule_note": "",
        }],
    })
    monkeypatch.setattr(evidence, "_fetch_jun", lambda items: {
        row["doc_id_normalized"]: {
            "search_state": evidence.FOUND,
            "evidence": [{
                "source": "JUN",
                "reason_code": "CONSULTING",
                "reason_label": "컨설팅·자문용역",
                "page_no": 2,
                "evidence_sentence": "컨설팅 업무",
                "confidence": 0.93,
                "direct_candidate": True,
            }],
        },
    })

    evidence.enrich_items([row])

    assert row["evidence_level"] == evidence.STRUCTURED_CASE_SIGNAL
    assert row["suggested_reason_code"] == "RENT"
    assert row["suggested_reason_label"] == "임료·임대료 감정"
    assert row["suggested_opinion"] == "임료감정"
    assert "컨설팅 업무" not in row["suggested_opinion"]


def test_apworks_query_keeps_only_joined_specific_reasons(monkeypatch):
    doc_id = "01-2607-A-0001"

    class Cursor:
        def execute(self, statement, params):
            return self

        def fetchall(self):
            return [
                (doc_id, 0, None, "Memo1", "", ""),
                (doc_id, 1, 1, "", "기본 수수료 요율", ""),
                (doc_id, 47, None, "출장비", "", ""),
                (doc_id, 999, 999, "", "미등록 사유", ""),
                (doc_id, 17, 13, "", "동일물건 재평가", ""),
                (doc_id, 23, 39, "", "임료 평가", ""),
            ]

    class Connection:
        def cursor(self):
            return Cursor()

        def close(self):
            pass

    class Engine:
        def raw_connection(self):
            return Connection()

    monkeypatch.setattr(evidence, "get_source_engine", Engine)

    result = evidence._apw_reasons([doc_id])

    assert [
        (reason["storage_key"], reason["display_code"])
        for reason in result[doc_id]
    ] == [(17, 13), (23, 39)]


def test_apw_bill_query_maps_only_verified_padded_types(monkeypatch):
    doc_id = "01-2607-A-0001"
    statements = []

    class Cursor:
        def execute(self, statement, params):
            statements.append(statement)
            return self

        def fetchall(self):
            def row(seq, gubun, charge=None, rate=1.0, dc=1.0):
                return (
                    doc_id, 101, seq, gubun, charge, rate, dc,
                    100 if str(gubun).strip() == "2" else None,
                    None, None, None, None, None, None, None, None,
                    None, None, None, None, None, None,
                )

            # 실제 SQL은 1·2만 반환하지만 Python gate도 자리표시자 0을 거른다.
            return [
                row(1, "0         "),
                row(2, "1         "),
                row(3, "2         ", "V", 0.8, 1.0),
            ]

    class Connection:
        def cursor(self):
            return Cursor()

        def close(self):
            pass

    class Engine:
        def raw_connection(self):
            return Connection()

    monkeypatch.setattr(evidence, "get_source_engine", Engine)

    result = _REAL_APW_BILL_REASONS([doc_id])

    assert "INNER JOIN APW_BILL b ON b.MasterID = m.MasterID" in statements[0]
    assert "RTRIM(ISNULL(b.SusuGubun, '')) IN ('1', '2')" in statements[0]
    assert [
        (reason["susu_gubun"], reason["reason_code"], reason["reason_label"])
        for reason in result[doc_id]
    ] == [
        ("1", "COURT_AUCTION", "경매"),
        ("2", "VOLUME", "종량제"),
    ]
    assert result[doc_id][1]["charge_gubun"] == "V"
    assert result[doc_id][1]["susu_rate"] == 0.8


@pytest.mark.parametrize(
    "gubun,purpose,title,expected_code,expected_opinion",
    [
        ("1         ", "민사소송", "소송 감정", "COURT_AUCTION", "경매"),
        ("2         ", "기타", "보상평가", "VOLUME", "종량제"),
    ],
)
def test_apw_bill_type_is_a_concise_structured_reason(
    monkeypatch, gubun, purpose, title, expected_code, expected_opinion
):
    row = item(purpose_name=purpose, title=title)
    monkeypatch.setattr(evidence, "_apw_reasons", lambda docs: {})
    monkeypatch.setattr(evidence, "_apw_bill_reasons", lambda docs: {
        row["doc_id"]: [{
            "source": "APW_BILL",
            "susu_gubun": gubun,
            "susu_rate": 1.0,
            "susu_dc": 1.0,
        }],
    })
    monkeypatch.setattr(evidence, "_fetch_jun", lambda items: {})

    summary = evidence.enrich_items([row])

    assert row["suggested_reason_code"] == expected_code
    assert row["suggested_opinion"] == expected_opinion
    assert row["evidence_level"] == evidence.STRUCTURED_CASE_SIGNAL
    assert row["evidence"][0]["selected"] is True
    assert row["source_row_json"]["AB"] == expected_opinion
    assert summary["apw_bill_found"] == 1


def test_conflicting_apw_bill_types_are_ambiguous(monkeypatch):
    row = item(purpose_name="", title="")
    monkeypatch.setattr(evidence, "_apw_reasons", lambda docs: {})
    monkeypatch.setattr(evidence, "_apw_bill_reasons", lambda docs: {
        row["doc_id"]: [
            {"source": "APW_BILL", "susu_gubun": "1"},
            {"source": "APW_BILL", "susu_gubun": "2"},
        ],
    })
    monkeypatch.setattr(evidence, "_fetch_jun", lambda items: {})

    summary = evidence.enrich_items([row])

    assert row["suggested_reason_code"] == "MULTIPLE"
    assert row["suggested_opinion"] == "복수사유확인"
    assert row["evidence_level"] == evidence.AMBIGUOUS
    assert summary["ambiguous"] == 1


def test_apw_bill_failure_does_not_break_other_reason_paths(monkeypatch):
    row = item()
    monkeypatch.setattr(evidence, "_apw_reasons", lambda docs: {})

    def fail(_docs):
        raise RuntimeError("secret-bearing source error")

    monkeypatch.setattr(evidence, "_apw_bill_reasons", fail)
    monkeypatch.setattr(evidence, "_fetch_jun", lambda items: {})

    summary = evidence.enrich_items([row])

    assert summary["apw_bill_error"] == "APWorks 청구구분 조회에 실패했습니다."
    assert "secret-bearing" not in summary["apw_bill_error"]
    assert row["suggested_opinion"] == "컨설팅"
    assert row["evidence_level"] == evidence.CONTEXT_ONLY


def test_multiple_distinct_apworks_reasons_are_ambiguous(monkeypatch):
    row = item(purpose_name="", title="")
    monkeypatch.setattr(evidence, "_apw_reasons", lambda docs: {
        row["doc_id"]: [
            {
                "source": "APWORKS",
                "storage_key": 0,
                "display_code": None,
                "item_note": "Memo1",
            },
            {
                "source": "APWORKS",
                "storage_key": 17,
                "display_code": 13,
                "contents": "동일물건 재평가",
            },
            {
                "source": "APWORKS",
                "storage_key": 23,
                "display_code": 39,
                "contents": "임료 평가",
            },
        ],
    })
    monkeypatch.setattr(evidence, "_fetch_jun", lambda items: {})

    summary = evidence.enrich_items([row])

    assert row["suggested_reason_code"] == "MULTIPLE"
    assert row["evidence_level"] == evidence.AMBIGUOUS
    assert row["suggested_opinion"] == "복수사유확인"
    assert len(row["evidence"]) == 2
    assert summary["ambiguous"] == 1


def test_equivalent_apworks_short_reason_collapses(monkeypatch):
    row = item(purpose_name="", title="")
    monkeypatch.setattr(evidence, "_apw_reasons", lambda docs: {
        row["doc_id"]: [
            {
                "source": "APWORKS",
                "storage_key": 17,
                "display_code": 13,
                "contents": "3개월 이내 동일물건 재평가",
            },
            {
                "source": "APWORKS",
                "storage_key": 18,
                "display_code": 14,
                "contents": "3개월 이내 재평가",
            },
        ],
    })
    monkeypatch.setattr(evidence, "_fetch_jun", lambda items: {})

    evidence.enrich_items([row])

    assert row["suggested_reason_code"] == "REAPPRAISAL"
    assert row["evidence_level"] == evidence.STRUCTURED_CASE_SIGNAL
    assert row["suggested_opinion"] == "3개월이내재평가"
    assert row["evidence"][0]["selected"] is True


def test_different_reappraisal_periods_are_ambiguous(monkeypatch):
    row = item(purpose_name="", title="")
    monkeypatch.setattr(evidence, "_apw_reasons", lambda docs: {
        row["doc_id"]: [
            {
                "source": "APWORKS",
                "storage_key": 17,
                "display_code": 13,
                "contents": "3개월 이내 동일물건 재평가",
            },
            {
                "source": "APWORKS",
                "storage_key": 19,
                "display_code": 15,
                "contents": "6개월 이내 재평가",
            },
        ],
    })
    monkeypatch.setattr(evidence, "_fetch_jun", lambda items: {})

    evidence.enrich_items([row])

    assert row["suggested_reason_code"] == "MULTIPLE"
    assert row["evidence_level"] == evidence.AMBIGUOUS
    assert row["suggested_opinion"] == "복수사유확인"


def test_selected_jun_evidence_survives_public_cap(monkeypatch):
    row = item()
    filler = [
        {
            "source": "JUN",
            "reason_code": "RENT",
            "reason_label": "임료·임대료 감정",
            "page_no": page,
            "direct_candidate": False,
        }
        for page in range(1, 13)
    ]
    selected = {
        "source": "JUN",
        "reason_code": "CONSULTING",
        "reason_label": "컨설팅·자문용역",
        "page_no": 13,
        "direct_candidate": True,
    }
    monkeypatch.setattr(evidence, "_apw_reasons", lambda docs: {})
    monkeypatch.setattr(evidence, "_fetch_jun", lambda items: {
        row["doc_id_normalized"]: {
            "search_state": evidence.FOUND,
            "evidence": [*filler, selected],
        },
    })

    evidence.enrich_items([row])

    assert row["suggested_opinion"] == "컨설팅"
    assert len(row["evidence"]) == 12
    assert row["evidence"][0]["reason_code"] == "CONSULTING"
    assert row["evidence"][0]["selected"] is True
    assert any(
        item.get("reason_code") == row["suggested_reason_code"]
        and item.get("selected")
        for item in row["evidence"]
    )


def test_no_reason_still_gets_factual_manual_draft(monkeypatch):
    row = item(purpose_name="", title="")
    monkeypatch.setattr(evidence, "_apw_reasons", lambda docs: {})
    monkeypatch.setattr(evidence, "_fetch_jun", lambda items: {})

    summary = evidence.enrich_items([row])

    assert row["evidence_level"] == evidence.NONE
    assert row["suggested_reason_code"] == "MANUAL_REQUIRED"
    assert row["suggested_reason_label"] == "기타 확인"
    assert row["suggested_opinion"] == "담당자확인요청"
    assert summary["manual_required"] == 1


def test_jun_failure_does_not_break_apworks_and_context(monkeypatch):
    row = item()
    monkeypatch.setattr(evidence, "_apw_reasons", lambda docs: {})

    def fail(items):
        raise RuntimeError("secret-bearing driver message")

    monkeypatch.setattr(evidence, "_fetch_jun", fail)
    summary = evidence.enrich_items([row])

    assert summary["jun_error"] == "JUN 근거 조회를 사용할 수 없습니다."
    assert "secret-bearing" not in summary["jun_error"]
    assert row["evidence_level"] == evidence.CONTEXT_ONLY
    assert row["search_state"] == evidence.EVIDENCE_ERROR


def test_jun_target_cte_uses_sql_server_compatible_values(monkeypatch):
    statements = []

    class Cursor:
        def execute(self, statement, params):
            statements.append(statement)
            return self

        def fetchall(self):
            return []

    class Connection:
        def cursor(self):
            return Cursor()

        def close(self):
            pass

    monkeypatch.setattr(evidence, "_connect_jun", Connection)

    result = evidence._fetch_jun([{
        "doc_id_normalized": "012607A0001",
    }])

    assert result["012607A0001"]["search_state"] == evidence.NO_CASE
    assert len(statements) == 2
    assert all("FROM (VALUES" in statement for statement in statements)
    assert all("AS (VALUES" not in statement for statement in statements)


def test_jun_page_search_ranks_per_reason_and_keeps_late_reason(monkeypatch):
    normalized = "012607A0001"
    statements = []
    parameter_sets = []
    responses = iter([
        [("01-2607-A-0001", normalized, 101, 1, "01")],
        [(
            normalized, 101, 1, 501, "감정평가서.pdf", "report",
            "done", 1, "sha-501", "2026-07-29 09:00:00",
        ), (
            normalized, 101, 1, 502, "부속자료.pdf", "attachment",
            "done", 1, "sha-502", "2026-07-29 09:00:01",
        )],
        [
            (
                501, 11, 1, "CONSULTING", "컨설팅 업무를 수행한다.",
                "page-sha-11", "ocr", "v1", 0.95,
                1, 1, 1, 1,
            ),
            (
                # 섹션이 붙어 있는데 전부 etc인 쪽 → 직접근거 후보에서 뺀다.
                501, 99, 99, "RENT", "후반부에서 임료 감정 목적을 확인한다.",
                "page-sha-99", "ocr", "v1", 0.92,
                1, 0, 0, 1,
            ),
            (
                # 섹션이 아예 없는 쪽 → 분류 안 됨이라 confidence 규칙을 그대로 쓴다.
                501, 120, 120, "VOLUME", "종량제 방식으로 산정한다.",
                "page-sha-120", "ocr", "v1", 0.93,
                1, 0, 0, 0,
            ),
        ],
    ])

    class Cursor:
        def execute(self, statement, params):
            statements.append(statement)
            parameter_sets.append(list(params))
            self.rows = next(responses)
            return self

        def fetchall(self):
            return self.rows

    class Connection:
        def cursor(self):
            return Cursor()

        def close(self):
            pass

    def unexpected_rematch(*args, **kwargs):
        raise AssertionError("SQL-matched reason should be consumed directly")

    monkeypatch.setattr(evidence, "_connect_jun", Connection)
    monkeypatch.setattr(evidence, "_matching_rules", unexpected_rematch)

    result = evidence._fetch_jun([{"doc_id_normalized": normalized}])

    page_statement = " ".join(statements[2].split())
    assert len(statements) == 3
    assert "WITH terms(reason_code, keyword) AS" in page_statement
    assert "SELECT DISTINCT pt.document_version_id, pt.page_id, pt.page_no" in (
        page_statement
    )
    assert "FROM (VALUES" in page_statement
    assert "AS v(reason_code, keyword)" in page_statement
    assert "PARTITION BY document_version_id, reason_code" in page_statement
    assert "WHEN confidence >= 0.80 THEN 0" in page_statement
    assert "WHERE h.rn <= 3" in page_statement
    # 5A: OCR 교정본을 우선 검색하고, 정규화가 없는 쪽만 원문으로 떨어진다.
    assert "COALESCE(n.search_text_content, p.text_content)" in page_statement
    assert "ptn.is_published = 1" in page_statement
    # 5B: 섹션 종류를 함께 읽어 etc 단독 쪽을 직접근거에서 뺀다.
    assert "FROM jun.section_span sp" in page_statement
    assert "s.section_type <> N'etc'" in page_statement
    # `{ids}`가 page_text·page_section 두 곳에 들어가므로 문서버전 목록도 두 번 넘어간다.
    # 한 번만 넘기면 pyodbc가 파라미터 수 불일치로 죽고, 예외가 삼켜져 근거가 0건이 된다.
    assert parameter_sets[2][-4:] == [501, 502, 501, 502]
    assert page_statement.count("document_version_id IN (") == 2
    # 자리표시자 수와 실제 파라미터 수가 같아야 한다(실측 84 vs 83 결함).
    assert page_statement.count("?") == len(parameter_sets[2])
    assert [
        (entry["reason_code"], entry["page_no"])
        for entry in result[normalized]["evidence"]
    ] == [("CONSULTING", 1), ("RENT", 99), ("VOLUME", 120)]
    assert result[normalized]["evidence"][1]["reason_label"] == "임료·임대료 감정"
    # 신뢰도는 둘 다 0.80 이상이지만, 섹션 종류가 etc뿐인 쪽은 직접근거 후보가 아니다.
    assert result[normalized]["evidence"][0]["direct_candidate"] is True
    assert result[normalized]["evidence"][1]["direct_candidate"] is False
    assert result[normalized]["evidence"][2]["direct_candidate"] is True
    assert result[normalized]["evidence"][0]["section_fee_basis"] is True


def test_asset_revaluation_context_is_not_generic_reappraisal():
    codes = {
        rule.code for rule in evidence._matching_rules("자산재평가 목적 감정평가")
    }

    assert "ASSET_REVALUATION" in codes
    assert "REAPPRAISAL" not in codes


# ---------------------------------------------------------------------------
# 계산 기반 사유 (문서 근거가 전혀 없을 때만 동작한다)
#
# 실측 근거: 2026-05 상반 본사 130행에서 재무팀이 수기로 적었으나 자동으로 못 잡던
# 6건 중 2건이 날짜·금액만으로 확정 가능했다.
#   01-2508-4-0276 기준시점 2023-03-22 / 접수 2025-08-20 → 재무 AB '소급감정'
#   01-2603-4-0100 하한 65,098,539 / 실제 65,031,000 → 재무 AB '수수료차액발생 67,539'
# 두 규칙 모두 MANUAL_REQUIRED 폴백 직전에만 보므로 기존 사유를 덮지 않는다.
# ---------------------------------------------------------------------------


def test_retrospective_is_detected_from_base_date_before_receipt(monkeypatch):
    """6개월 이상 소급이면 날짜 계산만으로 `소급감정`을 확정한다.

    보수기준 할증 대상이 6개월 이상 소급(APW_IW_SusuWhy.Code=2)이라서다.
    실측 01-2508-4-0276은 880일 소급이고 재무팀 AB도 `소급감정`이다.
    """
    monkeypatch.setattr(evidence, "_fetch_jun", lambda items: {})
    monkeypatch.setattr(evidence, "_apw_reasons", lambda docs: {})
    rows = [item(
        purpose_name="HUG(시가참고)", title="서울특별시 중구 토지 부동산",
        base_date="2023-03-22", receipt_date="2025-08-20",
        deviation_direction="상한 초과",
        actual_fee=23_147_056, lower_fee=15_431_371, upper_fee=23_022_056,
        gap_amount=124_999,
    )]
    evidence.enrich_items(rows)
    assert rows[0]["suggested_reason_code"] == "RETROSPECTIVE"
    assert rows[0]["suggested_opinion"] == "소급감정"
    assert rows[0]["evidence_level"] == evidence.CALCULATED


def test_absurd_base_date_is_not_treated_as_retrospective(monkeypatch):
    """원천 오류로 기준시점이 1900년대인 행(실측 2건)을 사유로 오인하지 않는다."""
    monkeypatch.setattr(evidence, "_fetch_jun", lambda items: {})
    monkeypatch.setattr(evidence, "_apw_reasons", lambda docs: {})
    rows = [item(
        purpose_name="기타", title="토지",
        base_date="1900-01-01", receipt_date="2026-03-20",
        deviation_direction="하한 미만",
        actual_fee=1, lower_fee=10_000_000, upper_fee=15_000_000,
        gap_amount=-9_999_999,
    )]
    evidence.enrich_items(rows)
    assert rows[0]["suggested_reason_code"] == "MANUAL_REQUIRED"
    assert rows[0]["suggested_opinion"] == "담당자확인요청"


def test_minor_fee_gap_reports_the_amount_like_the_finance_sheet(monkeypatch):
    """넘은 폭이 미미하면 사유 대신 차액 금액을 적는다(재무팀 관례).

    차액은 동결 원천 금액에서 정확히 나오므로 확인 후보가 아니라 사실이다.
    """
    monkeypatch.setattr(evidence, "_fetch_jun", lambda items: {})
    monkeypatch.setattr(evidence, "_apw_reasons", lambda docs: {})
    rows = [item(
        purpose_name="HUG(시가참고)", title="충청북도 청주시 토지 부동산",
        base_date="2026-03-31", receipt_date="2026-03-20",
        deviation_direction="하한 미만",
        actual_fee=65_031_000, lower_fee=65_098_539, upper_fee=97_522_809,
        gap_amount=-67_539.35,
    )]
    evidence.enrich_items(rows)
    assert rows[0]["suggested_reason_code"] == "FEE_GAP_MINOR"
    assert rows[0]["suggested_opinion"] == "수수료차액발생 67,539"
    assert rows[0]["evidence_level"] == evidence.CALCULATED


def test_large_gap_stays_manual_instead_of_reporting_amount(monkeypatch):
    """차액이 크면 금액만 적어 넘기지 않는다 — 사유 확인이 필요하다."""
    monkeypatch.setattr(evidence, "_fetch_jun", lambda items: {})
    monkeypatch.setattr(evidence, "_apw_reasons", lambda docs: {})
    rows = [item(
        purpose_name="HUG(기타담보)", title="담보물",
        base_date="2026-02-25", receipt_date="2026-02-24",
        deviation_direction="하한 미만",
        actual_fee=57_357_558, lower_fee=81_939_369, upper_fee=122_784_054,
        gap_amount=-24_581_811,
    )]
    evidence.enrich_items(rows)
    assert rows[0]["suggested_reason_code"] == "MANUAL_REQUIRED"


def test_calculated_reason_never_overrides_document_evidence(monkeypatch):
    """계산 사유는 폴백 직전이라 문서·문맥 근거가 있으면 그쪽이 이긴다.

    실측에서 소급 후보 6건 중 3건은 이미 COURT_AUCTION 등 사유가 붙어 있었다.
    """
    monkeypatch.setattr(evidence, "_apw_reasons", lambda docs: {})
    monkeypatch.setattr(
        evidence, "_fetch_jun",
        lambda items: {items[0]["doc_id_normalized"]: {
            "status": evidence.FOUND,
            "evidence": [{
                "source": "JUN", "reason_code": "RENT",
                "reason_label": "임료·임대료 감정", "direct_candidate": True,
                "sentence": "차임 산정을 위한 임료 평가",
            }],
        }},
    )
    rows = [item(
        purpose_name="임료 감정", title="임대료 산정",
        base_date="2023-01-01", receipt_date="2026-03-20",  # 소급 후보이기도 함
        deviation_direction="하한 미만", gap_amount=-50_000,
        actual_fee=900_000, lower_fee=1_000_000, upper_fee=1_500_000,
    )]
    evidence.enrich_items(rows)
    assert rows[0]["suggested_reason_code"] == "RENT"
    assert rows[0]["evidence_level"] == evidence.DIRECT


# ---------------------------------------------------------------------------
# 동일 물건 재평가 (같은 법정 지번의 직전 감정서로 판정)
#
# 실측 근거: 2026-05 상반에서 재무팀이 재평가로 적었으나 자동으로 못 잡던 3건이
# APW_MASTEREX의 지번(REG·EUB·SAN·BUN1·BUN2)으로 직전 건을 찾을 수 있었다.
#   01-2602-3-0636 ← 01-2507-3-2315  간격 232일 → 재무 AB '1년이내재평가'
#   01-2602-3-0644 ← 01-2602-4-0060  같은 날 평가 → 재무 AB '1개월이내재평가'
#   01-2603-4-0131 ← 01-2503-4-0105  간격 363일 → 재무 AB '1년이내재평가'
# 간격은 현재 기준시점 − 직전 발송일로 센다(발송일끼리 재면 377일이 되어 구간이 어긋난다).
# ---------------------------------------------------------------------------


def _quiet(monkeypatch):
    monkeypatch.setattr(evidence, "_fetch_jun", lambda items: {})
    monkeypatch.setattr(evidence, "_apw_reasons", lambda docs: {})


def test_prior_appraisal_on_same_parcel_becomes_period_reappraisal(monkeypatch):
    """직전 평가와의 간격을 재무팀 표기(N이내재평가)로 바꾼다.

    확정 조건은 '엄격한 선후관계 + 의뢰인이나 평가목적 일치'다. 주소만 같으면
    다른 의뢰인의 별건일 수 있어 확정하지 않는다.
    """
    _quiet(monkeypatch)
    monkeypatch.setattr(
        evidence, "_prior_reappraisals",
        lambda docs: {docs[0]: {
            "prior_doc": "01-2503-4-0105", "sent": "2025-04-02",
            "same_client": True, "same_purpose": False, "strictly_before": True,
        }},
    )
    rows = [item(
        doc_id="01-2603-4-0131", purpose_name="HUG(시가참고)",
        title="경기도 성남시 분당구 정자동 토지 부동산",
        base_date="2026-03-31", receipt_date="2026-03-30",
        deviation_direction="하한 미만", gap_amount=-5_214_600,
        actual_fee=12_167_400, lower_fee=17_382_000, upper_fee=25_948_000,
    )]
    evidence.enrich_items(rows)
    assert rows[0]["suggested_reason_code"] == "REAPPRAISAL"
    # AB에는 핵심어만 넣는다 — 직전 감정서번호는 내부 근거(label)로만 남긴다.
    assert rows[0]["suggested_opinion"] == "1년이내재평가"
    assert "01-2503-4-0105" in rows[0]["suggested_reason_label"]
    assert rows[0]["evidence_level"] == evidence.CALCULATED


def test_same_day_pair_is_confirmed_within_the_one_month_band(monkeypatch):
    """며칠 뒤집혀 들어온 쌍도 1개월 구간 안이라는 사실은 방향과 무관하게 참이다.

    실측 01-2602-3-0644 ↔ 01-2602-4-0060은 발송일이 같고, 재무팀도
    `1개월이내재평가`로 확정했다. 다만 뒤집힘이 1개월을 넘으면 확정하지 않는다
    (아래 test_large_reverse_order_is_a_check_candidate).
    """
    _quiet(monkeypatch)
    monkeypatch.setattr(
        evidence, "_prior_reappraisals",
        lambda docs: {docs[0]: {
            "prior_doc": "01-2602-4-0060", "sent": "2026-03-09",
            "same_client": True, "same_purpose": True, "strictly_before": True,
        }},
    )
    rows = [item(
        doc_id="01-2602-3-0644", purpose_name="주1순위근저당담보", title="담보물",
        base_date="2026-03-03", receipt_date="2026-02-24",
        deviation_direction="하한 미만", gap_amount=-115_457_400,
        actual_fee=12_828_600, lower_fee=128_286_000, upper_fee=192_304_000,
    )]
    evidence.enrich_items(rows)
    assert rows[0]["suggested_reason_code"] == "REAPPRAISAL"
    assert rows[0]["suggested_opinion"] == "1개월이내재평가"


def test_large_reverse_order_is_a_check_candidate(monkeypatch):
    """기준시점이 직전 발송보다 1개월 넘게 앞서면 원천 선후관계를 믿을 수 없다."""
    _quiet(monkeypatch)
    monkeypatch.setattr(
        evidence, "_prior_reappraisals",
        lambda docs: {docs[0]: {
            "prior_doc": "01-2606-4-0001", "sent": "2026-06-30",
            "same_client": True, "same_purpose": True, "strictly_before": False,
        }},
    )
    rows = [item(
        doc_id="01-2603-4-0131", purpose_name="HUG(시가참고)", title="토지 부동산",
        base_date="2026-03-01", receipt_date="2026-03-02",
        deviation_direction="하한 미만", gap_amount=-5_214_600,
        actual_fee=12_167_400, lower_fee=17_382_000, upper_fee=25_948_000,
    )]
    evidence.enrich_items(rows)
    assert rows[0]["suggested_reason_code"] == "REAPPRAISAL_CHECK"
    assert rows[0]["suggested_opinion"] == "재평가확인"
    assert "선후관계 불명확" in rows[0]["suggested_reason_label"]


def test_prior_appraisal_older_than_two_years_is_not_a_reason(monkeypatch):
    """2년을 넘긴 직전 평가는 할인 근거가 아니므로 사유로 쓰지 않는다."""
    _quiet(monkeypatch)
    monkeypatch.setattr(
        evidence, "_prior_reappraisals",
        lambda docs: {docs[0]: {
            "prior_doc": "01-2201-4-0019", "sent": "2022-01-27",
            "same_client": True, "same_purpose": True, "strictly_before": True,
        }},
    )
    rows = [item(
        purpose_name="HUG(시가참고)", title="토지 부동산",
        base_date="2026-03-31", receipt_date="2026-03-30",
        deviation_direction="하한 미만", gap_amount=-5_214_600,
        actual_fee=12_167_400, lower_fee=17_382_000, upper_fee=25_948_000,
    )]
    evidence.enrich_items(rows)
    assert rows[0]["suggested_reason_code"] == "MANUAL_REQUIRED"


def test_minor_gap_wins_over_reappraisal(monkeypatch):
    """실측 01-2603-4-0100은 직전 평가(55일)가 있어도 재무팀은 차액만 적었다."""
    _quiet(monkeypatch)
    monkeypatch.setattr(
        evidence, "_prior_reappraisals",
        lambda docs: {docs[0]: {
            "prior_doc": "012601-4-0013-2", "sent": "2026-02-04",
            "same_client": True, "same_purpose": True, "strictly_before": True,
        }},
    )
    rows = [item(
        doc_id="01-2603-4-0100", purpose_name="HUG(시가참고)", title="토지 부동산",
        base_date="2026-03-31", receipt_date="2026-03-20",
        deviation_direction="하한 미만", gap_amount=-67_539.35,
        actual_fee=65_031_000, lower_fee=65_098_539, upper_fee=97_522_809,
    )]
    evidence.enrich_items(rows)
    assert rows[0]["suggested_reason_code"] == "FEE_GAP_MINOR"


def test_address_and_period_alone_confirm_reappraisal(monkeypatch):
    """의뢰인·평가목적이 달라도 같은 지번·기간이면 확정한다.

    재무팀이 확정한 4건(01-2602-3-0636, 01-2603-4-0131, 01-2602-3-0644,
    01-2602-4-0060) 모두 의뢰인·평가목적이 달랐다. 재평가 할인의 근거는
    '같은 물건을 다시 조사하지 않는다'는 사실이라 의뢰인이 바뀌어도 성립한다.
    """
    _quiet(monkeypatch)
    monkeypatch.setattr(
        evidence, "_prior_reappraisals",
        lambda docs: {docs[0]: {
            "prior_doc": "01-2503-4-0105", "sent": "2025-04-02",
            "same_client": False, "same_purpose": False, "strictly_before": True,
        }},
    )
    rows = [item(
        doc_id="01-2603-4-0131", purpose_name="HUG(시가참고)",
        title="경기도 성남시 분당구 정자동 토지 부동산",
        base_date="2026-03-31", receipt_date="2026-03-30",
        deviation_direction="하한 미만", gap_amount=-5_214_600,
        actual_fee=12_167_400, lower_fee=17_382_000, upper_fee=25_948_000,
    )]
    evidence.enrich_items(rows)
    assert rows[0]["suggested_reason_code"] == "REAPPRAISAL"
    assert rows[0]["suggested_opinion"] == "1년이내재평가"
    # 이전 감정서번호는 AB가 아니라 내부 근거에만 남는다.
    assert "01-2503-4-0105" in rows[0]["suggested_reason_label"]


def test_missing_jun_document_says_so_instead_of_generic_manual(monkeypatch):
    """문서가 없어서 못 찾은 건과 문서에 단서가 없는 건을 구분한다.

    담당자가 해야 할 일이 다르다 — 전자는 문서 확보, 후자는 내용 판단이다.
    """
    monkeypatch.setattr(evidence, "_apw_reasons", lambda docs: {})
    monkeypatch.setattr(evidence, "_prior_reappraisals", lambda docs: {})
    monkeypatch.setattr(
        evidence, "_fetch_jun",
        lambda items: {items[0]["doc_id_normalized"]: {
            "search_state": evidence.NO_DOCUMENT, "evidence": [],
        }},
    )
    rows = [item(
        purpose_name="기타", title="토지",
        base_date="2026-03-25", receipt_date="2026-03-20",
        deviation_direction="하한 미만", gap_amount=-24_581_811,
        actual_fee=57_357_558, lower_fee=81_939_369, upper_fee=122_784_054,
    )]
    evidence.enrich_items(rows)
    assert rows[0]["suggested_reason_code"] == "JUN_NO_DOCUMENT"
    assert rows[0]["suggested_opinion"] == "JUN문서없음"
    assert rows[0]["evidence_level"] == evidence.NO_DOCUMENT_LEVEL


def test_prior_lookup_failure_does_not_break_other_paths(monkeypatch):
    """이전 감정서 조회가 실패해도 다른 사유 경로와 요약은 살아 있어야 한다."""
    _quiet(monkeypatch)

    def boom(docs):
        raise RuntimeError("APW_MASTEREX 조회 실패")

    monkeypatch.setattr(evidence, "_prior_reappraisals", boom)
    rows = [item(purpose_name="컨설팅 용역", title="부동산 컨설팅")]
    summary = evidence.enrich_items(rows)
    assert summary["prior_error"] is not None
    assert rows[0]["suggested_reason_code"] == "CONSULTING"
