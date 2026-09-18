from datetime import timedelta
from pathlib import Path

import pandas as pd

from paper_trader import StockPaperTrader
from strategy import snapshot


def rising_candles(count: int = 100) -> pd.DataFrame:
    rows = []
    for index in range(count):
        close = 100_000 + index * 500
        rows.append(
            {
                "time": pd.Timestamp("2026-07-20 09:00")
                + timedelta(minutes=15 * index),
                "open": close - 200,
                "high": close + 300,
                "low": close - 500,
                "close": close,
                "volume": 10_000 + index * 100,
                "closed": True,
            }
        )
    return pd.DataFrame(rows)


def test_strategy_returns_complete_snapshot():
    result = snapshot(rising_candles())
    assert 0 <= result["buy_score"] <= 5
    assert result["atr"] > 0
    assert set(result["buy_checks"]) == {"vwap", "ema", "rsi", "bollinger", "trend"}


def test_stock_order_uses_integer_shares_and_round_trip_costs(tmp_path: Path):
    trader = StockPaperTrader(tmp_path / "state.json")
    assert trader.buy("005930", "삼성전자", 200_000, 5_000, "test")
    position = trader.snapshot()["positions"][0]
    assert isinstance(position["quantity"], int)
    assert position["quantity"] > 0
    assert trader.sell("005930", 210_000, "test")
    account = trader.snapshot()
    assert not account["positions"]
    assert len(account["trades"]) == 2


def test_auto_trade_refuses_stale_quote(tmp_path: Path):
    trader = StockPaperTrader(tmp_path / "state.json")
    signal = {
        "time": "2026-07-30T09:15:00",
        "atr": 5_000,
        "buy_signal": True,
        "sell_signal": False,
    }
    action = trader.evaluate("005930", "삼성전자", 210_000, signal, True, False)
    assert action is None
    assert trader.snapshot()["positions"] == []
