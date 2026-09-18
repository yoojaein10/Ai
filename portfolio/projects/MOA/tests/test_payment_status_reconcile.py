from unittest.mock import MagicMock

from app.services import payment_status


def test_apworks_only_change_reconciles_stored_payment_status(monkeypatch):
    monkeypatch.setattr(payment_status, "_source_db", lambda: "apworksdw")
    db = MagicMock()
    db.execute.return_value.rowcount = 3

    changed = payment_status.reconcile_payment_status_with_master(db)

    sql = str(db.execute.call_args.args[0])
    assert "a10_payment_status" in sql
    assert "a10_receivable_summary" in sql
    assert "[apworksdw].dbo.apw_masterex" in sql
    assert "m.[청구금액] - s.received_amount <= 1000" in sql
    assert "ISNULL(p.pay_result, N'') <> e.pay_result" in sql
    assert changed == 3
    db.commit.assert_called_once_with()
