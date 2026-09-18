"""CB2_ACCT_HIS 조회 — 입금만/전체 거래, 읽기 전용."""

from app.services import deposit_source


def test_입금_조회는_INOUT_2만_본다():
    sql, params = deposit_source.build_query("20260825", "20260826", "2")
    assert "h.INOUT_GUBUN = ?" in sql
    assert params == ("20260825", "20260826", "2")


def test_전체_거래_조회는_구분_조건이_없고_구분_열을_준다():
    sql, params = deposit_source.build_query("20260825", "20260825", None)
    assert "INOUT_GUBUN = ?" not in sql
    assert "h.INOUT_GUBUN" in sql and "h.ACCT_TXTIME" in sql, "대사 화면이 입·출금 구분과 시각을 쓴다"
    assert params == ("20260825", "20260825")


def test_읽기_전용이다():
    sql, _ = deposit_source.build_query("20260825", "20260825", None)
    upper = sql.upper()
    assert upper.lstrip().startswith("SELECT")
    assert not any(word in upper for word in ("UPDATE ", "INSERT ", "DELETE ", "MERGE "))


def test_fetch_deposits는_입금_래퍼다(monkeypatch):
    seen = {}

    def fake(date_from, date_to, inout=None):
        seen.update(date_from=date_from, date_to=date_to, inout=inout)
        return []

    monkeypatch.setattr(deposit_source, "fetch_transactions", fake)
    assert deposit_source.fetch_deposits("20260801", "20260825") == []
    assert seen == {"date_from": "20260801", "date_to": "20260825", "inout": "2"}
