from app.services.receivables import receivable_status_cte


def test_receivable_cte_nets_non_cash_sales_reversal_from_billed_amount():
    sql = receivable_status_cte("management_no IS NOT NULL")

    assert "WHEN e.ar_credit > 0" in sql
    assert "AND (e.bank_net + e.hq_net) = 0" in sql
    assert "AND e.fee_credit < 0" in sql
    assert "THEN e.ar_credit" in sql


def test_receivable_cte_caps_correction_credit_at_other_voucher_debits():
    """같은 전표 안 발생+상쇄(거래처 정정)는 다른 전표 발생액까지만 청구에서
    뺀다. 선수금·가수금 상계 전표(지사 정산 관행)는 정정으로 보지 않는다."""
    sql = receivable_status_cte("management_no IS NOT NULL")

    assert "THEN e.ar_credit ELSE 0 END AS corr_credit" in sql
    assert "THEN e.ar_debit ELSE 0 END AS corr_debit" in sql
    assert "AND e.advance_net >= 0 AND e.suspense_net >= 0" in sql
    assert "CASE WHEN SUM(corr_credit) < SUM(ar_debit) - SUM(corr_debit)" in sql


def test_receivable_cte_keeps_cash_linked_ar_credit_as_receipt():
    sql = receivable_status_cte("management_no IS NOT NULL")

    assert "CASE WHEN (e.bank_net + e.hq_net) <> 0 THEN" in sql
    assert "e.ar_credit + e.advance_net + e.suspense_net" in sql
