import pytest

from app.services.payment_sms import (
    PaymentSmsError,
    _clean_phone,
    auto_send_pending,
    build_alimtalk_body,
    build_filters,
    mark_sent,
    sms_recipients,
)


def test_auto_send_requires_start_date(monkeypatch):
    """스위치가 켜져 있어도 운영 시작일이 없거나 형식이 틀리면 자동발송하지 않는다.

    과거 건 오발송 방지 (2026-07-31 사용자 확정: 시작일 이후 입금분만).
    db=None을 넘겨도 DB에 닿기 전에 반환해야 한다.
    """
    import app.services.payment_sms as module

    class FakeSettings:
        payment_alert_auto_send = True
        payment_alert_test_phone = ""
        payment_alert_auto_days = 3
        payment_alert_start_date = ""
        bizppurio_db = "KakaoMMs"
        bizppurio_sender_key = "k"
        bizppurio_template_code = "t"
        bizppurio_send_phone = '010-0000-0000'
        is_bizppurio_configured = True

    monkeypatch.setattr(module, "get_settings", lambda: FakeSettings())
    assert auto_send_pending(None) is None          # 시작일 미설정
    FakeSettings.payment_alert_start_date = "2026-13-99"
    assert auto_send_pending(None) is None          # 형식 오류


def test_clean_phone_normalizes_and_rejects():
    assert _clean_phone('010-0000-0000') == '010-0000-0000'
    assert _clean_phone(' 010-0000-0000 ') == '010-0000-0000'
    assert _clean_phone("7858") is None       # 내선번호
    assert _clean_phone("02-555-1234") is None  # 일반전화
    assert _clean_phone(None) is None


def test_build_alimtalk_body_matches_template_variables():
    # 템플릿 '입금내역알림'(bizp_20260728...) 변수 6개 치환 — 본문 불일치 시 발송 거부되므로 고정 검증
    body = build_alimtalk_body({
        "doc_id": "01-2606-3-1889",
        "paid_date": "2026-07-29",
        "total_amount": 13140600,
        "paid_amount": 11946000,
        "customer_name": "한국투자저축은행 금융3팀장",
        "address": "서울특별시 강남구",
    })
    assert body.startswith("[감정물건 입금내역 안내]")
    assert "1. 감정번호: 01-2606-3-1889" in body
    assert "2. 입금일자: 2026-07-29" in body
    assert "3. 매출총액: 13,140,600원" in body
    assert "4. 입금합계: 11,946,000원" in body
    assert "5. 거래처: 한국투자저축은행 금융3팀장" in body
    assert "6. 소재지: 서울특별시 강남구" in body
    assert body.endswith("재무팀으로 연락 부탁드립니다.")


def test_sms_recipients_common_only_excluded():
    # 공(...)·'공통'(공시업무)뿐이면 수신자 없음 → 목록 제외 대상
    assert sms_recipients("공(서정석)") is None
    assert sms_recipients("공통") is None
    assert sms_recipients(None) is None
    assert sms_recipients("") is None


def test_sms_recipients_kdb_mixed_manager():
    # KDB산업은행 패턴: 공(...)과 같이 등록된 일반 담당자가 수신자
    assert sms_recipients("윤도,공(장재원)") == "윤도"
    assert sms_recipients("공(황인석), 윤도") == "윤도"
    assert sms_recipients("김도윤") == "김도윤"
    assert sms_recipients("김도윤,이재형") == "김도윤, 이재형"


def test_build_filters_sent_states():
    # sent/unsent = 큐 행의 처리 여부 (2026-07-31 큐 기반 목록 전환)
    clauses, params = build_filters("sent", None)
    assert clauses == ["n.sent_at IS NOT NULL"]
    assert params == {}
    clauses, _ = build_filters("unsent", None)
    assert clauses == ["n.sent_at IS NULL"]
    clauses, _ = build_filters("all", None)
    assert clauses == []


def test_build_filters_query_uses_bind_param():
    # 검색어는 반드시 바인드 파라미터로만 — SQL 문자열에 값이 섞이면 안 된다
    clauses, params = build_filters("all", "  '; DROP TABLE x --  ")
    assert params == {"query": "%'; DROP TABLE x --%"}
    assert all(":query" in clause for clause in clauses)
    assert "DROP" not in " ".join(clauses)


def test_build_filters_blank_query_ignored():
    clauses, params = build_filters("all", "   ")
    assert clauses == [] and params == {}


def test_mark_sent_rejects_empty_and_oversized():
    with pytest.raises(PaymentSmsError):
        mark_sent(None, [" ", ""], True, 1)
    with pytest.raises(PaymentSmsError):
        mark_sent(None, [f"01-{i}" for i in range(201)], True, 1)
