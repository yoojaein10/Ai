import unittest

import pandas as pd

from indicators import _rsi
from indicators import (
    adaptive_signal_snapshot,
    buy_threshold_met,
    calculate_indicators,
    signal_snapshot,
)
from upbit_public import completed_candles


def fake_candles(count=80):
    rows = []
    for index in range(count):
        close = 100 + index * 0.2 + ((index % 7) - 3) * 0.3
        rows.append(
            {
                "candle_date_time_kst": f"2026-01-01T{index // 4:02d}:{(index % 4) * 15:02d}:00",
                "opening_price": close - 0.2,
                "high_price": close + 0.5,
                "low_price": close - 0.5,
                "trade_price": close,
                "candle_acc_trade_volume": 10 + index,
            }
        )
    return rows


class IndicatorTests(unittest.TestCase):
    def test_buy_threshold_allows_one_optional_check_to_wait(self):
        checks = {
            "market_mode": True,
            "entry_setup": True,
            "confirmation": False,
            "volume": True,
            "timeframes": True,
            "market_guard": True,
        }
        self.assertTrue(buy_threshold_met(checks))

    def test_buy_threshold_keeps_required_safety_checks(self):
        checks = {
            "market_mode": False,
            "entry_setup": True,
            "confirmation": True,
            "volume": True,
            "timeframes": True,
            "market_guard": True,
        }
        self.assertFalse(buy_threshold_met(checks))

        checks["market_mode"] = True
        checks["market_guard"] = False
        self.assertFalse(buy_threshold_met(checks))

    def test_calculates_expected_columns(self):
        frame = calculate_indicators(fake_candles())
        for column in (
            "bb_upper",
            "bb_lower",
            "ema_fast",
            "ema_slow",
            "ema_regime",
            "rsi",
            "atr",
            "adx",
            "atr_rate",
        ):
            self.assertIn(column, frame.columns)
        signal = signal_snapshot(frame)
        self.assertIn("buy_score", signal)
        self.assertIn("buy_signal", signal)
        self.assertIn("sell_signal", signal)
        self.assertIn(signal["regime"], {"bullish", "sideways", "bearish"})
        self.assertIn("regime", signal["buy_checks"])
        self.assertGreaterEqual(signal["rsi"], 0)
        self.assertLessEqual(signal["rsi"], 100)

    def test_rsi_handles_one_way_and_flat_prices(self):
        rising = _rsi(pd.Series(range(1, 40)))
        flat = _rsi(pd.Series([100] * 40))
        self.assertEqual(float(rising.iloc[-1]), 100)
        self.assertEqual(float(flat.iloc[-1]), 50)

    def test_current_candle_is_excluded_from_signals(self):
        rows = fake_candles()
        rows[-1]["candle_date_time_kst"] = "2999-01-01T00:00:00"
        self.assertEqual(len(completed_candles(rows, 15)), len(rows) - 1)

    def test_adaptive_strategy_selects_trend_mode(self):
        frame = calculate_indicators(fake_candles())
        trend = {
            "state": "bullish",
            "trend_ok": True,
            "adx": 25,
            "atr_rate": 0.01,
        }
        signal = adaptive_signal_snapshot(
            frame,
            {"60": trend, "240": trend},
            {"240": trend},
            True,
        )
        self.assertIn(
            signal["strategy_mode"],
            {"trend_pullback", "trend_breakout"},
        )
        self.assertEqual(len(signal["buy_checks"]), 6)


if __name__ == "__main__":
    unittest.main()
