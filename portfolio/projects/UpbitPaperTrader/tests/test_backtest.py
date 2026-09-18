import unittest

import pandas as pd

from backtest import simulate_portfolio, validate_candle_histories


class BacktestTests(unittest.TestCase):
    def test_target_exit_produces_winning_trade(self):
        frame = pd.DataFrame(
            [
                {
                    "time": "2026-01-01T00:00:00",
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.0,
                    "atr": 10.0,
                    "buy_signal": True,
                    "sell_signal": False,
                },
                {
                    "time": "2026-01-01T00:15:00",
                    "open": 100.0,
                    "high": 105.0,
                    "low": 99.0,
                    "close": 102.0,
                    "atr": 10.0,
                    "buy_signal": False,
                    "sell_signal": False,
                },
                {
                    "time": "2026-01-01T00:30:00",
                    "open": 102.0,
                    "high": 121.0,
                    "low": 101.0,
                    "close": 120.0,
                    "atr": 10.0,
                    "buy_signal": False,
                    "sell_signal": False,
                },
            ]
        )
        result = simulate_portfolio({"KRW-TEST": frame}, initial_cash=10_000_000)
        self.assertEqual(result["trades"], 1)
        self.assertEqual(result["wins"], 1)
        self.assertGreater(result["total_return"], 0)

    def test_candle_validation_detects_duplicates_and_invalid_ohlc(self):
        row = {
            "candle_date_time_utc": "2026-01-01T00:00:00",
            "opening_price": 100,
            "high_price": 90,
            "low_price": 95,
            "trade_price": 100,
            "candle_acc_trade_volume": 1,
        }
        result = validate_candle_histories({"KRW-TEST": [row, dict(row)]})
        self.assertFalse(result["valid"])
        self.assertEqual(result["markets"][0]["duplicates"], 1)
        self.assertEqual(result["markets"][0]["invalid_ohlc"], 2)


if __name__ == "__main__":
    unittest.main()
