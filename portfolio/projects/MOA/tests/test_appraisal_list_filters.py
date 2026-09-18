"""감정서 목록 검색조건(WHERE) 조립 테스트."""

from datetime import date

from app.services.appraisals import _where_clause


def _where(**kwargs) -> tuple[str, dict]:
    """_where_clause는 위치인자가 많아 테스트에서는 기본값을 채워 호출한다."""
    defaults = dict(
        doc_id=None, address=None, customer_name=None, manager=None, charge=None,
        status=None, date_from=None, date_to=None, office_code=None,
    )
    defaults.update(kwargs)
    return _where_clause(
        defaults["doc_id"], defaults["address"], defaults["customer_name"],
        defaults["manager"], defaults["charge"], defaults["status"],
        defaults["date_from"], defaults["date_to"], defaults["office_code"],
        cust_doc_id=defaults.get("cust_doc_id"),
    )


def test_cust_doc_id_uses_like_on_custdocid_column():
    where, params = _where(cust_doc_id="TADA265287")

    assert "CustDocid LIKE :cust_doc_id" in where
    assert params["cust_doc_id"] == "%TADA265287%"


def test_cust_doc_id_absent_when_not_given():
    where, params = _where(address="서울")

    assert "CustDocid" not in where
    assert "cust_doc_id" not in params


def test_cust_doc_id_search_ignores_receipt_date_range():
    """의뢰문서번호를 아는 사람은 접수일을 모르므로 기간 조건을 걸지 않는다."""
    where, params = _where(
        cust_doc_id="TADA265287", date_from=date(2026, 7, 1), date_to=date(2026, 7, 31)
    )

    assert "ReceiptDate" not in where
    assert "date_from" not in params and "date_to" not in params


def test_date_range_still_applies_without_number_search():
    where, params = _where(date_from=date(2026, 7, 1), date_to=date(2026, 7, 31))

    assert "ReceiptDate >= :date_from" in where
    assert params["date_from"] == date(2026, 7, 1)
